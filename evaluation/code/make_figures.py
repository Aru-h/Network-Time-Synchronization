#!/usr/bin/env python3
"""
Summary charts computed directly from the result CSVs (nothing typed by hand).

    make_figures.py [results_dir] [-o out_dir]

Writes 01_summary_avg_rtt.png and 02_summary_offset_error.png: one bar per test,
OK samples only. These are plots of the committed measurements, not terminal captures.
"""
import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "evaluation" / "results" / "actual_sdn_results"

# (file stem, label, colour group)
TESTS = [
    ("P1_baseline", "P1\nbaseline", "plain"),
    ("P2_delay", "P2\n50 ms delay", "plain"),
    ("P3a_load_under", "P3a\n10M load\n(under)", "plain"),
    ("P3b_load_over_qosoff", "P3b\noverload\nQoS off", "off"),
    ("P3b_load_over_qoson", "P3b\noverload\nQoS on", "on"),
    ("P4_load_delay_qosoff", "P4\nload+delay\nQoS off", "off"),
    ("P4_load_delay_qoson", "P4\nload+delay\nQoS on", "on"),
    ("P6_recovery_up", "P6\nserver\nrestarted", "plain"),
]
COLOURS = {"plain": "#6b7280", "off": "#e8622c", "on": "#2f6fcb"}


def means(path):
    rtt, err = [], []
    for r in csv.DictReader(open(path)):
        if r.get("status") == "OK":
            rtt.append(float(r["rtt_ms"]))
            err.append(float(r["abs_error_ms"]))
    return (sum(rtt) / len(rtt), sum(err) / len(err), len(rtt)) if rtt else None


def bars(data, idx, ylabel, title, out):
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=150)
    xs, vals, cols, labels = [], [], [], []
    for i, (stem, label, grp) in enumerate(TESTS):
        m = data.get(stem)
        if m is None:
            continue
        xs.append(i); vals.append(m[idx]); cols.append(COLOURS[grp]); labels.append(label)
    pos = list(range(len(xs)))
    ax.bar(pos, vals, color=cols, width=0.62)
    for p, v in zip(pos, vals):
        ax.text(p, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(pos); ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel(ylabel); ax.set_title(title, fontsize=11, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.margins(y=0.15)
    fig.text(0.01, 0.01, "Source: evaluation/results/actual_sdn_results/*.csv, 20 samples per test (OK samples only). "
             "Orange = QoS off, blue = QoS on.", fontsize=7, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out); plt.close(fig)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", default=str(DEFAULT))
    ap.add_argument("-o", "--out", default=str(ROOT / "screenshots"))
    a = ap.parse_args()
    res, out = Path(a.results), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    data = {}
    for stem, _, _ in TESTS:
        p = res / f"{stem}.csv"
        if p.exists():
            m = means(p)
            if m:
                data[stem] = m
    bars(data, 0, "mean sync RTT (ms)", "Sync RTT per test: delay and congestion raise it, QoS removes the congestion part",
         out / "01_summary_avg_rtt.png")
    bars(data, 1, "mean |offset error| (ms)", "Offset error per test: congestion makes the delay asymmetric; QoS restores accuracy",
         out / "02_summary_offset_error.png")


if __name__ == "__main__":
    main()
