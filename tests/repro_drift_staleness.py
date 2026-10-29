#!/usr/bin/env python3
"""
Reproduction of the drift failure in a sandbox simulation (no Mininet), and the numbers behind the fix.

Model: a client clock with a 50 ppm oscillator drift, polled once a second. Each exchange has an
independent random delay per direction (0.03 ms + exponential, mean 0.04 ms), so RTT and the
one-way asymmetry both vary like the idle Mininet path. The loop is the simplest discipline: slew at
filtered_offset / poll, capped at 500 ppm. Variants differ only in the filter:

  raw      min-RTT window, stored offsets NOT corrected for adjustments made since (cause a)
  min_rtt  min-RTT window, offsets corrected                                      (the failing case)
  age      corrected offsets, ranked by rtt/2 + age*phi                           (fix b)
  age+f    as age, plus the drift estimate removed from stale offsets (oracle 50 ppm here)

Bound checked per steady poll (second half): |true_error| <= previous filtered_rtt/2 + drift*poll.

    python3 tests/repro_drift_staleness.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server_client"))
from agefilter import AgeFilter  # noqa: E402


def simulate(variant, seed, phi_ppm=100.0, drift_ppm=50.0, polls=60, cap=500.0, dt=1.0):
    rnd = random.Random(seed)
    filt = AgeFilter(8, 0.0 if variant in ("raw", "min_rtt") else phi_ppm)
    t_ns, corr_ns, rate = 0, 0.0, 0.0
    rows, prev_frtt = [], None
    for _ in range(polls):
        corr_ns += rate * 1e-6 * dt * 1e9
        t_ns += int(dt * 1e9)
        err_ms = drift_ppm * 1e-6 * t_ns / 1e6 + corr_ns / 1e6              # client minus real
        d_req, d_rep = (0.03 + rnd.expovariate(1 / 0.04) for _ in range(2))
        rtt, off = d_req + d_rep, -err_ms + (d_req - d_rep) / 2
        c = 0.0 if variant == "raw" else corr_ns                              # raw: pretend no corrections were applied
        filt.add(rtt, off, c, t_ns)
        best = filt.best(c, t_ns, drift_est_ppm=drift_ppm if variant == "age+f" else 0.0)
        rows.append((err_ms, prev_frtt))
        prev_frtt = best["rtt_ms"]
        rate = max(-cap, min(cap, best["offset_ms"] / (dt * 1e3) * 1e6))
    steady = rows[len(rows) // 2:]
    bound_drift = drift_ppm * 1e-6 * dt * 1e3
    viol = sum(1 for e, pf in steady if abs(e) > pf / 2 + bound_drift)
    return max(abs(e) for e, _ in steady), sum(abs(e) for e, _ in steady) / len(steady), viol


def table(variants, seeds=200, **kw):
    out = []
    for v, phi in variants:
        res = [simulate(v, s, phi_ppm=phi, **kw) for s in range(seeds)]
        out.append((v, phi, sum(r[0] for r in res) / seeds, sum(r[1] for r in res) / seeds,
                    sum(1 for r in res if r[2] > 0), seeds))
    return out


if __name__ == "__main__":
    print(f"{'variant':<9}{'phi ppm':>8}{'mean worst |err| ms':>21}{'mean |err| ms':>15}{'legs failing bound':>20}")
    for v, phi, worst, mean, fail, n in table([("raw", 0), ("min_rtt", 0), ("age", 15), ("age", 50), ("age", 100),
                                              ("age+f", 15), ("age+f", 100)]):
        print(f"{v:<9}{phi:>8}{worst:>21.3f}{mean:>15.3f}{f'{fail}/{n}':>20}")
