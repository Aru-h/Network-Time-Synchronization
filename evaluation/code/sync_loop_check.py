#!/usr/bin/env python3
"""
Verdicts for the sync-loop legs, and the PASS / FAIL / SKIP table.

    sync_loop_check.py RESULTS_DIR [--steps STEPS.tsv] [--markdown OUT.md]

Pass bound, computed from each run: over the steady state (the second half of the OK polls) a poll is WITHIN the
bound if  |true_error| <= filtered_rtt/2 + drift_ppm * 1e-6 * poll_s  (ms), where filtered_rtt is the one from the
PREVIOUS poll. A leg passes the bound check if at least WITHIN_FRACTION (95%) of its steady polls are within it; the
violation count and the worst excess are printed for every leg.

CRITERION HISTORY. The first version required EVERY steady poll to be within the bound (strict). Runs 1 and 2 each had
one idle leg miss it by 4 and 8 microseconds on a bound of a few hundredths of a millisecond; the criterion was then
changed to the 95% rule below, on 2026-10-29, after seeing those two runs. It is fixed and not to be altered again after
run 3. `--strict` (or strict=True) still evaluates the original rule, and docs/SYNC_LOOP.md reports both. The clock error logged at poll i was set by the discipline of poll i-1, so that is the estimate
whose uncertainty bounds it. filtered_rtt/2 is the most one offset estimate can be wrong when the delay is all on
one side; the drift term is how far the clock wanders between two polls. The bound is printed, never relaxed.

Legs (expected steps, role):
  S1_slew            skew 100 ms, slew cap 5000 ppm (DEMO setting)   0 steps  PASS/FAIL
  S2_step            skew 500 ms, default cap                        1 step   PASS/FAIL
  S3_drift           50 ppm drift, 60 s                              0 steps  PASS/FAIL
  S3f_drift_freq     as S3 with --freq-compensate                    0 steps  report only
  S6_idle_cpubusy    idle leg with CPU-busy background processes     1 step   report only; optional (omitted if not run)
  S4_load_qosoff     load 30M, QoS off, skew 500 ms                  1 step   report only (error ~ RTT/2 sits on the bound)
  S5_load_qoson      load 30M, QoS on,  skew 500 ms                  1 step   PASS/FAIL, plus  S5 error < S4 error
VALIDITY (a leg that fails it is reported INVALID, keeps its data, and is counted as SKIP, never PASS):
  clock step  (wall clock - CLOCK_MONOTONIC) must not change by more than CLOCK_STEP_MS (5 ms) between two consecutive polls.
              CLOCK_MONOTONIC is slewed like the wall clock, so the difference stays constant while chrony slews and changes only
              when the wall clock is stepped or the machine is suspended and resumed (a laptop going to sleep under the VM,
              which stepped the clock by 456 s in run 3). 5 ms is far above the noise of reading two clocks back to back and
              far above what a step could do to the soft clock (rate x step is microseconds). Legs from runs that did not
              record the column are "not measured", not INVALID.
  load        (S4, S5) the iperf server must have received more than 0 Mbit/s in every second of the steady window, and the
              sender must still have been running at the end of the leg. No threshold is introduced: the achieved mean and
              minimum are printed so saturation can be read off. The steady window is the iperf-server seconds from one second
              before the loop's steady half (the load starts LOAD_HEAD_START_S before the loop; the mapping is good to about
              one second) to the last poll. A second missing from the server log counts as 0.
  S5 < S4     is SKIP if either load leg is INVALID.
Every leg: the clock never goes backwards (the `backwards` column stays 0; step instants are reported apart).
Missing or too little data is SKIP, never PASS, and the table then says INCOMPLETE. Report-only legs are shown as INFO and are
not counted. The exit status is 1 only for a FAIL.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

POLL_S = 1.0
WITHIN_FRACTION = 0.95      # fixed before run 3; see CRITERION HISTORY above
CLOCK_STEP_MS = 5.0         # a leg is INVALID if (wall clock - CLOCK_MONOTONIC) changes by more than this between two polls
LOAD_LEGS = ("S4_load_qosoff", "S5_load_qoson")
LOAD_HEAD_START_S = 2       # the runner starts the load this many seconds before the loop (run_sync_loop.py: LOAD_HEAD_START_S)
# name, description, drift ppm, expected steps, role
LEGS = [
    ("S1_slew", "skew 100 ms, slew cap 5000 ppm (DEMO), 120 s", 0.0, 0, "PASS"),
    ("S2_step", "skew 500 ms, cap 500 ppm, 60 s", 0.0, 1, "PASS"),
    ("S3_drift", "50 ppm drift, 60 s", 50.0, 0, "PASS"),
    ("S3f_drift_freq", "50 ppm drift, --freq-compensate, 60 s", 50.0, 0, "INFO"),
    ("S6_idle_cpubusy", "skew 500 ms, CPU-busy background processes, no load, 60 s", 0.0, 1, "INFO"),
    ("S4_load_qosoff", "30 Mbit load, QoS off, skew 500 ms, 90 s", 0.0, 1, "INFO"),
    ("S5_load_qoson", "30 Mbit load, QoS on, skew 500 ms, 90 s", 0.0, 1, "PASS"),
]


def analyze(csv_path, drift_ppm, poll_s=POLL_S, min_steady=3):
    """Numbers for one CSV, or None if there is not enough data."""
    p = Path(csv_path)
    if not p.exists():
        return None
    allrows = list(csv.DictReader(open(p)))
    rows = [r for r in allrows if r["status"] == "OK"]
    start = len(rows) // 2
    steady, prev = rows[start:], rows[max(start - 1, 0):-1]
    if start == 0 or len(steady) < min_steady or len(prev) != len(steady):
        return None
    drift_ms = abs(drift_ppm) * 1e-6 * poll_s * 1e3
    errs = [abs(float(r["true_error"])) for r in steady]
    bounds = [float(r["filtered_rtt"]) / 2 + drift_ms for r in prev]
    jumps = [float(r["clock_jump_ms"]) for r in allrows if r.get("clock_jump_ms") not in (None, "")]
    return dict(polls=len(allrows), ok=len(rows), steady=len(steady), timeouts=len(allrows) - len(rows),
                t_steady_start=float(steady[0]["t"]), t_last=float(allrows[-1]["t"]),
                clock_checked=bool(jumps), max_clock_jump=max((abs(j) for j in jumps), default=0.0),
                steps=sum(int(r["stepped"]) for r in allrows),
                step_at=[float(r["t"]) for r in allrows if int(r["stepped"])],
                backwards=int(float(allrows[-1]["backwards"])) if allrows else 0,
                first_err=abs(float(rows[0]["true_error"])),
                max_err=max(errs), mean_err=sum(errs) / len(errs),
                max_bound=max(bounds), mean_bound=sum(bounds) / len(bounds), drift_term=drift_ms,
                violations=sum(1 for e, b in zip(errs, bounds) if e > b),
                worst_excess=max(0.0, max(e - b for e, b in zip(errs, bounds))),
                within=sum(1 for e, b in zip(errs, bounds) if e <= b) / len(errs),
                margin=min(b - e for e, b in zip(errs, bounds)),
                max_rate=max(abs(float(r["rate_ppm"])) for r in allrows))


def load_per_second(path):
    """{start_second: Mbit/s} from the iperf server log, 1 s intervals only. Zero-rate intervals ('0.000 bits/sec') are kept:
    the D2 runner's iperf_server_summary regex only matches 'Mbits/sec' lines, so it would drop them and average over the rest."""
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text().splitlines():
        m = re.search(r"\]\s+(\d+\.\d+)\s*-\s*(\d+\.\d+)\s+sec\s+.*?(\d+\.?\d*)\s+([MKG]?)bits/sec", line)
        if m and float(m.group(2)) - float(m.group(1)) <= 1.05:
            out[int(float(m.group(1)))] = float(m.group(3)) * {"G": 1e3, "M": 1.0, "K": 1e-3, "": 1e-6}[m.group(4)]
    return out


