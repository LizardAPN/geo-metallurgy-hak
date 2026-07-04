"""Пост-загрузочное слияние дублей сущностей в Neo4j."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from neo4j import Driver
from rapidfuzz import fuzz

from app.config import settings
from app.extraction.extractor import strip_json_fence
from app.graph.convert import ENTITY_LABELS
from app.graph.driver import close_driver, get_driver
from app.llm import get_llm_client
from app.retrieval.embedder import embed_texts

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEDUP_PLAN_PATH = REPO_ROOT / "data" / "dedup_plan.json"
DEDUP_ENTITIES_PATH = REPO_ROOT / "data" / "dedup_entities.json"
DEDUP_LOG_PATH = REPO_ROOT / "data" / "dedup_log.jsonl"

FUZZY_CANDIDATE = 88
FUZZY_AUTO = 96
COSINE_CANDIDATE = 0.92
COSINE_AUTO = 0.97
EMBEDDING_MATRIX_LIMIT = 5000
LLM_BATCH_SIZE = 30
LLM_BATCH_RETRIES = 3

LLM_SYSTEM = (
    "Ты эксперт-металлург. Для каждой пары терминов ответь, обозначают ли они "
    "ОДНО И ТО ЖЕ понятие (не родственные, не общее/частное — именно одно). "
    "['хлорное выщелачивание' vs 'кучное выщелачивание' → false; "
    "'обратный осмос' vs 'reverse osmosis' → true; "
    "'штейн' vs 'штейн МДП' → false]. "
    'JSON: {"answers": [{"pair": i, "same": bool}]}'
)

_MERGE_CYPHER = """
MATCH (canon:%(label)s {id: $canon_id})
MATCH (dup:%(label)s) WHERE dup.id IN $dup_ids
WITH canon, collect(dup) AS dups
CALL apoc.refactor.mergeNodes(
  [canon] + dups,
  {properties: 'discard', mergeRels: true}
) YIELD node
SET node.aliases = apoc.coll.toSet(
  coalesce(node.aliases, []) + $extra_aliases + $dup_name_norms
)
RETURN node.id AS id
"""


@dataclass
class EntityRecord:
    id: str
    name_norm: str
    aliases: list[str]
    degree: int


@dataclass
class PairCandidate:
    label: str
    idx_a: int
    idx_b: int
    fuzzy_score: float | None = None
    cosine_score: float | None = None


@dataclass
class PairDecision:
    label: str
    name_a: str
    name_b: str
    id_a: str
    id_b: str
    merge: bool
    method: str
    canon_id: str | None = None
    canon_name_norm: str | None = None
    fuzzy_score: float | None = None
    cosine_score: float | None = None
    llm_same: bool | None = None


@dataclass
class MergeCluster:
    label: str
    canon: EntityRecord
    duplicates: list[EntityRecord]
    methods: list[str] = field(default_factory=list)


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def is_dry_run() -> bool:
    return os.environ.get("DRY_RUN", "1") != "0"


def parse_expert_name(name_norm: str) -> tuple[str, list[str]]:
    parts = name_norm.strip().lower().split()
    surname = parts[0] if parts else ""
    initials = [c for c in "".join(parts[1:]) if c.isalpha()]
    return surname, initials


def initials_compatible(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return long_[: len(short)] == short


def experts_should_merge(name_a: str, name_b: str) -> bool:
    surname_a, init_a = parse_expert_name(name_a)
    surname_b, init_b = parse_expert_name(name_b)
    if not surname_a or surname_a != surname_b:
        return False
    return initials_compatible(init_a, init_b)


def pick_canon(a: EntityRecord, b: EntityRecord) -> EntityRecord:
    if a.degree != b.degree:
        return a if a.degree > b.degree else b
    return a if a.name_norm <= b.name_norm else b


def fetch_all_entities(driver: Driver) -> dict[str, list[EntityRecord]]:
    return {label: fetch_entities(driver, label) for label in ENTITY_LABELS}


def export_entities_to_file(driver: Driver, path: Path) -> None:
    """Выгрузить сущности из Neo4j для офлайн-dedup (без Docker/Neo4j на GPU-ВМ)."""
    entities = fetch_all_entities(driver)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "labels": {
            label: [asdict(n) for n in nodes]
            for label, nodes in entities.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in entities.values())
    logger.info("Exported %d entities to %s", total, path)


def load_entities_from_file(path: Path) -> dict[str, list[EntityRecord]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[EntityRecord]] = {}
    for label, rows in data.get("labels", {}).items():
        result[label] = [
            EntityRecord(
                id=str(row["id"]),
                name_norm=str(row["name_norm"]),
                aliases=list(row.get("aliases") or []),
                degree=int(row.get("degree", 0)),
            )
            for row in rows
            if row.get("name_norm")
        ]
    return result


def cluster_to_dict(cluster: MergeCluster) -> dict[str, Any]:
    return {
        "label": cluster.label,
        "canon_id": cluster.canon.id,
        "canon_name_norm": cluster.canon.name_norm,
        "duplicate_ids": [d.id for d in cluster.duplicates],
        "duplicate_name_norms": [d.name_norm for d in cluster.duplicates],
        "methods": cluster.methods,
    }


def cluster_from_dict(data: dict[str, Any], nodes_by_id: dict[str, EntityRecord]) -> MergeCluster:
    canon = nodes_by_id[data["canon_id"]]
    duplicates = [nodes_by_id[did] for did in data["duplicate_ids"]]
    return MergeCluster(
        label=data["label"],
        canon=canon,
        duplicates=duplicates,
        methods=list(data.get("methods") or []),
    )


def fetch_entities(driver: Driver, label: str) -> list[EntityRecord]:
    cypher = f"""
    MATCH (n:{label})
    RETURN n.id AS id,
           n.name_norm AS name_norm,
           coalesce(n.aliases, []) AS aliases,
           count {{ (n)--() }} AS degree
    ORDER BY name_norm
    """
    with driver.session() as session:
        rows = [dict(r) for r in session.run(cypher)]
    return [
        EntityRecord(
            id=str(row["id"]),
            name_norm=str(row["name_norm"]),
            aliases=list(row["aliases"] or []),
            degree=int(row["degree"]),
        )
        for row in rows
        if row.get("name_norm")
    ]


def _fuzzy_pairs(nodes: list[EntityRecord], label: str) -> dict[tuple[int, int], float]:
    n = len(nodes)
    if n > 2000:
        logger.warning("Label %s has %d entities; fuzzy scan may be slow", label, n)
    scores: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            score = float(fuzz.token_sort_ratio(nodes[i].name_norm, nodes[j].name_norm))
            if score >= FUZZY_CANDIDATE:
                scores[(i, j)] = score
    return scores


def _embedding_pairs(
    nodes: list[EntityRecord],
) -> dict[tuple[int, int], float]:
    texts = [n.name_norm for n in nodes]
    vecs = embed_texts(texts)
    mat = np.asarray(vecs, dtype=np.float32)
    sim = mat @ mat.T
    n = len(nodes)
    scores: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            score = float(sim[i, j])
            if score >= COSINE_CANDIDATE:
                scores[(i, j)] = score
    return scores


def find_candidate_pairs(label: str, nodes: list[EntityRecord]) -> list[PairCandidate]:
    if len(nodes) < 2:
        return []

    fuzzy_scores = _fuzzy_pairs(nodes, label)
    cosine_scores: dict[tuple[int, int], float] = {}
    if label != "Expert" and len(nodes) < EMBEDDING_MATRIX_LIMIT:
        cosine_scores = _embedding_pairs(nodes)
    elif label != "Expert" and len(nodes) >= EMBEDDING_MATRIX_LIMIT:
        logger.warning(
            "Label %s has %d entities; embedding path skipped (limit %d)",
            label,
            len(nodes),
            EMBEDDING_MATRIX_LIMIT,
        )

    all_keys = set(fuzzy_scores) | set(cosine_scores)
    candidates: list[PairCandidate] = []
    for key in sorted(all_keys):
        i, j = key
        candidates.append(
            PairCandidate(
                label=label,
                idx_a=i,
                idx_b=j,
                fuzzy_score=fuzzy_scores.get(key),
                cosine_score=cosine_scores.get(key),
            )
        )
    return candidates


def _auto_method(fuzzy_score: float | None, cosine_score: float | None) -> str:
    if cosine_score is not None and cosine_score >= COSINE_AUTO:
        return "auto_cosine"
    return "auto_fuzzy"


def _is_auto_merge(fuzzy_score: float | None, cosine_score: float | None) -> bool:
    if cosine_score is not None and cosine_score >= COSINE_AUTO:
        return True
    return fuzzy_score is not None and fuzzy_score >= FUZZY_AUTO


def decide_pair(
    label: str,
    node_a: EntityRecord,
    node_b: EntityRecord,
    candidate: PairCandidate,
    *,
    llm_same: bool | None = None,
) -> PairDecision:
    fuzzy_score = candidate.fuzzy_score
    cosine_score = candidate.cosine_score

    if label == "Expert":
        merge = experts_should_merge(node_a.name_norm, node_b.name_norm)
        canon = pick_canon(node_a, node_b) if merge else None
        return PairDecision(
            label=label,
            name_a=node_a.name_norm,
            name_b=node_b.name_norm,
            id_a=node_a.id,
            id_b=node_b.id,
            merge=merge,
            method="expert",
            canon_id=canon.id if canon else None,
            canon_name_norm=canon.name_norm if canon else None,
            fuzzy_score=fuzzy_score,
            cosine_score=cosine_score,
        )

    if _is_auto_merge(fuzzy_score, cosine_score):
        canon = pick_canon(node_a, node_b)
        return PairDecision(
            label=label,
            name_a=node_a.name_norm,
            name_b=node_b.name_norm,
            id_a=node_a.id,
            id_b=node_b.id,
            merge=True,
            method=_auto_method(fuzzy_score, cosine_score),
            canon_id=canon.id,
            canon_name_norm=canon.name_norm,
            fuzzy_score=fuzzy_score,
            cosine_score=cosine_score,
        )

    merge = bool(llm_same)
    canon = pick_canon(node_a, node_b) if merge else None
    return PairDecision(
        label=label,
        name_a=node_a.name_norm,
        name_b=node_b.name_norm,
        id_a=node_a.id,
        id_b=node_b.id,
        merge=merge,
        method="llm",
        canon_id=canon.id if canon else None,
        canon_name_norm=canon.name_norm if canon else None,
        fuzzy_score=fuzzy_score,
        cosine_score=cosine_score,
        llm_same=llm_same,
    )


def _build_llm_user(pairs: list[tuple[str, str]]) -> str:
    lines = [f'{i}. "{a}" vs "{b}"' for i, (a, b) in enumerate(pairs)]
    return "Пары терминов:\n" + "\n".join(lines)


def parse_llm_answers(raw: str, *, expected: int) -> list[bool]:
    """Разобрать ответ LLM; неполные ответы дополняются False."""
    cleaned = strip_json_fence(raw)
    if not cleaned:
        raise ValueError("empty LLM response")
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data).__name__}")
    answers = data.get("answers")
    if not isinstance(answers, list):
        raise ValueError("missing or invalid 'answers' array")
    by_idx: dict[int, bool] = {}
    for item in answers:
        if not isinstance(item, dict):
            continue
        if "pair" not in item or "same" not in item:
            continue
        by_idx[int(item["pair"])] = bool(item["same"])
    if not by_idx:
        raise ValueError("no valid entries in 'answers'")
    return [by_idx.get(i, False) for i in range(expected)]


async def _llm_batch(pairs: list[tuple[str, str]]) -> list[bool]:
    user = _build_llm_user(pairs)
    llm = get_llm_client()
    last_error: Exception | None = None
    for attempt in range(1, LLM_BATCH_RETRIES + 1):
        raw = await llm.complete_json(LLM_SYSTEM, user, temperature=0.0, max_tokens=2000)
        try:
            return parse_llm_answers(raw, expected=len(pairs))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            last_error = exc
            preview = (raw or "").strip().replace("\n", " ")[:200]
            logger.warning(
                "LLM batch parse failed (attempt %d/%d): %s; raw=%r",
                attempt,
                LLM_BATCH_RETRIES,
                exc,
                preview,
            )
    raise RuntimeError(f"LLM batch failed after {LLM_BATCH_RETRIES} attempts") from last_error


async def resolve_llm_pairs(
    pending: list[tuple[PairCandidate, EntityRecord, EntityRecord]],
) -> list[bool]:
    results: list[bool] = []
    for start in range(0, len(pending), LLM_BATCH_SIZE):
        batch = pending[start : start + LLM_BATCH_SIZE]
        pair_names = [(a.name_norm, b.name_norm) for _, a, b in batch]
        batch_results = await _llm_batch(pair_names)
        results.extend(batch_results)
    return results


def build_merge_clusters(
    label: str,
    nodes: list[EntityRecord],
    decisions: list[PairDecision],
) -> list[MergeCluster]:
    merge_decisions = [d for d in decisions if d.merge]
    if not merge_decisions:
        return []

    id_to_idx = {n.id: i for i, n in enumerate(nodes)}
    uf = UnionFind(len(nodes))
    methods_by_edge: dict[tuple[int, int], set[str]] = {}

    for d in merge_decisions:
        ia = id_to_idx.get(d.id_a)
        ib = id_to_idx.get(d.id_b)
        if ia is None or ib is None:
            continue
        uf.union(ia, ib)
        edge = (min(ia, ib), max(ia, ib))
        methods_by_edge.setdefault(edge, set()).add(d.method)

    clusters: dict[int, list[int]] = {}
    for i in range(len(nodes)):
        root = uf.find(i)
        clusters.setdefault(root, []).append(i)

    result: list[MergeCluster] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        member_nodes = [nodes[i] for i in members]
        canon = min(member_nodes, key=lambda n: (-n.degree, n.name_norm))

        duplicates = [n for n in member_nodes if n.id != canon.id]
        cluster_methods: list[str] = []
        for i in members:
            for j in members:
                if i >= j:
                    continue
                edge = (min(i, j), max(i, j))
                cluster_methods.extend(sorted(methods_by_edge.get(edge, set())))

        result.append(
            MergeCluster(
                label=label,
                canon=canon,
                duplicates=duplicates,
                methods=sorted(set(cluster_methods)),
            )
        )
    return result


def _count_entities(driver: Driver) -> int:
    cypher = """
    MATCH (n)
    WHERE any(l IN labels(n) WHERE l IN $labels)
    RETURN count(n) AS cnt
    """
    with driver.session() as session:
        row = session.run(cypher, labels=ENTITY_LABELS).single()
    return int(row["cnt"]) if row else 0


def _count_edges(driver: Driver) -> int:
    cypher = "MATCH ()-[r]->() RETURN count(r) AS cnt"
    with driver.session() as session:
        row = session.run(cypher).single()
    return int(row["cnt"]) if row else 0


def execute_cluster(driver: Driver, cluster: MergeCluster) -> int:
    dup_ids = [d.id for d in cluster.duplicates]
    extra_aliases: list[str] = []
    dup_name_norms: list[str] = []
    rewired = sum(d.degree for d in cluster.duplicates)

    for dup in cluster.duplicates:
        extra_aliases.extend(dup.aliases)
        if dup.name_norm != cluster.canon.name_norm:
            dup_name_norms.append(dup.name_norm)

    cypher = _MERGE_CYPHER % {"label": cluster.label}
    with driver.session() as session:
        session.run(
            cypher,
            canon_id=cluster.canon.id,
            dup_ids=dup_ids,
            extra_aliases=extra_aliases,
            dup_name_norms=dup_name_norms,
        )
    return rewired


def append_merge_log(cluster: MergeCluster, rewired_edges: int) -> None:
    DEDUP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "label": cluster.label,
        "canon_id": cluster.canon.id,
        "canon_name_norm": cluster.canon.name_norm,
        "merged_ids": [d.id for d in cluster.duplicates],
        "merged_name_norms": [d.name_norm for d in cluster.duplicates],
        "methods": cluster.methods,
        "rewired_edges": rewired_edges,
    }
    with DEDUP_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def decision_to_dict(d: PairDecision) -> dict[str, Any]:
    return asdict(d)


def print_decisions(decisions: list[PairDecision]) -> None:
    print(f"\n{'label':<14} {'merge':<6} {'method':<12} {'pair':<60} canon")
    print("-" * 110)
    for d in decisions:
        pair = f"{d.name_a} <-> {d.name_b}"
        canon = d.canon_name_norm or "-"
        print(f"{d.label:<14} {str(d.merge):<6} {d.method:<12} {pair:<60} {canon}")


def write_plan(
    decisions: list[PairDecision],
    clusters: list[MergeCluster],
    *,
    dry_run: bool,
    path: Path,
    source: str,
) -> None:
    to_merge = sum(1 for d in decisions if d.merge)
    by_method: dict[str, int] = {}
    for d in decisions:
        by_method[d.method] = by_method.get(d.method, 0) + 1

    payload = {
        "dry_run": dry_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "decisions": [decision_to_dict(d) for d in decisions],
        "clusters": [cluster_to_dict(c) for c in clusters],
        "summary": {
            "candidates": len(decisions),
            "to_merge": to_merge,
            "clusters": len(clusters),
            "nodes_to_merge": sum(len(c.duplicates) for c in clusters),
            "by_method": by_method,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Wrote plan to %s", path)


async def process_label_nodes(
    label: str,
    nodes: list[EntityRecord],
) -> tuple[list[PairDecision], list[MergeCluster]]:
    if len(nodes) < 2:
        return [], []

    candidates = find_candidate_pairs(label, nodes)
    if not candidates:
        return [], []

    pending_llm: list[tuple[PairCandidate, EntityRecord, EntityRecord]] = []
    pre_decisions: list[PairDecision] = []

    for cand in candidates:
        node_a = nodes[cand.idx_a]
        node_b = nodes[cand.idx_b]
        if label == "Expert":
            pre_decisions.append(decide_pair(label, node_a, node_b, cand))
        elif _is_auto_merge(cand.fuzzy_score, cand.cosine_score):
            pre_decisions.append(decide_pair(label, node_a, node_b, cand))
        else:
            pending_llm.append((cand, node_a, node_b))

    if pending_llm:
        llm_results = await resolve_llm_pairs(pending_llm)
        for (cand, node_a, node_b), llm_same in zip(pending_llm, llm_results, strict=True):
            pre_decisions.append(
                decide_pair(label, node_a, node_b, cand, llm_same=llm_same)
            )

    clusters = build_merge_clusters(label, nodes, pre_decisions)
    return pre_decisions, clusters


async def process_label(
    driver: Driver,
    label: str,
) -> tuple[list[PairDecision], list[MergeCluster]]:
    nodes = fetch_entities(driver, label)
    return await process_label_nodes(label, nodes)


async def run_plan_phase(
    entities_by_label: dict[str, list[EntityRecord]],
    *,
    dry_run: bool,
    plan_path: Path,
    source: str,
) -> list[MergeCluster]:
    all_decisions: list[PairDecision] = []
    all_clusters: list[MergeCluster] = []

    for label in ENTITY_LABELS:
        nodes = entities_by_label.get(label, [])
        if not nodes:
            continue
        logger.info("Processing label %s (%d nodes)", label, len(nodes))
        decisions, clusters = await process_label_nodes(label, nodes)
        all_decisions.extend(decisions)
        all_clusters.extend(clusters)

    print_decisions(all_decisions)
    write_plan(all_decisions, all_clusters, dry_run=dry_run, path=plan_path, source=source)

    to_merge_nodes = sum(len(c.duplicates) for c in all_clusters)
    if dry_run:
        print(f"\n[DRY RUN] Кандидатов: {len(all_decisions)}, к слиянию узлов: {to_merge_nodes}")
    return all_clusters


def load_clusters_from_plan(
    plan_path: Path,
    driver: Driver,
) -> list[MergeCluster]:
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    cluster_rows = data.get("clusters") or []
    if not cluster_rows:
        raise ValueError(f"No clusters in plan: {plan_path}")

    clusters: list[MergeCluster] = []
    for row in cluster_rows:
        label = row["label"]
        ids = [row["canon_id"], *row["duplicate_ids"]]
        cypher = f"""
        MATCH (n:{label})
        WHERE n.id IN $ids
        RETURN n.id AS id,
               n.name_norm AS name_norm,
               coalesce(n.aliases, []) AS aliases,
               count {{ (n)--() }} AS degree
        """
        with driver.session() as session:
            nodes = [
                EntityRecord(
                    id=str(r["id"]),
                    name_norm=str(r["name_norm"]),
                    aliases=list(r["aliases"] or []),
                    degree=int(r["degree"]),
                )
                for r in session.run(cypher, ids=ids)
            ]
        nodes_by_id = {n.id: n for n in nodes}
        missing = set(ids) - set(nodes_by_id)
        if missing:
            raise ValueError(f"Nodes not found in Neo4j for label {label}: {missing}")
        clusters.append(cluster_from_dict(row, nodes_by_id))
    return clusters


def apply_clusters(driver: Driver, clusters: list[MergeCluster]) -> int:
    if not clusters:
        print("\nНет узлов для слияния.")
        return 0

    nodes_before = _count_entities(driver)
    edges_before = _count_edges(driver)

    total_rewired = 0
    for cluster in clusters:
        rewired = execute_cluster(driver, cluster)
        total_rewired += rewired
        append_merge_log(cluster, rewired)

    nodes_after = _count_entities(driver)
    edges_after = _count_edges(driver)
    merged_count = nodes_before - nodes_after

    print(f"\nслито {merged_count} узлов, перевешано {total_rewired} рёбер")
    if edges_after < edges_before:
        logger.warning(
            "Edge count decreased: %d -> %d (expected no loss)",
            edges_before,
            edges_after,
        )
    else:
        print(f"рёбер в графе: {edges_before} -> {edges_after}")
    return 0


async def _run_offline_plan(
    entities: dict[str, list[EntityRecord]],
    *,
    plan_path: Path,
    source: str,
) -> int:
    await run_plan_phase(entities, dry_run=True, plan_path=plan_path, source=source)
    return 0


async def run_dedup(driver: Driver, *, dry_run: bool, plan_path: Path) -> int:
    entities = fetch_all_entities(driver)
    clusters = await run_plan_phase(
        entities,
        dry_run=dry_run,
        plan_path=plan_path,
        source="neo4j",
    )
    if dry_run:
        return 0
    return apply_clusters(driver, clusters)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Пост-загрузочное слияние дублей сущностей",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Выгрузить сущности из Neo4j в JSON (для офлайн-dedup на GPU-ВМ)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="JSON с сущностями (без Neo4j): data/dedup_entities.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить готовый dedup_plan.json к Neo4j",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=DEDUP_PLAN_PATH,
        help="Путь к плану (чтение/запись)",
    )
    parser.add_argument(
        "--entities-out",
        type=Path,
        default=DEDUP_ENTITIES_PATH,
        help="Путь для --export",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dry_run = is_dry_run()

    if args.export:
        driver = get_driver()
        try:
            export_entities_to_file(driver, args.entities_out)
            return 0
        finally:
            close_driver()

    if args.apply:
        if dry_run:
            logger.error("--apply requires DRY_RUN=0")
            return 1
        driver = get_driver()
        try:
            clusters = load_clusters_from_plan(args.plan, driver)
            return apply_clusters(driver, clusters)
        finally:
            close_driver()

    if not settings.llm_api_key:
        logger.warning("LLM_API_KEY is not set; LLM pairs will fail if any exist")

    if args.input is not None:
        input_path = args.input if args.input.is_absolute() else REPO_ROOT / args.input
        if not input_path.exists():
            logger.error("Input file not found: %s", input_path)
            return 1
        logger.info("Offline mode: reading entities from %s", input_path)
        entities = load_entities_from_file(input_path)
        if not dry_run:
            logger.error("Offline mode only builds a plan; use --apply on Neo4j host with DRY_RUN=0")
            return 1
        return asyncio.run(
            _run_offline_plan(
                entities,
                plan_path=args.plan if args.plan.is_absolute() else REPO_ROOT / args.plan,
                source=str(input_path),
            )
        )

    driver = get_driver()
    try:
        if not dry_run:
            logger.info("EXECUTE mode (DRY_RUN=0)")
        else:
            logger.info("DRY RUN mode (default); set DRY_RUN=0 to execute merges")

        plan_path = args.plan if args.plan.is_absolute() else REPO_ROOT / args.plan
        return asyncio.run(run_dedup(driver, dry_run=dry_run, plan_path=plan_path))
    finally:
        close_driver()


if __name__ == "__main__":
    sys.exit(main())
