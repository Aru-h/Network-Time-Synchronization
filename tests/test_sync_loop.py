"""Sandbox tests for the software clock and the discipline loop: a fake clock, no sockets, no Mininet."""
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server_client")]
from softclock import SoftClock  # noqa: E402
from sync_loop import SyncLoop  # noqa: E402

S = 1_000_000_000


class Fake:
    def __init__(self):
        self.t = 1_700_000_000 * S

    def __call__(self):
        return self.t

    def advance(self, ns):
        self.t += int(ns)


def make_exchange(fake, seed=1, jitter=True, fail_every=0, bias_ms=0.0):
    """The server as a perfect reference. Each direction gets an independent random delay, so the measured
    offset is minus the clock's true error plus half the one-way asymmetry."""
    rnd, n = random.Random(seed), [0]

    def exchange(clock):
        n[0] += 1
        if fail_every and n[0] % fail_every == 0:
            return None
        d_req, d_rep = ((0.03 + rnd.expovariate(1 / 0.04)) if jitter else 0.05 for _ in range(2))
        return dict(rtt_ms=d_req + d_rep, rx_ns=fake(),
                    offset_ms=-clock.true_error_ns() / 1e6 + (d_req - d_rep) / 2 + bias_ms)
    return exchange


def drive(skew_ms=0.0, drift_ppm=0.0, polls=60, cap=500.0, step_ms=128.0, **kw):
    f = Fake()
    clock = SoftClock(skew_ns=skew_ms * 1e6, drift_ppm=drift_ppm, max_slew_ppm=cap, time_fn=f)
    loop = SyncLoop(clock, make_exchange(f, **kw), time_fn=f, step_ms=step_ms)
    rows = []
    for k in range(polls):
        f.advance(1 * S)
        rows.append(loop.poll(k + 1))
    return clock, loop, rows, f


