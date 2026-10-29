#!/usr/bin/env python3
"""
Evaluation - Robustness & Performance
Topic 23: Network Time Synchronization System

This is the evaluation layer. It does NOT replace Track A's time server or
Track B's SDN controller. It evaluates the existing system by generating
repeatable synchronization measurements and writing CSV results.

Run this file on a Mininet host (normally h2/h3).

Protocol used by Track A:
Request:  REQ|sequence|T1
Reply:    REP|sequence|T1|T2|T3

Metrics:
RTT = (T4 - T1) - (T3 - T2)
Offset = ((T2 - T1) + (T3 - T4)) / 2

T1 is the user-space clock before sending. T4 is the kernel receive timestamp
(SO_TIMESTAMPNS) of the reply plus the simulated skew; if the kernel gives no
stamp the user-space time is used and the fallback is counted and printed.

A reply that does not match the current request (a late reply to an earlier,
timed-out request) is counted as stale and ignored; the evaluator keeps reading
until the matching reply arrives or the per-sample deadline (--timeout) passes.

The --skew-ms argument simulates client clock skew without changing the OS
clock. Expected correction is approximately -skew-ms.
"""

import argparse
import csv
import socket
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server_client"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import clockfilter  # noqa: E402
import ktime  # noqa: E402


def clock_ns(skew_ms: float) -> int:
    return time.time_ns() + int(skew_ms * 1_000_000)


def ms(ns: float) -> float:
    return ns / 1_000_000.0


def _parse_reply(data):
    p = data.decode().strip().split("|")
    if len(p) != 5 or p[0] != "REP":
        raise ValueError("malformed server response")
    return tuple(map(int, p[1:]))


def one_sample(sock, stamper, server, seq, skew_ms, timeout):
    """One request/reply exchange. Returns (status, rtt_ms, offset_ms, error_ms, t4_src, stale)."""
    t1 = clock_ns(skew_ms)
    deadline = time.monotonic() + timeout
    stale = 0
    try:
        sock.sendto(f"REQ|{seq}|{t1}".encode(), server)
    except OSError as exc:
        return f"ERROR:{type(exc).__name__}", None, None, None, "", 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "ERROR:timeout", None, None, None, "", stale
        sock.settimeout(remaining)
        try:
            data, _addr, rx_ns, src = stamper.recv(2048)
        except socket.timeout:
            return "ERROR:timeout", None, None, None, "", stale
        try:
            rseq, t1_echo, t2, t3 = _parse_reply(data)
        except (ValueError, UnicodeDecodeError):
            stale += 1
            continue
        if rseq != seq or t1_echo != t1:
            stale += 1          # a late reply to an earlier request: keep waiting
            continue
        t4 = rx_ns + int(skew_ms * 1_000_000)
        rtt = (t4 - t1) - (t3 - t2)
        offset = ((t2 - t1) + (t3 - t4)) / 2
        return "OK", ms(rtt), ms(offset), abs(ms(offset) + skew_ms), src, stale


def collect(server, samples, interval, timeout, skew_ms, test="baseline", use_kernel=True):
    """Run the exchange `samples` times. Returns (rows, stamper)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stamper = ktime.Stamper(sock, use_kernel=use_kernel)
    rows = []
    try:
        for seq in range(1, samples + 1):
            status, rtt_ms, offset_ms, error_ms, src, stale = one_sample(
                sock, stamper, server, seq, skew_ms, timeout)
            rows.append({
                "test": test,
                "seq": seq,
                "status": status,
                "rtt_ms": "" if rtt_ms is None else f"{rtt_ms:.6f}",
                "offset_ms": "" if offset_ms is None else f"{offset_ms:.6f}",
                "abs_error_ms": "" if error_ms is None else f"{error_ms:.6f}",
                "skew_ms": skew_ms,
                "t4_src": src,
                "stale": stale,
                "timestamp": time.time(),
            })
            if interval > 0:
                time.sleep(interval)
    finally:
        sock.close()
    return rows, stamper


def run(args):
    out = Path(args.csv)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows, stamper = collect((args.server, args.port), args.samples, args.interval,
                            args.timeout, args.skew_ms, args.test, not args.no_kernel_ts)

    with out.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if out.stat().st_size == 0:
            writer.writeheader()
        writer.writerows(rows)

    ok = [r for r in rows if r["status"] == "OK"]
    rtts = [float(r["rtt_ms"]) for r in ok]
    offsets = [float(r["offset_ms"]) for r in ok]
    errors = [float(r["abs_error_ms"]) for r in ok]

    print("\n=== ROBUSTNESS EVALUATION ===")
    print(f"Test              : {args.test}")
    print(f"Server            : {args.server}:{args.port}")
    print(f"Samples requested : {args.samples}")
    print(f"Successful        : {len(ok)}")
    print(f"Timeout/errors    : {len(rows)-len(ok)}")
    print(f"Stale replies     : {sum(int(r['stale']) for r in rows)} (ignored, kept reading)")
    print(f"T4 source         : {stamper.summary()}")
    if stamper.fallbacks:
        print(f"WARNING           : {stamper.fallbacks} sample(s) used user-space time for T4")
    if ok:
        print(f"Average RTT (ms)  : {statistics.mean(rtts):.3f}")
        print(f"Average offset(ms): {statistics.mean(offsets):.3f}")
        print(f"Mean abs error(ms): {statistics.mean(errors):.3f}")
        print(f"Min/Max RTT (ms)  : {min(rtts):.3f} / {max(rtts):.3f}")
        cmp = clockfilter.compare(list(zip(rtts, offsets)), -args.skew_ms)
        if cmp:
            print(f"Min-RTT filter({cmp['window']}): mean error {cmp['raw_mean_ms']:.3f} ms -> "
                  f"filtered {cmp['filtered_mean_ms']:.3f} ms ({cmp['reduction_pct']:+.0f}% , "
                  f"{cmp['n_filtered']} windows)")
    else:
        print("No successful synchronization samples.")
    print(f"CSV results       : {out}")
    print("====================================\n")


def main():
    p = argparse.ArgumentParser(description="Robustness evaluator")
    p.add_argument("--test", required=True,
                   choices=["baseline", "delay", "load", "load_delay", "recovery"])
    p.add_argument("--server", required=True)
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--samples", type=int, default=20)
    p.add_argument("--interval", type=float, default=0.2)
    p.add_argument("--timeout", type=float, default=2.0,
                   help="per-sample deadline: stale replies are ignored until it passes")
    p.add_argument("--skew-ms", type=float, default=100.0)
    p.add_argument("--no-kernel-ts", action="store_true",
                   help="take T4 from user-space time (comparison only)")
    p.add_argument("--csv", default="results/evaluation_results.csv")
    args = p.parse_args()
    run(args)


if __name__ == "__main__":
    main()
