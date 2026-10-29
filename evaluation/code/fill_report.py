#!/usr/bin/env python3
"""
Fill the generated tables in docs/D2_REPORT.md from the real result files.

    fill_report.py [results_dir] [--report docs/D2_REPORT.md]

Replaces the text between `<!-- GEN:name -->` and `<!-- /GEN:name -->` markers. A row
whose result file does not exist is written as `pending` -- numbers are never invented.
Blocks: performance, qos, errors, verdicts, environment.
"""
import argparse
import csv
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import clockfilter  # noqa: E402

DEFAULT = ROOT / "evaluation" / "results" / "actual_sdn_results"
PENDING = "pending"

# (label, csv stem, condition, client)
TESTS = [
    ("P1", "P1_baseline", "Normal", "h2"),
    ("P1b", "P1b_baseline_h3", "Normal, second client", "h3"),
    ("P2", "P2_delay", "50 ms delay (25 ms on h1 and h2)", "h2"),
    ("P3a", "P3a_load_under", "Load 10 Mbit (under capacity)", "h2"),
    ("P3b", "P3b_load_over_qosoff", "Load 30 Mbit offered, QoS off", "h2"),
    ("P3b", "P3b_load_over_qoson", "Load 30 Mbit offered, QoS on", "h2"),
    ("P3b-h3", "P3b_load_over_qosoff_h3", "Same run, second client, QoS off", "h3"),
    ("P3b-h3", "P3b_load_over_qoson_h3", "Same run, second client, QoS on", "h3"),
    ("P4", "P4_load_delay_qosoff", "Load + 50 ms delay, QoS off", "h2"),
    ("P4", "P4_load_delay_qoson", "Load + 50 ms delay, QoS on", "h2"),
    ("P5", "P5_recovery_down", "Server down", "h2"),
    ("P6", "P6_recovery_up", "Server restarted", "h2"),
]


def stats(path):
    if not path.exists():
        return None
    rows = list(csv.DictReader(open(path)))
    ok = [r for r in rows if r["status"] == "OK"]
    d = dict(total=len(rows), ok=len(ok), skew=float(rows[0]["skew_ms"]) if rows else 0.0)
    if ok:
        rtt = [float(r["rtt_ms"]) for r in ok]
        d.update(rtt=statistics.mean(rtt), rtt_max=max(rtt),
                 off=statistics.mean(float(r["offset_ms"]) for r in ok),
                 err=statistics.mean(float(r["abs_error_ms"]) for r in ok),
                 samples=[(float(r["rtt_ms"]), float(r["offset_ms"])) for r in ok])
    return d


def performance(d):
    out = ["| Test | Condition | Client | Skew | Samples OK | Avg RTT (ms) | Max RTT (ms) | Avg offset (ms) | Mean abs error (ms) | Timeouts |",
           "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for label, stem, cond, client in TESTS:
        s = stats(d / f"{stem}.csv")
        if s is None:
            out.append(f"| {label} | {cond} | {client} | | {PENDING} | | | | | |")
        elif not s["ok"]:
            out.append(f"| {label} | {cond} | {client} | {s['skew']:+.0f} ms | 0/{s['total']} | - | - | - | - | {s['total']} |")
        else:
            out.append(f"| {label} | {cond} | {client} | {s['skew']:+.0f} ms | {s['ok']}/{s['total']} | {s['rtt']:.2f} | "
                       f"{s['rtt_max']:.2f} | {s['off']:+.2f} | {s['err']:.3f} | {s['total'] - s['ok']} |")
    return "\n".join(out)


def qos(d):
    out = ["| Scenario | Unloaded reference (ms) | Sync RTT, QoS off (ms) | Sync RTT, QoS on (ms) | Change (ms) | Offset error off -> on (ms) |",
           "|---|---:|---:|---:|---:|---:|"]
    for name, stem, ref in (("Load over capacity (P3b)", "P3b_load_over", "P1_baseline"),
                            ("Load + delay (P4)", "P4_load_delay", "P2_delay")):
        off, on, r = (stats(d / f"{stem}_qosoff.csv"), stats(d / f"{stem}_qoson.csv"), stats(d / f"{ref}.csv"))
        if not (off and on and off["ok"] and on["ok"] and r and r["ok"]):
            out.append(f"| {name} | {PENDING} | | | | |")
            continue
        out.append(f"| {name} | {r['rtt']:.2f} | {off['rtt']:.2f} | {on['rtt']:.2f} | {on['rtt'] - off['rtt']:+.2f} | "
                   f"{off['err']:.3f} -> {on['err']:.3f} |")
    return "\n".join(out)


def errors(d):
    out = ["| Test | OK samples | Mean RTT (ms) | Raw mean error (ms) | Min-RTT filtered error (ms) | Reduction |",
           "|---|---:|---:|---:|---:|---:|"]
    n = 0
    for _l, stem, _c, _cl in TESTS:
        s = stats(d / f"{stem}.csv")
        if not s or not s["ok"]:
            continue
        c = clockfilter.compare(s["samples"], -s["skew"])
        if c:
            n += 1
            out.append(f"| {stem} | {s['ok']} | {s['rtt']:.2f} | {c['raw_mean_ms']:.3f} | {c['filtered_mean_ms']:.3f} | {c['reduction_pct']:+.0f}% |")
    if not n:
        out.append(f"| {PENDING} | | | | | |")
    return "\n".join(out)


def verdicts(d):
    p = d / "SUMMARY.txt"
    if not p.exists():
        return PENDING
    lines = [l for l in p.read_text().splitlines()
             if re.match(r"(QOS_verdict|QOS_setup|P[0-9a-z_]+)\s", l) and not l[0].isspace()]
    return "```text\n" + "\n".join(l[:200] for l in lines) + "\n```"


def environment(d):
    p = d / "environment.txt"
    return ("```text\n" + p.read_text().strip() + "\n```") if p.exists() else PENDING


BLOCKS = dict(performance=performance, qos=qos, errors=errors, verdicts=verdicts, environment=environment)


def fill(text, d):
    for name, fn in BLOCKS.items():
        pat = re.compile(rf"(<!-- GEN:{name} -->\n).*?(\n<!-- /GEN:{name} -->)", re.S)
        if not pat.search(text):
            continue
        text = pat.sub(lambda m: m.group(1) + fn(d) + m.group(2), text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", nargs="?", default=str(DEFAULT))
    ap.add_argument("--report", default=str(ROOT / "docs" / "D2_REPORT.md"))
    a = ap.parse_args()
    p = Path(a.report)
    p.write_text(fill(p.read_text(), Path(a.results_dir)))
    print(f"filled {p} from {a.results_dir}")


if __name__ == "__main__":
    main()
