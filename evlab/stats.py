"""Two-sided Fisher's exact test and Holm correction, standard library only."""
from __future__ import annotations

from math import comb


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """2x2 table [[a, b], [c, d]]. Returns two-sided p-value."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d
    if n == 0:
        return 1.0
    denom = comb(n, c1)

    def p(x):
        return comb(r1, x) * comb(r2, c1 - x) / denom

    p_obs = p(a)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= p_obs * (1 + 1e-9)))


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = running
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    ph = k / n
    den = 1 + z * z / n
    centre = (ph + z * z / (2 * n)) / den
    half = z * ((ph * (1 - ph) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for (rater_a, rater_b) label pairs. None when undefined."""
    n = len(pairs)
    if n == 0:
        return None
    cats = {x for p in pairs for x in p}
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n) for c in cats)
    if pe >= 1:
        return 1.0 if po == 1 else None
    return (po - pe) / (1 - pe)


def bootstrap_ci(pairs: list, fn, n_boot: int = 1000, seed: int = 0, level: float = 0.95) -> tuple[float, float] | None:
    """Percentile bootstrap interval for fn(pairs). Seeded, so reruns give the same interval."""
    import random
    if not pairs:
        return None
    rng = random.Random(seed)
    vals = sorted(v for v in (fn([rng.choice(pairs) for _ in pairs]) for _ in range(n_boot)) if v is not None)
    if not vals:
        return None
    lo, hi = vals[int((1 - level) / 2 * len(vals))], vals[min(len(vals) - 1, int((1 + level) / 2 * len(vals)))]
    return (lo, hi)


def confusion(pairs: list[tuple[str, str]], cats: list[str]) -> dict[str, dict[str, int]]:
    """Rows: first rater (hand label). Columns: second rater."""
    m = {a: {b: 0 for b in cats} for a in cats}
    for a, b in pairs:
        m.setdefault(a, {c: 0 for c in cats}).setdefault(b, 0)
        m[a][b] += 1
    return m
