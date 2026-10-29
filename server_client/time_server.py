#!/usr/bin/env python3
"""
UDP Reference Time Server
Topic 23 - Network Time Synchronization System

Protocol:
Client sends:  REQ|sequence|T1
Server records: T2 = kernel receive timestamp (SO_TIMESTAMPNS); falls back to
                user-space time if the kernel gives none, and counts each fallback
Server records: T3 immediately before reply
Server sends:  REP|sequence|T1|T2|T3

The client records T4 on receiving the response.
"""

import argparse
import signal
import socket
import time

import ktime


def now_ns():
    return time.time_ns()


def serve(sock, stamper, stop=lambda: False, log=print):
    """Answer requests until stop() is true. The socket needs a timeout for stop() to be polled."""
    served = 0
    while not stop():
        try:
            data, addr, t2, src = stamper.recv(2048)
        except socket.timeout:
            continue

        try:
            parts = data.decode().strip().split("|")
            if len(parts) != 3 or parts[0] != "REQ":
                log(f"Ignoring malformed packet from {addr}: {data!r}")
                continue

            seq = int(parts[1])
            t1 = int(parts[2])
        except (ValueError, UnicodeDecodeError):
            log(f"Ignoring invalid packet from {addr}")
            continue

        t3 = now_ns()
        reply = f"REP|{seq}|{t1}|{t2}|{t3}".encode()

        sock.sendto(reply, addr)
        served += 1

        log(
            f"SYNC seq={seq:03d} client={addr[0]}:{addr[1]} "
            f"T2={t2} ({src}) T3={t3} | kernel={stamper.kernel} "
            f"user-space-fallbacks={stamper.fallbacks}"
        )
    return served


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="10.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-kernel-ts", action="store_true",
                        help="take T2 from user-space time (comparison only)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    stamper = ktime.Stamper(sock, use_kernel=not args.no_kernel_ts)
    sock.settimeout(0.5)
    signal.signal(signal.SIGTERM, signal.default_int_handler)   # print the summary on terminate()

    print("=" * 64)
    print("TOPIC 23 - REFERENCE TIME SERVER")
    print("=" * 64)
    print(f"Listening on UDP {args.host}:{args.port}")
    print(f"T2 source: {'kernel SO_TIMESTAMPNS' if stamper.kernel_enabled else 'user-space time'}"
          f"{'' if stamper.kernel_enabled or args.no_kernel_ts else ' (kernel timestamps unavailable)'}")
    print("Waiting for synchronization clients...")
    print(flush=True)

    try:
        serve(sock, stamper)
    except KeyboardInterrupt:
        pass
    finally:
        print(stamper.summary(), flush=True)


if __name__ == "__main__":
    main()