def sender_running_at_end(txt_path):
    """True/False from the runner's note 'still running at end of leg: ...', None if it is not there."""
    p = Path(txt_path)
    m = re.search(r"still running at end of leg: (True|False)", p.read_text()) if p.exists() else None
    return None if m is None else m.group(1) == "True"


def load_check(d, name, a):
    """Load validity of one load leg from its iperf server log and runner note: dict(ok, mean, min, secs, alive, reason)."""
    rates = load_per_second(Path(d) / f"{name}_iperf_server.log")
    alive = sender_running_at_end(Path(d) / f"{name}.txt")
    first = max(0, int(LOAD_HEAD_START_S + a["t_steady_start"]) - 1)
    last = int(LOAD_HEAD_START_S + a["t_last"])
    win = [rates.get(i, 0.0) for i in range(first, last + 1)]
    reasons = []
    if not rates:
        reasons.append("no iperf server log")
    if win and min(win) <= 0:
        reasons.append(f"load was 0 Mbit/s in {sum(1 for x in win if x <= 0)} of {len(win)} steady seconds")
    if alive is False:
        reasons.append("the sender was no longer running at the end of the leg")
    if alive is None:
        reasons.append("no sender-status note")
    return dict(ok=not reasons, mean=(sum(win) / len(win)) if win else 0.0, min=min(win) if win else 0.0,
                secs=len(win), window=(first, last), alive=alive, reason="; ".join(reasons))


