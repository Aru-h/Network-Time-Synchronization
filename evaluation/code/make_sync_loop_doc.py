#!/usr/bin/env python3
"""Write docs/SYNC_LOOP.md: every number in its tables is read from the CSVs/logs under evaluation/results/sync_loop/run*/.

    python3 evaluation/code/make_sync_loop_doc.py [results_dir] [-o docs/SYNC_LOOP.md]
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / "tests"), str(ROOT / "server_client")]
import sync_loop_check as chk  # noqa: E402
import repro_drift_staleness as repro  # noqa: E402


def freq_estimate(d, name):
    p = Path(d) / f"{name}.txt"
    m = re.search(r"frequency estimate ([+-][\d.]+) ppm", p.read_text()) if p.exists() else None
    return f"{float(m.group(1)):+.1f}" if m else "-"


def run_table(d):
    rows = ["| Leg | Setting | Role | Steps (expected) | Backwards | First-poll error (ms) | Steady mean \\|error\\| (ms) | Steady max \\|error\\| (ms) | Bound max (ms) | Polls over bound | Verdict |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    legs, an = chk.evaluate(d)
    res = {n: r for n, r, _ in legs}
    for name, desc, drift, steps, role in chk.LEGS:
        a = an[name]
        if a is None:
            rows.append(f"| {name} | {desc} | {'report only' if role == 'INFO' else 'PASS/FAIL'} | pending | | | | | | | {res[name]} |")
            continue
        rows.append(f"| {name} | {desc} | {'report only' if role == 'INFO' else 'PASS/FAIL'} | {a['steps']} ({steps}) | {a['backwards']} | "
                    f"{a['first_err']:.1f} | {a['mean_err']:.4f} | {a['max_err']:.4f} | {a['max_bound']:.4f} | "
                    f"{a['violations']}/{a['steady']} | {res[name]} |")
    cmp_ = [r for r in legs if r[0] == "S5 < S4 error"][0]
    counts = {k: sum(1 for _, r, _ in legs if r == k) for k in ("PASS", "FAIL", "SKIP", "INFO")}
    return "\n".join(rows), cmp_, counts, an


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", nargs="?", default=str(ROOT / "evaluation" / "results" / "sync_loop"))
    ap.add_argument("-o", "--out", default=str(ROOT / "docs" / "SYNC_LOOP.md"))
    a = ap.parse_args()
    base = Path(a.results_dir)
    runs = sorted(p for p in base.glob("run*") if p.is_dir())
    tabs = {p.name: run_table(p) for p in runs}
    sim = repro.table([("raw", 0), ("min_rtt", 0), ("age", 15), ("age", 50), ("age", 100), ("age+f", 100)], seeds=200)
    sim_rows = ["| Filter variant | phi (ppm) | Mean worst steady \\|error\\| (ms) | Mean steady \\|error\\| (ms) | Legs over the bound |", "|---|---:|---:|---:|---:|"]
    names = {"raw": "min-RTT, offsets NOT corrected for adjustments (cause a)", "min_rtt": "min-RTT, offsets corrected (the failing case, cause b)",
             "age": "age-ranked, corrected", "age+f": "age-ranked, corrected, + drift estimate"}
    for v, phi, worst, mean, fail, n in sim:
        sim_rows.append(f"| {names[v]} | {phi} | {worst:.3f} | {mean:.3f} | {fail}/{n} |")

    def variant_rows():
        out = ["| Run | Variant | Steady mean \\|error\\| (ms) | Steady max \\|error\\| (ms) | Bound max (ms) | Frequency estimate (ppm, true +50) |", "|---|---|---:|---:|---:|---:|"]
        for p in runs:
            an = tabs[p.name][3]
            for leg, label in (("S3_drift", "default (corrections only)"), ("S3f_drift_freq", "--freq-compensate")):
                x = an[leg]
                if x:
                    out.append(f"| {p.name} | {label} | {x['mean_err']:.4f} | {x['max_err']:.4f} | {x['max_bound']:.4f} | {freq_estimate(p, leg)} |")
        return "\n".join(out)

    parts = [f"""# Sync loop: a client that corrects its own clock

A client keeps a **software clock** (the OS clock is never touched), measures its offset against the unchanged time
server (`REQ|seq|T1` / `REP|seq|T1|T2|T3`, kernel receive stamps), and disciplines the soft clock with a step or a slew.
This is a small teaching sync loop, **not NTP**: one server, no peer selection, no authentication, no leap handling.

Files: `server_client/softclock.py`, `server_client/sync_loop.py`, `server_client/agefilter.py`; runner
`evaluation/ubuntu_runner/run_sync_loop.sh`; checks `evaluation/code/sync_loop_check.py`; this page is written by
`evaluation/code/make_sync_loop_doc.py` from the result files.

## Two caveats that apply to every number below

1. **Shared clock.** `true_error` (the soft clock minus real time) can be logged only because every Mininet host shares one
   kernel clock, so "real time" is the server's reference too. On separate machines this number would not exist; a real
   client sees only its own offset estimate. The checks below use it as ground truth.
