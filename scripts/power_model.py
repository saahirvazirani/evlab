"""Monte Carlo power model for `evlab diff` (Fisher exact + Holm over 5 areas).

Standard library only. Uses evlab.stats, the same functions the diff command uses.
Model: independent binomial draws. One area gets a true shift, the other four stay
at the base rate. Probe clustering is ignored, so these numbers are optimistic.

Usage: python3 scripts/power_model.py [--trials 400] [--seed 20261027]
"""
import argparse, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from evlab.stats import fisher_exact_two_sided, holm

AREAS = 5
_cache = {}

def fisher(n, a, c):
    """p for baseline a/n fail vs current c/n fail, cached (symmetric in a, c)."""
    key = (n, min(a, c), max(a, c))
    if key not in _cache:
        _cache[key] = fisher_exact_two_sided(a, n - a, c, n - c)
    return _cache[key]

def power(n, base, delta, trials, rng):
    """Share of trials where the shifted area is flagged REGRESSION (Holm p < 0.05, rate up)."""
    hit = 0
    for _ in range(trials):
        pv, up = {}, {}
        for i in range(AREAS):
            p_cur = min(1.0, base + delta) if i == 0 else base
            a = rng.binomialvariate(n, base)
            c = rng.binomialvariate(n, p_cur)
            pv[i] = fisher(n, a, c)
            up[i] = c > a
        if holm(pv)[0] < 0.05 and up[0]:
            hit += 1
    return hit / trials

def mde(n, base, trials, seed, target=0.8):
    """Smallest delta (step 0.01) with power >= target, by bisection (power rises with delta)."""
    lo, hi = 1, int(round((1 - base) * 100))
    if power(n, base, hi / 100, trials, random.Random(seed)) < target:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if power(n, base, mid / 100, trials, random.Random(seed + mid)) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo

def n_needed(base, delta, trials, seed, target=0.8):
    """Smallest per-area n (step 10) with power >= target for a given true shift."""
    n = 50
    while n <= 1500:
        if power(n, base, delta, trials, random.Random(seed + n)) >= target:
            return n
        n += 10
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20261027)
    ap.add_argument("--ns", default="48,100,200,400,800")
    ap.add_argument("--bases", default="0.05,0.10,0.20")
    a = ap.parse_args()
    ns = [int(x) for x in a.ns.split(",")]
    bases = [float(x) for x in a.bases.split(",")]
    print(f"Minimum detectable increase (points), 80% power, Holm over {AREAS} areas, "
          f"{a.trials} trials, seed {a.seed}")
    print("| Per-area n | " + " | ".join(f"Base {int(b*100)}%" for b in bases) + " |")
    print("|---|" + "---|" * len(bases))
    for n in ns:
        cells = []
        for b in bases:
            d = mde(n, b, a.trials, a.seed)
            cells.append("n/a" if d is None else f"+{d}")
        print(f"| {n} | " + " | ".join(cells) + " |", flush=True)
    print()
    print("Per-area n needed for 80% power at a given true increase")
    print("| Base rate | +10 points | +15 points |")
    print("|---|---|---|")
    for b in bases:
        print(f"| {int(b*100)}% | {n_needed(b, 0.10, a.trials, a.seed)} | "
              f"{n_needed(b, 0.15, a.trials, a.seed)} |", flush=True)

if __name__ == "__main__":
    main()
