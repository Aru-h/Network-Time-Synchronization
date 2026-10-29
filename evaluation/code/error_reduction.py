#!/usr/bin/env python3
"""
Error-reduction table: mean offset error of the raw samples vs the NTP-style
min-RTT filter over 8 samples, per result CSV.

    error_reduction.py [results_dir] [--markdown out.md]

Raw = mean |offset - (-skew)| over all OK samples. Filtered = the same measure over
the sliding 8-sample windows, each window contributing the offset of its minimum-RTT
sample. Tests with fewer than 8 OK samples (P5/P6 recovery, failures) are skipped.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clockfilter  # noqa: E402

DEFAULT = Path(__file__).resolve().parents[1] / "results" / "actual_sdn_results"


def load(path):
    rows = [r for r in csv.DictReader(open(path)) if r.get("status") == "OK"]
    skew = float(rows[0]["skew_ms"]) if rows else 0.0
    return [(float(r["rtt_ms"]), float(r["offset_ms"])) for r in rows], -skew


def table(results_dir):
    lines = ["| Test | OK samples | Mean RTT (ms) | Raw mean error (ms) | Min-RTT filtered error (ms) | Reduction |",
             "|---|---:|---:|---:|---:|---:|"]
    n = 0
    for p in sorted(Path(results_dir).glob("*.csv")):
        samples, expected = load(p)
        c = clockfilter.compare(samples, expected)
        if not c:
            continue
        n += 1
        mean_rtt = sum(r for r, _ in samples) / len(samples)
        lines.append(f"| {p.stem} | {len(samples)} | {mean_rtt:.2f} | {c['raw_mean_ms']:.3f} | "
                     f"{c['filtered_mean_ms']:.3f} | {c['reduction_pct']:+.0f}% |")
    return "\n".join(lines), n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", nargs="?", default=str(DEFAULT))
    ap.add_argument("--markdown")
    a = ap.parse_args()
    text, n = table(a.results_dir)
    print(text)
    if a.markdown:
        Path(a.markdown).write_text(text + "\n")
    sys.exit(0 if n else 1)


if __name__ == "__main__":
    main()