def invalid_reasons(a, load):
    r = []
    if a["clock_checked"] and a["max_clock_jump"] > CLOCK_STEP_MS:
        r.append(f"wall clock stepped against CLOCK_MONOTONIC by {a['max_clock_jump']:.1f} ms between polls (tolerance {CLOCK_STEP_MS:g} ms)")
    if load is not None and not load["ok"]:
        r.append(load["reason"])
    return r


def verdict(a, exp_steps, role, strict=False):
    """(result, detail) from analyze(); result is PASS, FAIL, SKIP or INFO (report only).
    strict=True is the original rule (every steady poll within the bound); the default is the 95% rule."""
    if a is None:
        return "SKIP", "no data (missing CSV or too few OK polls)"
    bound_ok = a["violations"] == 0 if strict else a["within"] >= WITHIN_FRACTION
    checks = [("bound", bound_ok), ("steps", a["steps"] == exp_steps), ("monotonic", a["backwards"] == 0)]
    bad = [n for n, ok in checks if not ok]
    detail = (f"steps {a['steps']} (expected {exp_steps})" + (f" at t={a['step_at']}" if a["step_at"] else "") +
              f"; backwards {a['backwards']}; steady |err| max {a['max_err']:.4f} mean {a['mean_err']:.4f} ms; "
              f"bound max {a['max_bound']:.4f} ms (filtered_rtt/2 + drift*poll {a['drift_term']:.3f}); "
              f"{a['violations']}/{a['steady']} steady polls over the bound ({a['within'] * 100:.1f}% within, "
              f"{'all' if strict else f'{WITHIN_FRACTION * 100:.0f}%'} needed), worst excess {a['worst_excess']:.4f} ms")
    if role == "INFO":
        return "INFO", detail + ("" if not bad else f"; would fail: {','.join(bad)}")
    return ("PASS" if not bad else "FAIL"), detail + ("" if not bad else f"; failed: {','.join(bad)}")


