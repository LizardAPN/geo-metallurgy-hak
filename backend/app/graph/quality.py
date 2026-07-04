"""Эвристики качества графа (дубли, отчёт)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

DUPLICATE_RATIO_PREFILTER = 80
DUPLICATE_TOKEN_SORT_THRESHOLD = 90
DUPLICATE_PAIR_LIMIT = 30


@dataclass
class DuplicatePair:
    label: str
    name_a: str
    name_b: str
    score: float


def find_duplicate_pairs(
    names_by_label: dict[str, list[str]],
    *,
    prefilter: int = DUPLICATE_RATIO_PREFILTER,
    threshold: int = DUPLICATE_TOKEN_SORT_THRESHOLD,
    limit: int = DUPLICATE_PAIR_LIMIT,
) -> list[DuplicatePair]:
    """Попарный поиск дублей внутри одного label (token_sort_ratio > threshold)."""
    pairs: list[DuplicatePair] = []
    for label, names in names_by_label.items():
        unique = sorted(set(names))
        n = len(unique)
        if n > 2000:
            logger.warning("Label %s has %d entities; duplicate scan may be slow", label, n)
        for i in range(n):
            a = unique[i]
            for j in range(i + 1, n):
                b = unique[j]
                if max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b)) < prefilter:
                    continue
                score = fuzz.token_sort_ratio(a, b)
                if score > threshold:
                    pairs.append(DuplicatePair(label=label, name_a=a, name_b=b, score=float(score)))
    pairs.sort(key=lambda p: p.score, reverse=True)
    return pairs[:limit]
