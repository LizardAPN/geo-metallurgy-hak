"""Unit tests for entity deduplication logic."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
from rapidfuzz import fuzz

from app.graph.dedup import (
    EntityRecord,
    MergeCluster,
    PairCandidate,
    PairDecision,
    UnionFind,
    build_merge_clusters,
    cluster_to_dict,
    decide_pair,
    experts_should_merge,
    find_candidate_pairs,
    initials_compatible,
    load_entities_from_file,
    parse_expert_name,
    pick_canon,
    _is_auto_merge,
)


def _node(id_: str, name_norm: str, degree: int = 0) -> EntityRecord:
    return EntityRecord(id=id_, name_norm=name_norm, aliases=[], degree=degree)


def test_expert_initials_merge() -> None:
    assert experts_should_merge("румянцев а.е.", "румянцев а.")


def test_expert_initials_no_merge() -> None:
    assert not experts_should_merge("румянцев а.е.", "румянцев в.е.")


def test_parse_expert_name() -> None:
    assert parse_expert_name("румянцев а.е.") == ("румянцев", ["а", "е"])
    assert parse_expert_name("румянцев а.") == ("румянцев", ["а"])
    assert parse_expert_name("smith j.") == ("smith", ["j"])


def test_initials_compatible() -> None:
    assert initials_compatible(["а"], ["а", "е"])
    assert not initials_compatible(["а", "е"], ["в", "е"])


def test_auto_merge_thresholds() -> None:
    assert _is_auto_merge(fuzzy_score=97.0, cosine_score=None)
    assert _is_auto_merge(fuzzy_score=None, cosine_score=0.98)
    assert not _is_auto_merge(fuzzy_score=90.0, cosine_score=0.93)


def test_chlorine_heap_leaching_not_auto() -> None:
    score = fuzz.token_sort_ratio("хлорное выщелачивание", "кучное выщелачивание")
    assert score < 96
    assert not _is_auto_merge(fuzzy_score=float(score), cosine_score=0.93)


def test_decide_pair_auto_fuzzy() -> None:
    a = _node("a", "обратный осмос", degree=3)
    b = _node("b", "осмос обратный", degree=1)
    cand = PairCandidate(label="Process", idx_a=0, idx_b=1, fuzzy_score=97.0)
    decision = decide_pair("Process", a, b, cand)
    assert decision.merge
    assert decision.method == "auto_fuzzy"
    assert decision.canon_id == "a"


def test_decide_pair_llm_rejected() -> None:
    a = _node("a", "хлорное выщелачивание", degree=2)
    b = _node("b", "кучное выщелачивание", degree=1)
    score = float(fuzz.token_sort_ratio(a.name_norm, b.name_norm))
    cand = PairCandidate(label="Process", idx_a=0, idx_b=1, fuzzy_score=score, cosine_score=0.93)
    decision = decide_pair("Process", a, b, cand, llm_same=False)
    assert not decision.merge
    assert decision.method == "llm"
    assert decision.llm_same is False


def test_decide_pair_expert() -> None:
    a = _node("a", "румянцев а.е.", degree=1)
    b = _node("b", "румянцев а.", degree=2)
    cand = PairCandidate(label="Expert", idx_a=0, idx_b=1, fuzzy_score=90.0)
    decision = decide_pair("Expert", a, b, cand)
    assert decision.merge
    assert decision.method == "expert"
    assert decision.canon_id == "b"


def test_pick_canon_by_degree() -> None:
    low = _node("low", "alpha", degree=1)
    high = _node("high", "beta", degree=5)
    canon = pick_canon(low, high)
    assert canon.id == "high"


def test_pick_canon_tiebreak_name_norm() -> None:
    a = _node("a", "beta", degree=3)
    b = _node("b", "alpha", degree=3)
    canon = pick_canon(a, b)
    assert canon.id == "b"


def test_union_find_clusters() -> None:
    nodes = [
        _node("a", "term a", degree=1),
        _node("b", "term b", degree=3),
        _node("c", "term c", degree=2),
    ]
    decisions = [
        PairDecision(
            label="Material",
            name_a="term a",
            name_b="term b",
            id_a="a",
            id_b="b",
            merge=True,
            method="auto_fuzzy",
            canon_id="b",
            canon_name_norm="term b",
        ),
        PairDecision(
            label="Material",
            name_a="term b",
            name_b="term c",
            id_a="b",
            id_b="c",
            merge=True,
            method="auto_cosine",
            canon_id="b",
            canon_name_norm="term b",
        ),
    ]
    clusters = build_merge_clusters("Material", nodes, decisions)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.canon.id == "b"
    assert {d.id for d in cluster.duplicates} == {"a", "c"}


def test_union_find_class() -> None:
    uf = UnionFind(4)
    uf.union(0, 1)
    uf.union(1, 2)
    assert uf.find(0) == uf.find(2)
    assert uf.find(0) != uf.find(3)


def test_cyrillic_latin_candidate_via_fuzzy() -> None:
    nodes = [
        _node("a", "обратный осмос", degree=1),
        _node("b", "reverse osmosis", degree=1),
    ]
    with patch("app.graph.dedup.embed_texts") as mock_embed:
        # High cosine similarity for cross-script synonyms
        vecs = np.array([[1.0, 0.0], [0.95, 0.31]], dtype=np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        mock_embed.return_value = vecs.tolist()
        candidates = find_candidate_pairs("Process", nodes)
    assert len(candidates) == 1
    assert candidates[0].cosine_score is not None
    assert candidates[0].cosine_score >= 0.92


def test_expert_skips_embeddings() -> None:
    nodes = [_node(str(i), f"expert {i}", degree=0) for i in range(3)]
    with patch("app.graph.dedup.embed_texts") as mock_embed:
        candidates = find_candidate_pairs("Expert", nodes)
    mock_embed.assert_not_called()
    assert isinstance(candidates, list)


def test_entities_export_roundtrip(tmp_path: Path) -> None:
    entities = {
        "Process": [
            EntityRecord(id="u1", name_norm="обратный осмос", aliases=["RO"], degree=5),
            EntityRecord(id="u2", name_norm="reverse osmosis", aliases=[], degree=2),
        ],
    }
    path = tmp_path / "entities.json"
    path.write_text(
        json.dumps(
            {
                "exported_at": "2026-01-01T00:00:00+00:00",
                "labels": {k: [asdict(n) for n in v] for k, v in entities.items()},
            }
        ),
        encoding="utf-8",
    )
    loaded = load_entities_from_file(path)
    assert len(loaded["Process"]) == 2
    assert loaded["Process"][0].id == "u1"
    assert loaded["Process"][0].degree == 5


def test_cluster_to_dict() -> None:
    canon = _node("c", "канон", degree=3)
    dup = _node("d", "дубль", degree=1)
    cluster = MergeCluster(
        label="Material",
        canon=canon,
        duplicates=[dup],
        methods=["auto_cosine"],
    )
    data = cluster_to_dict(cluster)
    assert data["canon_id"] == "c"
    assert data["duplicate_ids"] == ["d"]