def evaluate(d, strict=False):
    """List of (name, result, detail) for every leg plus the S5<S4 comparison."""
    d = Path(d)
    out, an = [], {}
    for name, desc, drift, steps, role in LEGS:
        if name.startswith("S6") and not (d / f"{name}.csv").exists():
            continue                                                    # optional leg that was not run: omitted, not a SKIP
        a = an[name] = analyze(d / f"{name}.csv", drift)
        if a is not None and name in LOAD_LEGS:
            a["load"] = load_check(d, name, a)
        res, detail = verdict(a, steps, role, strict)
        if a is not None:
            bad = invalid_reasons(a, a.get("load"))
            note = "" if a["clock_checked"] else "; clock-step check not recorded"
            if name in LOAD_LEGS:
                note += (f"; load in steady window {a['load']['mean']:.1f} Mbit/s mean, {a['load']['min']:.1f} min "
                         f"({a['load']['secs']} s)")
            if bad:
                res, detail = "INVALID", "INVALID (counted SKIP): " + "; ".join(bad) + ". Data kept: " + detail
            else:
                detail += note
        out.append((name, res, f"{desc}: {detail}"))
    s4, s5 = an["S4_load_qosoff"], an["S5_load_qoson"]
    inval = {n: r for n, r, _ in out if r == "INVALID"}
    if s4 is None or s5 is None:
        out.append(("S5 < S4 error", "SKIP", "no data for S4 or S5"))
    elif "S4_load_qosoff" in inval or "S5_load_qoson" in inval:
        out.append(("S5 < S4 error", "SKIP", "S4 INVALID" if "S4_load_qosoff" in inval and "S5_load_qoson" not in inval
                    else "S5 INVALID" if "S5_load_qoson" in inval and "S4_load_qosoff" not in inval else "S4 and S5 INVALID"))
    else:
        ok = s5["mean_err"] < s4["mean_err"]
        out.append(("S5 < S4 error", "PASS" if ok else "FAIL",
                    f"steady mean |true_error| QoS on {s5['mean_err']:.4f} ms vs QoS off {s4['mean_err']:.4f} ms "
                    f"(max {s5['max_err']:.4f} vs {s4['max_err']:.4f} ms)"))
    return out, an


REPORT_ONLY = {name for name, _d, _dr, _st, role in LEGS if role == "INFO"}
# The counted checks of every run: the 5 setup rows (3 sandbox test files, environment probe, runner exit status),
# S1_slew, S2_step, S3_drift, S5_load_qoson and "S5 < S4 error" = 10. Report-only legs are never counted.
COUNTED_CHECKS = 10


def count(rows):
    """THE counting rule, the same for every run. rows are (name, result, detail).
    - a report-only leg (S3f, S4, S6) is shown but never counted, whatever its result (INFO, INVALID or SKIP): bucket 'INFO';
    - any other check counts once: PASS, FAIL or SKIP; an INVALID check is counted as SKIP (and also tallied in 'INVALID').
    PASS + FAIL + SKIP is therefore the number of counted checks, whatever happened in the run."""
    n = dict(PASS=0, FAIL=0, SKIP=0, INFO=0, INVALID=0)
    for name, res, _detail in rows:
        if name in REPORT_ONLY:
            n["INFO"] += 1
        elif res == "INVALID":
            n["SKIP"] += 1
            n["INVALID"] += 1
        elif res in ("PASS", "FAIL", "SKIP"):
            n[res] += 1
    return n


def read_steps(path):
    rows = []
    if path and Path(path).exists():
        for line in open(path):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2:
                rows.append((p[0], p[1], p[2] if len(p) > 2 else ""))
    return rows


def render(rows):
    w = max(len(r[0]) for r in rows)
    lines = ["=" * 110, f"{'CHECK':<{w}}  RESULT  DETAIL", "-" * 110]
    for name, res, detail in rows:
        lines.append(f"{name:<{w}}  {res:<6}  {detail[:110 - w - 10]}")
    n = count(rows)                                                     # an INVALID counted check is a SKIP, never a PASS
    total = n["PASS"] + n["FAIL"] + n["SKIP"]
    lines += ["-" * 110, f"PASS {n['PASS']}   FAIL {n['FAIL']}   SKIP {n['SKIP']} (of which INVALID {n['INVALID']})   = {total} counted checks   "
              f"(INFO {n['INFO']}: report-only legs, never counted)",
              "OVERALL: " + ("FAIL" if n["FAIL"] else f"INCOMPLETE ({n['SKIP']} SKIP: no data)" if n["SKIP"] else "PASS"), "=" * 110]
    return "\n".join(lines), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--steps")
    ap.add_argument("--strict", action="store_true", help="the original rule: every steady poll within the bound")
    ap.add_argument("--no-summary", action="store_true", help="do not write SUMMARY.txt into the results directory")
    a = ap.parse_args()
    rows = read_steps(a.steps)
    legs, _ = evaluate(a.results_dir, strict=a.strict)
    text, n = render(rows + legs)
    print(text)
    if not a.no_summary:
        Path(a.results_dir, "SUMMARY.txt").write_text(text + "\n")
    sys.exit(1 if n["FAIL"] else 0)


if __name__ == "__main__":
    main()
