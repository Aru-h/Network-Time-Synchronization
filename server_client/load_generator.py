#!/usr/bin/env python3
"""Optional UDP background traffic generator for D1 experiments."""

import argparse
import socket
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--pps", type=int, default=500)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--size", type=int, default=512)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b"LOAD" + bytes(max(0, args.size - 4))

    destination = (args.destination, args.port)
    interval = 1.0 / max(1, args.pps)

    print(
        f"Sending background UDP load to {destination}, "
        f"{args.pps} packets/s for {args.duration}s"
    )

    end = time.time() + args.duration
    count = 0

    while time.time() < end:
        try:
            sock.sendto(payload, destination)
            count += 1
        except OSError:
            break
        time.sleep(interval)

    print(f"Background packets sent: {count}")


if __name__ == "__main__":
    main()
