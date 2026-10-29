#!/usr/bin/env python3
"""
Build the offline replay page from a results folder.

    build_replay.py [results_dir] [-o replay.html]

One self-contained HTML file (data inlined, no network, no libraries) showing, for
the over-capacity load test (P3b) and the load+delay test (P4):
  - sync RTT and offset error per sample, QoS off vs QoS on
  - the controller policy timeline (port-1 egress rate, thresholds, priority 100/200)
  - the flow table captured under load, with priorities and set_queue highlighted

Runs from before the QoS work have a single (QoS off) variant; the page says so.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "evaluation" / "results" / "actual_sdn_results"
VARIANT = re.compile(r"^(?P<scenario>.+?)(?:_qos(?P<qos>off|on))?$")
ENTER_MBPS, EXIT_MBPS = 15.0, 8.0     # mirrors controller/d2_adaptive_controller.py


def read_csv(path):
    rows = []
    if not Path(path).exists():
        return rows
    for r in csv.DictReader(open(path)):
        ok = r.get("status") == "OK"
        rows.append(dict(seq=int(r["seq"]), ok=ok, ts=float(r["timestamp"]),
                         rtt=float(r["rtt_ms"]) if ok else None,
                         err=float(r["abs_error_ms"]) if ok else None,
                         offset=float(r["offset_ms"]) if ok else None))
    return rows


def parse_policy(path):
    """[{t, mbps, congested, priority}] plus transition events [{t, state, mbps}]."""
    pts, events = [], []
    if not Path(path).exists():
        return pts, events
    for i, line in enumerate(Path(path).read_text().splitlines()):
        m = re.search(r"POLICY t=([\d.]+) .*state=(\w+) rate_mbps=([\d.]+)", line)
        if m:
            events.append(dict(t=float(m[1]), state=m[2], mbps=float(m[3])))
            continue
        m = re.search(r"DYNAMIC SDN: (?:t=([\d.]+) )?.*?egress ([\d.]+) Mbit/s \((\w+)\).*policy = (\d+)", line)
        if m:
            pts.append(dict(t=float(m[1]) if m[1] else None, mbps=float(m[2]),
                            congested=m[3] == "congested", priority=int(m[4])))
            continue
        m = re.search(r"DYNAMIC SDN: .*traffic (high|normal) \((\d+) bytes/interval\).*policy = (\d+)", line)
        if m:       # run made before the port-1 controller: summed bytes per 2 s poll
            pts.append(dict(t=None, mbps=int(m[2]) * 8 / 2 / 1e6, congested=m[1] == "high",
                            priority=int(m[3])))
    return pts, events


def parse_flows(text):
    flows = []
    for line in text.splitlines():
        m = re.search(r"n_packets=(\d+).*?priority=(\d+)(?:,(.*?))? actions=(.*)$", line)
        if m:
            flows.append(dict(pkts=int(m[1]), priority=int(m[2]), match=m[3] or "(any)",
                              actions=m[4].strip()))
    flows.sort(key=lambda f: -f["priority"])
    return flows


def section(text, title):
    m = re.search(r"### " + re.escape(title) + r"[^\n]*\n(.*?)(?=\n### |\Z)", text, re.S)
    return m.group(1) if m else ""


def load_variant(d, name):
    ev = Path(d) / f"evidence_{name}_during_load.txt"
    text = ev.read_text() if ev.exists() else ""
    pts, events = parse_policy(Path(d) / f"policy_{name}.txt")
    assertions = []
    ap = Path(d) / f"assertions_{name}.txt"
    if ap.exists():
        for line in ap.read_text().splitlines():
            m = re.match(r"(PASS|FAIL)\s+(.*)$", line)
            if m:
                assertions.append(dict(ok=m[1] == "PASS", text=m[2]))
    return dict(name=name, rows=read_csv(Path(d) / f"{name}.csv"), rows_h3=read_csv(Path(d) / f"{name}_h3.csv"),
                policy=pts, events=events, flows=parse_flows(section(text, "ovs-ofctl dump-flows s1")),
                tc=section(text, "tc -s class show dev s1-eth1"), assertions=assertions)


def build(d):
    d = Path(d)
    scenarios = {}
    for csvp in sorted(d.glob("P3b_load_over*.csv")) + sorted(d.glob("P4_load_delay*.csv")):
        if csvp.stem.endswith("_h3"):
            continue
        m = VARIANT.match(csvp.stem)
        key = m["scenario"]
        qos = "on" if m["qos"] == "on" else "off"
        scenarios.setdefault(key, {})[qos] = load_variant(d, csvp.stem)
    base = {}
    for n, f in (("P1", "P1_baseline"), ("P2", "P2_delay")):
        rows = [r for r in read_csv(d / f"{f}.csv") if r["ok"]]
        if rows:
            base[n] = sum(r["rtt"] for r in rows) / len(rows)
    summary = (d / "SUMMARY.txt").read_text() if (d / "SUMMARY.txt").exists() else ""
    env = (d / "environment.txt").read_text() if (d / "environment.txt").exists() else ""
    verdicts = [l for l in summary.splitlines() if l.startswith(("QOS_verdict", "P3b", "P4"))]
    return dict(scenarios=scenarios, baseline=base, verdicts=verdicts, env=env.strip().splitlines(),
                thresholds=dict(enter=ENTER_MBPS, exit=EXIT_MBPS), source=str(d.name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", nargs="?", default=str(DEFAULT))
    ap.add_argument("-o", "--out")
    a = ap.parse_args()
    data = build(a.results_dir)
    if not data["scenarios"]:
        sys.exit(f"no P3b/P4 CSVs in {a.results_dir}")
    out = Path(a.out) if a.out else Path(a.results_dir) / "replay.html"
    tpl = (Path(__file__).with_name("replay_template.html")).read_text()
    out.write_text(tpl.replace("/*__DATA__*/null", json.dumps(data)))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