class ClockTest(unittest.TestCase):
    def test_step(self):
        f = Fake()
        c = SoftClock(skew_ns=500_000_000, time_fn=f)
        c.step(-500_000_000)
        self.assertEqual(c.true_error_ns(), 0)
        c.step(5_000)
        self.assertEqual(c.now_ns() - f(), 5_000)

    def test_rate_is_capped(self):
        f = Fake()
        c = SoftClock(time_fn=f)
        self.assertEqual(c.set_rate_ppm(10_000), 500.0)
        self.assertEqual(c.set_rate_ppm(-10_000), -500.0)
        f.advance(1 * S)
        self.assertAlmostEqual(c.true_error_ns(), -500_000, delta=1)          # -500 ppm for 1 s
        self.assertEqual(SoftClock(max_slew_ppm=5000, time_fn=f).set_rate_ppm(9000), 5000.0)

    def test_slew_never_goes_backwards(self):
        f = Fake()
        c = SoftClock(skew_ns=100_000_000, drift_ppm=-50, time_fn=f)
        last = c.now_ns()
        for i in range(6000):
            if i % 400 == 0:
                c.set_rate_ppm(-500 if (i // 400) % 2 == 0 else 500)         # flip the rate; the clock never jumps back
            f.advance(1_000)
            now = c.now_ns()
            self.assertGreater(now, last)
            last = now

    def test_drift_grows_without_the_loop(self):
        f = Fake()
        c = SoftClock(drift_ppm=50, time_fn=f)
        errs = []
        for _ in range(60):
            f.advance(1 * S)
            errs.append(c.true_error_ns() / 1e6)
        self.assertAlmostEqual(errs[0], 0.05, places=6)
        self.assertAlmostEqual(errs[-1], 3.0, places=6)                      # 50 ppm * 60 s
        self.assertTrue(all(b > a for a, b in zip(errs, errs[1:])))


class LoopTest(unittest.TestCase):
    def test_small_offset_never_steps(self):
        for skew in (100.0, -100.0, 127.0, 5.0, 0.2):
            clock, loop, rows, _ = drive(skew_ms=skew, polls=40, cap=5000)
            self.assertEqual(loop.steps, 0, f"skew {skew} ms stepped")
            self.assertTrue(all(r["stepped"] == 0 for r in rows))
        self.assertLess(abs(rows[-1]["true_error"]), 0.1)                     # and 0.2 ms is slewed away

    def test_100ms_skew_converges_by_slewing_with_the_demo_cap(self):
        clock, loop, rows, _ = drive(skew_ms=100.0, polls=120, cap=5000)
        self.assertEqual(loop.steps, 0)
        self.assertLess(max(abs(r["true_error"]) for r in rows[60:]), 0.1)      # settles in about a minute at 5000 ppm
        self.assertLessEqual(max(abs(r["rate_ppm"]) for r in rows), 5000)

    def test_large_offset_steps_exactly_once(self):
        clock, loop, rows, _ = drive(skew_ms=500.0, polls=40)
        self.assertEqual(loop.steps, 1)
        self.assertEqual([r["stepped"] for r in rows].count(1), 1)
        self.assertEqual(rows[0]["stepped"], 1)                               # the first sample is far off
        self.assertGreater(abs(rows[0]["true_error"]), 400)
        self.assertLess(max(abs(r["true_error"]) for r in rows[2:]), 0.5)     # slew only afterwards, never stepped again

    def test_threshold_is_the_step_ms_flag(self):
        _, loop, _, _ = drive(skew_ms=100.0, polls=3, step_ms=50.0)
        self.assertEqual(loop.steps, 1)                                       # 100 ms > 50 ms
        _, loop, _, _ = drive(skew_ms=500.0, polls=3, step_ms=1000.0)
        self.assertEqual(loop.steps, 0)

    def test_slew_cap_respected_and_integral_anti_windup(self):
        clock, loop, rows, _ = drive(skew_ms=100.0, polls=60, cap=500)
        self.assertTrue(all(abs(r["rate_ppm"]) <= 500 for r in rows))
        self.assertEqual(rows[3]["rate_ppm"], -500.0)                         # skew +100 ms: clock is fast, saturated slow-down
        self.assertLessEqual(abs(loop.integral_ppm), 500)
        # 100 ms at 500 ppm takes ~200 s: after 60 s it is still being slewed, not stepped
        self.assertEqual(loop.steps, 0)
        self.assertGreater(abs(rows[-1]["true_error"]), 50)
        # the integrator did not wind up while saturated: when the offset finally closes it must not overshoot far
        clock, loop, rows, _ = drive(skew_ms=100.0, polls=330, cap=500)
        self.assertLess(max(-r["true_error"] for r in rows), 5.0)             # overshoot below -5 ms never happens

    def test_never_backwards_over_a_whole_run(self):
        for skew, cap in ((100.0, 5000), (-100.0, 500), (500.0, 500), (-500.0, 500)):
            _, loop, rows, _ = drive(skew_ms=skew, drift_ppm=50.0, polls=60, cap=cap)
            self.assertEqual(loop.backwards, 0, f"skew {skew}")
            self.assertEqual(rows[-1]["backwards"], 0)

    def test_drift_bounded_with_the_loop_and_frequency_learned(self):
        _, _, no_loop, f = None, None, None, None
        f0 = Fake()
        c0 = SoftClock(drift_ppm=50.0, time_fn=f0)
        f0.advance(60 * S)
        self.assertAlmostEqual(c0.true_error_ns() / 1e6, 3.0, places=6)       # without the loop: 3 ms after 60 s
        clock, loop, rows, _ = drive(drift_ppm=50.0, polls=90)
        self.assertLess(max(abs(r["true_error"]) for r in rows[45:]), 0.15)   # with it: bounded
        self.assertAlmostEqual(loop.freq_estimate_ppm, 50.0, delta=8.0)       # the frequency estimate is near the injected drift
        self.assertAlmostEqual(loop.integral_ppm, -50.0, delta=8.0)           # i.e. the integrator sits near -50 ppm

    def test_frequency_compensation_option_runs_and_converges(self):
        f = Fake()
        clock = SoftClock(drift_ppm=50.0, time_fn=f)
        loop = SyncLoop(clock, make_exchange(f), time_fn=f, freq_compensate=True)
        rows = []
        for k in range(90):
            f.advance(1 * S)
            rows.append(loop.poll(k + 1))
        self.assertLess(max(abs(r["true_error"]) for r in rows[45:]), 0.15)
        self.assertAlmostEqual(loop.freq_estimate_ppm, 50.0, delta=8.0)

    def test_timeouts_are_skipped(self):
        clock, loop, rows, _ = drive(skew_ms=20.0, polls=24, fail_every=3, cap=5000)
        self.assertEqual(sum(r["status"] == "TIMEOUT" for r in rows), 8)
        self.assertEqual(rows[0]["status"], "OK")
        self.assertLess(abs(rows[-1]["true_error"]), 0.2)


if __name__ == "__main__":
    unittest.main()
