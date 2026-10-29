"""Loopback sandbox test for kernel receive timestamps (no Mininet, no root).

1. The kernel stamp is never later than a user-space time taken right after the read.
2. User-space vs kernel median offset error over the full server+client exchange.
3. A missing kernel stamp falls back to user-space time and is counted.
4. A stale reply is skipped and the sample is not lost.
"""
import socket
import statistics
import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server_client"), str(ROOT / "evaluation" / "code")]
import ktime  # noqa: E402
import robustness_eval as ev  # noqa: E402
import time_server  # noqa: E402

N = 300
SKEW_MS = 100.0


def udp(bind=None, timeout=None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if bind:
        s.bind(bind)
    if timeout:
        s.settimeout(timeout)
    return s


class Server:
    def __init__(self, use_kernel):
        self.sock = udp(("127.0.0.1", 0), timeout=0.2)
        self.addr = self.sock.getsockname()
        self.stamper = ktime.Stamper(self.sock, use_kernel=use_kernel)
        self.stop = False
        self.t = threading.Thread(target=time_server.serve, args=(
            self.sock, self.stamper, lambda: self.stop, lambda *_: None), daemon=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *_):
        self.stop = True
        self.t.join()
        self.sock.close()


def busy(flag):
    while not flag["stop"]:
        sum(range(2000))


class KernelStampTest(unittest.TestCase):
    def test_kernel_stamp_never_later_than_userspace(self):
        rx, tx = udp(("127.0.0.1", 0)), udp()
        st = ktime.Stamper(rx)
        self.assertTrue(st.kernel_enabled, "SO_TIMESTAMPNS not available here")
        late = 0
        diffs = []
        for _ in range(N):
            before = time.time_ns()
            tx.sendto(b"x", rx.getsockname())
            _d, _a, k, src = st.recv()
            after = time.time_ns()
            self.assertEqual(src, ktime.KERNEL)
            self.assertGreaterEqual(k, before)      # stamped after the send began
            if k > after:
                late += 1
            diffs.append(after - k)
        rx.close(); tx.close()
        self.assertEqual(late, 0, "kernel stamp later than the user-space time")
        self.assertEqual(st.fallbacks, 0)
        print(f"\n[1] kernel stamp <= user-space read time in {N}/{N} packets; "
              f"user-space lag median {statistics.median(diffs)/1000:.1f} us")

    def run_mode(self, use_kernel, load):
        flag = {"stop": False}
        threads = [threading.Thread(target=busy, args=(flag,), daemon=True) for _ in range(load)]
        for t in threads:
            t.start()
        try:
            with Server(use_kernel) as srv:
                rows, st = ev.collect(srv.addr, N, 0, 1.0, SKEW_MS, use_kernel=use_kernel)
        finally:
            flag["stop"] = True
        errs = [float(r["abs_error_ms"]) * 1000 for r in rows if r["status"] == "OK"]
        self.assertGreater(len(errs), N * 0.9)
        return statistics.median(errs), st

    def test_median_error_user_vs_kernel(self):
        print("\n[2] median |offset error| on loopback (true offset = -skew), us")
        print(f"    {'scenario':<26}{'user-space':>12}{'kernel':>10}")
        for label, load in (("idle", 0), ("3 busy CPU threads", 3)):
            u, _ = self.run_mode(False, load)
            k, st = self.run_mode(True, load)
            self.assertEqual(st.fallbacks, 0)
            print(f"    {label:<26}{u:12.3f}{k:10.3f}")

    def test_fallback_is_counted(self):
        rx, tx = udp(("127.0.0.1", 0), timeout=1), udp()

        class NoStamp:                      # a socket whose recvmsg never returns a kernel stamp
            def setsockopt(self, *a):
                return rx.setsockopt(*a)

            def recvmsg(self, n, a):
                d, _anc, f, addr = rx.recvmsg(n, a)
                return d, [], f, addr

        st = ktime.Stamper(NoStamp())
        tx.sendto(b"x", rx.getsockname())
        _d, _a, _t, src = st.recv()
        self.assertEqual(src, ktime.FALLBACK)
        self.assertEqual((st.kernel, st.fallbacks), (0, 1))
        self.assertIn("user-space-fallback=1", st.summary())
        rx.close(); tx.close()
        print("\n[3] a dropped kernel stamp is counted:", st.summary())

    def test_stale_reply_does_not_lose_the_sample(self):
        sock = udp(("127.0.0.1", 0), timeout=2)
        addr = sock.getsockname()
        stop = False

        def serve():
            while not stop:
                try:
                    data, a = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                seq, t1 = int(data.decode().split("|")[1]), int(data.decode().split("|")[2])
                t = time.time_ns()
                reply = f"REP|{seq}|{t1}|{t}|{t}".encode()
                delay = {1: 0.25, 2: 0.15}.get(seq, 0)     # seq 1 answers after its deadline
                threading.Timer(delay, sock.sendto, (reply, a)).start()

        th = threading.Thread(target=serve, daemon=True)
        th.start()
        rows, _ = ev.collect(addr, 3, 0, 0.2, SKEW_MS)
        stop = True
        th.join()
        sock.close()
        self.assertEqual(rows[0]["status"], "ERROR:timeout")
        self.assertEqual(rows[1]["status"], "OK", "stale reply cost sample 2")
        self.assertEqual(rows[2]["status"], "OK")
        self.assertGreaterEqual(sum(int(r["stale"]) for r in rows), 1)
        print("\n[4] stale reply skipped:", [(r["seq"], r["status"], r["stale"]) for r in rows])


if __name__ == "__main__":
    unittest.main(verbosity=1)
