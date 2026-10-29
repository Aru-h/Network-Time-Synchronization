"""Sandbox tests for the age-aware filter: a fake clock model, no sockets, no Mininet."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server_client"), str(ROOT / "tests")]
from agefilter import AgeFilter, adjusted_offset_ms  # noqa: E402
import repro_drift_staleness as repro  # noqa: E402

S = 1_000_000_000


class Clock:
    """client error e(t) = skew + drift*t + correction (all ns); true offset = -e."""
    def __init__(self, skew_ns=0.0, drift_ppm=0.0):
        self.skew, self.drift, self.corr = skew_ns, drift_ppm, 0.0

    def err_ns(self, t_ns):
        return self.skew + self.drift * 1e-6 * t_ns + self.corr


class AdjustTest(unittest.TestCase):
    def test_corrected_offset_matches_true_offset_after_a_step(self):
        c = Clock(skew_ns=100e6)
        t0 = 5 * S
        sample = -c.err_ns(t0) / 1e6                      # measured offset -100 ms
        corr0 = c.corr
        c.corr += -100e6                                  # step applied afterwards
        t1 = 8 * S
        true_now = -c.err_ns(t1) / 1e6                    # 0 ms
        adj = adjusted_offset_ms(sample, corr0, c.corr, t1 - t0)
        self.assertAlmostEqual(adj, true_now, places=9)
        self.assertNotAlmostEqual(sample, true_now, places=3)         # uncorrected is wrong

    def test_corrected_offset_with_slew(self):
        c = Clock(skew_ns=20e6)
        t0, corr0 = 2 * S, c.corr
        sample = -c.err_ns(t0) / 1e6
        c.corr += -300 * 1e-6 * 4 * S                     # 300 ppm slew for 4 s
        t1 = 6 * S
        self.assertAlmostEqual(adjusted_offset_ms(sample, corr0, c.corr, t1 - t0), -c.err_ns(t1) / 1e6, places=9)

    def test_drift_term(self):
        c = Clock(drift_ppm=50.0)
        t0, corr0 = 10 * S, c.corr
        sample = -c.err_ns(t0) / 1e6
        t1 = 16 * S
        true_now = -c.err_ns(t1) / 1e6
        self.assertAlmostEqual(adjusted_offset_ms(sample, corr0, c.corr, t1 - t0, drift_est_ppm=50.0), true_now, places=9)
        # without the estimate the stale sample is off by drift * age = 50 ppm * 6 s = 0.3 ms
        self.assertAlmostEqual(abs(adjusted_offset_ms(sample, corr0, c.corr, t1 - t0) - true_now), 0.3, places=9)


class RankTest(unittest.TestCase):
    def test_stale_low_rtt_loses_to_fresh_slightly_higher_rtt(self):
        f = AgeFilter(8, phi_ppm=100)
        f.add(0.08, 1.0, 0.0, 0)                          # best RTT, 6 s old
        f.add(0.20, 2.0, 0.0, 6 * S)                      # fresh, 0.12 ms higher RTT
        b = f.best(0.0, 6 * S)
        self.assertEqual(b["offset_ms"], 2.0)             # fresh wins: 0.1 < 0.04 + 0.6
        plain = AgeFilter(8, phi_ppm=0)                   # no age term: the old behaviour
        plain.add(0.08, 1.0, 0.0, 0)
        plain.add(0.20, 2.0, 0.0, 6 * S)
        self.assertEqual(plain.best(0.0, 6 * S)["offset_ms"], 1.0)

    def test_stale_sample_still_wins_when_rtt_gap_is_large(self):
        f = AgeFilter(8, phi_ppm=100)
        f.add(34.0, 17.0, 0.0, 0)                         # queueing: old but 11 ms lower RTT
        f.add(45.0, 22.0, 0.0, 3 * S)
        self.assertEqual(f.best(0.0, 3 * S)["offset_ms"], 17.0)       # 17.3 < 22.5

    def test_ties_go_to_newest_and_window_evicts(self):
        f = AgeFilter(3, phi_ppm=0)
        for i in range(5):
            f.add(1.0, float(i), 0.0, i * S)
        self.assertEqual(len(f), 3)
        self.assertEqual(f.best(0.0, 4 * S)["offset_ms"], 4.0)
        self.assertIsNone(AgeFilter().best(0.0, 0))


class ReproTest(unittest.TestCase):
    """The drift failure, reproduced in simulation, and its fix (see tests/repro_drift_staleness.py)."""
    def test_root_cause_and_fix(self):
        rows = {(v, p): (w, m, f, n) for v, p, w, m, f, n in
                repro.table([("raw", 0), ("min_rtt", 0), ("age", 100), ("age+f", 100)], seeds=40)}
        raw, minrtt = rows[("raw", 0)], rows[("min_rtt", 0)]
        age, agef = rows[("age", 100)], rows[("age+f", 100)]
        self.assertGreater(raw[0], 4 * minrtt[0])                    # uncorrected offsets are far worse (cause a)
        self.assertEqual(minrtt[2], minrtt[3])                       # min-RTT, no age: fails the bound every time
        self.assertGreater(minrtt[0], 0.3)                           # ~0.4 ms, as the real run showed (cause b)
        self.assertLess(age[0], minrtt[0] / 2)                       # age ranking helps a lot
        self.assertEqual(agef[2], 0)                                 # age + drift term: no leg fails the bound


if __name__ == "__main__":
    unittest.main()
