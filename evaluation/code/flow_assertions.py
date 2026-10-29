#!/usr/bin/env python3
"""
Assertions over the evidence the runner captures while a load is running.

  check_flows(dump_flows_text, qos_on)
      priority=200 UDP/5000 sync flows must be present under load. set_queue:1
      must be on those flows when QoS is on, and nowhere when QoS is off.
  check_tc_classes(tc_class_text, qos_on)
      With QoS on, `tc -s class show dev s1-eth1` must show the sync class
      (OVS queue 1 = htb class 1:2) with its own packets, apart from the default
      class (queue 0 = 1:1) that carries the load. With QoS off there must be
      no such sync class.

Each check returns a list of (name, ok, detail). A CLI is provided:
    flow_assertions.py --flows flows.txt --tc classes.txt --qos on|off
"""
import argparse
import re
import sys

SYNC_CLASS = "1:2"      # OVS linux-htb: queue N is htb class 1:(N+1)
DEFAULT_CLASS = "1:1"
SYNC_MATCH = r"(tp|udp)_(dst|src)=5000\b"


def _flow_lines(text):
    return [l.strip() for l in text.splitlines() if "priority=" in l]


def check_flows(text, qos_on):
    lines = _flow_lines(text)
    sync200 = [l for l in lines if re.search(r"priority=200\b", l) and re.search(SYNC_MATCH, l)]
    res = [("flows: priority=200 UDP/5000 sync flow present under load", bool(sync200),
            f"{len(sync200)} flow(s)")]
    any_queue = [l for l in lines if "set_queue" in l]
    if qos_on:
        queued = [l for l in sync200 if "set_queue:1" in l]
        res.append(("flows: set_queue:1 on a priority=200 sync flow (QoS on)", bool(queued),
                    f"{len(queued)} flow(s)"))
        wrong = [l for l in any_queue if "set_queue:1" in l and not re.search(SYNC_MATCH, l)]
        res.append(("flows: set_queue:1 only on sync (UDP/5000) flows", not wrong, f"{len(wrong)} other"))
    else:
        res.append(("flows: no set_queue anywhere (QoS off)", not any_queue, f"{len(any_queue)} flow(s)"))
    return res


def check_no_escalation(text):
    """Control (load under capacity): no priority=200 sync flow, sync stays at priority 100."""
    lines = _flow_lines(text)
    p200 = [l for l in lines if re.search(r"priority=200\b", l)]
    p100 = [l for l in lines if re.search(r"priority=100\b", l) and re.search(SYNC_MATCH, l)]
    return [("flows: no priority=200 flow under under-capacity load", not p200, f"{len(p200)} flow(s)"),
            ("flows: sync flows stay at priority=100", bool(p100), f"{len(p100)} flow(s)")]


def check_reverted(text):
    """After the load stops the controller must take the sync flows back to priority 100."""
    lines = _flow_lines(text)
    p200 = [l for l in lines if re.search(r"priority=200\b", l)]
    p100 = [l for l in lines if re.search(r"priority=100\b", l) and re.search(SYNC_MATCH, l)]
    return [("flows: priority=200 reverted after the load cleared", not p200, f"{len(p200)} flow(s) left"),
            ("flows: sync flows back at priority=100 after the load cleared", bool(p100), f"{len(p100)} flow(s)")]


def parse_classes(text):
    """{'1:2': {'prio': 0, 'rate': '2Mbit', 'pkts': 12, 'bytes': 1800}, ...}"""
    classes = {}
    for b in re.split(r"(?m)^(?=class )", text):
        m = re.match(r"class htb (\d+:[0-9a-f]+)", b)
        if not m:
            continue
        prio = re.search(r"\bprio (\d+)", b)
        rate = re.search(r"\brate (\S+)", b)
        sent = re.search(r"Sent (\d+) bytes (\d+) pkt", b)
        classes[m.group(1)] = dict(prio=int(prio.group(1)) if prio else None,
                                   rate=rate.group(1) if rate else None,
                                   bytes=int(sent.group(1)) if sent else 0,
                                   pkts=int(sent.group(2)) if sent else 0)
    return classes


def check_tc_classes(text, qos_on):
    cls = parse_classes(text)
    if not qos_on:
        return [("tc: no OVS sync queue class (QoS off)", SYNC_CLASS not in cls, f"classes={sorted(cls)}")]
    sync, default = cls.get(SYNC_CLASS), cls.get(DEFAULT_CLASS)
    res = [("tc: sync class %s and default class %s exist" % (SYNC_CLASS, DEFAULT_CLASS),
            bool(sync and default), f"classes={sorted(cls)}")]
    if sync and default:
        res.append(("tc: sync packets are counted in their own class", sync["pkts"] > 0,
                    f"{SYNC_CLASS}: {sync['pkts']} pkts, rate {sync['rate']}, prio {sync['prio']}"))
        res.append(("tc: load packets stay in the default class", default["pkts"] > sync["pkts"],
                    f"{DEFAULT_CLASS}: {default['pkts']} pkts vs sync {sync['pkts']}"))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flows", required=True)
    ap.add_argument("--tc", required=True)
    ap.add_argument("--qos", choices=["on", "off"], required=True)
    a = ap.parse_args()
    on = a.qos == "on"
    res = check_flows(open(a.flows).read(), on) + check_tc_classes(open(a.tc).read(), on)
    for name, ok, detail in res:
        print(f"{'PASS' if ok else 'FAIL'}  {name}  [{detail}]")
    sys.exit(0 if all(ok for _, ok, _ in res) else 1)


if __name__ == "__main__":
    main()