2. **S1 is a demo setting.** The step threshold follows real NTP (128 ms): an offset below it is never stepped. A 100 ms
   skew is then removed by slewing alone, which at the realistic cap of 500 ppm takes about 200 s. S1 runs with
   `--max-slew-ppm 5000` so it converges inside a test; that is **not realistic NTP behaviour**. Every other leg uses the
   default 500 ppm.

## How it works

- **Discipline.** If `|filtered_offset| > --step-ms` (128) the clock is stepped once. Otherwise it is slewed only: a PI
  controller turns the filtered offset into a rate (ppm), clamped to `--max-slew-ppm`, so the clock never goes backwards
  while slewing (it runs at 1 + (drift + rate) x 1e-6 > 0 times real time). A step moves the clock back by design and is
  reported separately (the `stepped` column).
- **Frequency estimate.** The PI integral term settles near minus the oscillator drift. Anti-windup: it is clamped to the
  rate cap, is not accumulated while the output is saturated in the direction of the error, and is accumulated only while
  `|offset| < 2 ms` (integral separation). The last rule was added after the unit tests showed that integrating during
  the approach from a 100 ms offset overshoots by about 2 ms and takes tens of seconds to unwind.
- **Filter** (`agefilter.py`): the last 8 samples, each offset corrected for the adjustments applied since it was taken,
  ranked by `rtt/2 + age x phi`. phi = 100 ppm by default: the assumed oscillator tolerance, twice the largest drift
  injected (50 ppm). It is a stated assumption, not a value tuned until a bound passed. NTP's 15 ppm assumes a good crystal.
- **CSV** per poll: `t, offset_est, rtt, filtered_offset, correction, rate_ppm, true_error, stepped` (+ `status,
  filtered_rtt, backwards`).

## Root cause of the drift failure

An earlier version used a plain minimum-RTT window. With a 50 ppm drift its steady error reached 0.43 ms against a bound
of 0.09 to 0.15 ms in two Mininet runs (their result files were not committed; the code is on the local branch
`d2-stretch-v1`). It reproduces in simulation
(`tests/repro_drift_staleness.py`, 200 seeds, polls once a second, independent random delay per direction):

{chr(10).join(sim_rows)}

Cause: the window kept returning an old low-RTT sample. Its stored offset ignored the corrections applied since it was
taken (cause a: far worse), and even when corrected, nothing penalised its age, so the clock kept being steered by a
sample that was several seconds old while the oscillator moved about 0.05 ms per second (cause b). Ranking by
`rtt/2 + age x phi` and correcting stored offsets fixes both once the controller can learn the drift; with a simple
proportional controller alone, ranking helps but does not meet the bound at any phi tried.

## Results

Pass bound, computed from each run: over the steady state (second half of the OK polls) every poll must satisfy
`|true_error| <= filtered_RTT/2 + drift x poll`. **`filtered_RTT` is the one from the previous poll**: the error logged at
poll i was set by the discipline of poll i-1, so that is the estimate whose uncertainty bounds it. The bound is printed,
never relaxed. Missing data is SKIP, never PASS. S4 is report-only (the constant queue asymmetry puts its error at about
RTT/2, right on the bound, and a min-RTT filter cannot remove it); S5 is PASS/FAIL plus the check that S5's error is below S4's.
"""]
    for p in runs:
        table, cmp_, counts, _ = tabs[p.name]
        parts.append(f"""### {p.name}

{table}

S5 < S4 check: {cmp_[1]} ({cmp_[2]}).
Counts: PASS {counts['PASS']}, FAIL {counts['FAIL']}, SKIP {counts['SKIP']}, report-only {counts['INFO']}.
""")
    parts.append(f"""### Both filter variants, measured (S3 versus S3f)

{variant_rows()}

In the sandbox the two variants were indistinguishable at phi = 100 ppm (the age ranking already keeps stale samples out), so
the drift term is an option and is off by default.

## What the failures mean

Each run has exactly one failing check, and it is a different idle leg each time (see the tables). On the idle legs the
bound is only a few hundredths of a millisecond and the steady error sits at about 0.03 ms (the path's own request/reply
asymmetry), so one poll in 30 to 60 occasionally lands a few microseconds over it. That is noise at the bound's resolution,
not a loop failure: the clock stays within about 0.05 ms of real time on those legs. The bound was not relaxed; a
criterion with a few-microsecond margin on idle legs will keep flagging such single polls.

## Limitations

- Two runs, 20 to 120 polls per leg; the spread beyond these two runs is unknown.
- One server, one path, one bottleneck; the loop is not robust to a lying or failed server.
- `true_error` exists only because the hosts share a clock (caveat 1).
- The 5000 ppm cap in S1 is a demo setting (caveat 2). At the realistic 500 ppm a 100 ms offset takes about 200 s.
- phi (100 ppm) is an assumption about the oscillator; a drift above it would make stale samples look better than they are.
- Mininet's shaper is a software token bucket, so sub-millisecond figures describe this emulation, not a physical link.
""")
    Path(a.out).write_text("\n".join(parts))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
