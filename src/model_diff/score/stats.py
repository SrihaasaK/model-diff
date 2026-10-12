"""Small, dependency-free statistics used in scores and the report."""

from __future__ import annotations

from math import comb, sqrt


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(only_a_right: int, only_b_right: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pair counts.

    Under the null each discordant case is equally likely to favour either
    model, so the count favouring one side is Binomial(n, 0.5).
    """
    n = only_a_right + only_b_right
    if n == 0:
        return 1.0
    k = min(only_a_right, only_b_right)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)
