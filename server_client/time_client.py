#!/usr/bin/env python3
"""
UDP Time Synchronization Client
Topic 23 - D1

Four timestamps:
T1 = client sends request
T2 = server receives request
T3 = server sends response
T4 = client receives response

Offset estimate:
    offset = ((T2 - T1) + (T3 - T4)) / 2

Round-trip delay:
    delay = (T4 - T1) - (T3 - T2)

--skew-ms simulates a client clock offset without changing the real OS clock.
"""

import argparse
import socket
import time


def real_now_ns():
    return time.time_ns()


def client_clock_ns(skew_ms):
    return time.time_ns() + int(skew_ms * 1_000_000)


def ns_to_ms(value):
    return value / 1_000_000.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", required=True)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--skew-ms", type=float, default=0.0)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)

    server = (args.server, args.port)

    print("=" * 78)
    print("TOPIC 23 - NETWORK TIME SYNCHRONIZATION CLIENT")
    print("=" * 78)
    print(f"Server       : {args.server}:{args.port}")
    print(f"Samples      : {args.samples}")
    print(f"Simulated skew: {args.skew_ms:+.2f} ms")
    print()
    print(
        f"{'SEQ':>4} {'RTT(ms)':>12} {'OFFSET(ms)':>14} "
        f"{'ABS ERROR(ms)':>16}"
    )
    print("-" * 52)

    offsets = []
    rtts = []
    errors = []

    for seq in range(1, args.samples + 1):
        t1 = client_clock_ns(args.skew_ms)
        request = f"REQ|{seq}|{t1}".encode()

        try:
            sock.sendto(request, server)
            data, _ = sock.recvfrom(2048)
            t4 = client_clock_ns(args.skew_ms)

            parts = data.decode().strip().split("|")
            if len(parts) != 5 or parts[0] != "REP":
                raise ValueError("invalid server response")

            rseq = int(parts[1])
            t1_echo = int(parts[2])
            t2 = int(parts[3])
            t3 = int(parts[4])

            if rseq != seq or t1_echo != t1:
                raise ValueError("sequence/timestamp mismatch")

            rtt_ns = (t4 - t1) - (t3 - t2)
            offset_ns = ((t2 - t1) + (t3 - t4)) / 2

            # Since we intentionally simulated a local clock skew, the
            # expected correction is approximately -skew.
            expected_offset_ns = -args.skew_ms * 1_000_000
            error_ms = abs(ns_to_ms(offset_ns - expected_offset_ns))

            rtt_ms = ns_to_ms(rtt_ns)
            offset_ms = ns_to_ms(offset_ns)

            offsets.append(offset_ms)
            rtts.append(rtt_ms)
            errors.append(error_ms)

            print(
                f"{seq:4d} {rtt_ms:12.3f} {offset_ms:14.3f} "
                f"{error_ms:16.3f}"
            )

        except (socket.timeout, ValueError, UnicodeDecodeError) as exc:
            print(f"{seq:4d} {'TIMEOUT/ERROR':>12} {'-':>14} {'-':>16}  ({exc})")

        time.sleep(args.interval)

    if offsets:
        print()
        print("-" * 52)
        print(f"Successful samples : {len(offsets)}")
        print(f"Average RTT        : {sum(rtts)/len(rtts):.3f} ms")
        print(f"Average offset     : {sum(offsets)/len(offsets):.3f} ms")
        print(f"Mean absolute error: {sum(errors)/len(errors):.3f} ms")
        print()
        print("Interpretation:")
        print(
            "The estimated offset should be close to the negative of the "
            "simulated client skew."
        )
    else:
        print("\nNo successful synchronization samples.")


if __name__ == "__main__":
    main()
