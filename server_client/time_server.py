#!/usr/bin/env python3
"""
UDP Reference Time Server
Topic 23 - Network Time Synchronization System

Protocol:
Client sends:  REQ|sequence|T1
Server records: T2 when request arrives
Server records: T3 immediately before reply
Server sends:  REP|sequence|T1|T2|T3

The client records T4 on receiving the response.
"""

import argparse
import socket
import time


def now_ns():
    return time.time_ns()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="10.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))

    print("=" * 64)
    print("TOPIC 23 - REFERENCE TIME SERVER")
    print("=" * 64)
    print(f"Listening on UDP {args.host}:{args.port}")
    print("Waiting for synchronization clients...")
    print()

    while True:
        data, addr = sock.recvfrom(2048)

        t2 = now_ns()

        try:
            parts = data.decode().strip().split("|")
            if len(parts) != 3 or parts[0] != "REQ":
                print(f"Ignoring malformed packet from {addr}: {data!r}")
                continue

            seq = int(parts[1])
            t1 = int(parts[2])
        except (ValueError, UnicodeDecodeError):
            print(f"Ignoring invalid packet from {addr}")
            continue

        t3 = now_ns()
        reply = f"REP|{seq}|{t1}|{t2}|{t3}".encode()

        sock.sendto(reply, addr)

        print(
            f"SYNC seq={seq:03d} client={addr[0]}:{addr[1]} "
            f"T2={t2} T3={t3}"
        )


if __name__ == "__main__":
    main()
