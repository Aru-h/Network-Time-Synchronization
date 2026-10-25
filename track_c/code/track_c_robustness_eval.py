#!/usr/bin/env python3
"""
Track C - Robustness & Performance Evaluation
Topic 23: Network Time Synchronization System

This is the Track C layer. It does NOT replace Track A's time server or
Track B's SDN controller. It evaluates the existing system by generating
repeatable synchronization measurements and writing CSV results.

Run this file on a Mininet host (normally h2/h3).

Protocol used by Track A:
Request:  REQ|sequence|T1
Reply:    REP|sequence|T1|T2|T3

Metrics:
RTT = (T4 - T1) - (T3 - T2)
Offset = ((T2 - T1) + (T3 - T4)) / 2

The --skew-ms argument simulates client clock skew without changing the OS
clock. Expected correction is approximately -skew-ms.
"""

import argparse
import csv
import socket
import statistics
import time
from pathlib import Path


def clock_ns(skew_ms: float) -> int:
    return time.time_ns() + int(skew_ms * 1_000_000)


def ms(ns: float) -> float:
    return ns / 1_000_000.0


def run(args):
    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)
    server = (args.server, args.port)

    rows = []
    for seq in range(1, args.samples + 1):
        t1 = clock_ns(args.skew_ms)
        packet = f"REQ|{seq}|{t1}".encode()

        status = "OK"
        rtt_ms = offset_ms = error_ms = None

        try:
            sock.sendto(packet, server)
            data, _ = sock.recvfrom(2048)
            t4 = clock_ns(args.skew_ms)

            p = data.decode().strip().split("|")
            if len(p) != 5 or p[0] != "REP":
                raise ValueError("malformed server response")

            rseq, t1_echo, t2, t3 = map(int, p[1:])
            if rseq != seq or t1_echo != t1:
                raise ValueError("sequence/timestamp mismatch")

            rtt = (t4 - t1) - (t3 - t2)
            offset = ((t2 - t1) + (t3 - t4)) / 2
            expected = -args.skew_ms
            rtt_ms = ms(rtt)
            offset_ms = ms(offset)
            error_ms = abs(offset_ms - expected)

        except Exception as exc:
            status = f"ERROR:{type(exc).__name__}"

        rows.append({
            "test": args.test,
            "seq": seq,
            "status": status,
            "rtt_ms": "" if rtt_ms is None else f"{rtt_ms:.6f}",
            "offset_ms": "" if offset_ms is None else f"{offset_ms:.6f}",
            "abs_error_ms": "" if error_ms is None else f"{error_ms:.6f}",
            "skew_ms": args.skew_ms,
            "timestamp": time.time(),
        })

        if args.interval > 0:
            time.sleep(args.interval)

    with out.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if out.stat().st_size == 0:
            writer.writeheader()
        writer.writerows(rows)

    ok = [r for r in rows if r["status"] == "OK"]
    rtts = [float(r["rtt_ms"]) for r in ok]
    offsets = [float(r["offset_ms"]) for r in ok]
    errors = [float(r["abs_error_ms"]) for r in ok]

    print("\n=== TRACK C ROBUSTNESS EVALUATION ===")
    print(f"Test              : {args.test}")
    print(f"Server            : {args.server}:{args.port}")
    print(f"Samples requested : {args.samples}")
    print(f"Successful        : {len(ok)}")
    print(f"Timeout/errors    : {len(rows)-len(ok)}")
    if ok:
        print(f"Average RTT (ms)  : {statistics.mean(rtts):.3f}")
        print(f"Average offset(ms): {statistics.mean(offsets):.3f}")
        print(f"Mean abs error(ms): {statistics.mean(errors):.3f}")
        print(f"Min/Max RTT (ms)  : {min(rtts):.3f} / {max(rtts):.3f}")
    else:
        print("No successful synchronization samples.")
    print(f"CSV results       : {out}")
    print("====================================\n")


def main():
    p = argparse.ArgumentParser(description="Track C robustness evaluator")
    p.add_argument("--test", required=True,
                   choices=["baseline", "delay", "load", "load_delay", "recovery"])
    p.add_argument("--server", required=True)
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--samples", type=int, default=20)
    p.add_argument("--interval", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--skew-ms", type=float, default=100.0)
    p.add_argument("--csv", default="results/track_c_results.csv")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
