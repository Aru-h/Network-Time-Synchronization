"""Sandbox test for the min-RTT filter: synthetic queueing makes the filter win."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation" / "code"))
import clockfilter as cf  # noqa: E402


class T(unittest.TestCase):
    def test_picks_min_rtt_offset(self):
        s = [(5, 1.0), (2, 9.0), (7, 3.0), (4, 4.0), (6, 5.0), (8, 6.0), (9, 7.0), (3, 8.0)]
        self.assertEqual(cf.min_rtt_filter(s), [9.0])
        self.assertEqual(len(cf.min_rtt_filter(s + [(1, 0.5)])), 2)

    def test_too_few_samples(self):
        self.assertIsNone(cf.compare([(1, 0)] * 7, 0))

    def test_filter_reduces_error_under_one_way_queueing(self):
        random.seed(1)
        samples = []
        for _ in range(60):
            q = random.expovariate(1 / 8.0)             # one-way queue delay (ms)
            samples.append((1.0 + q, -100.0 + q / 2))   # offset error is half the queue delay
        c = cf.compare(samples, -100.0)
        self.assertLess(c["filtered_mean_ms"], c["raw_mean_ms"])
        self.assertEqual(c["n_filtered"], 53)


if __name__ == "__main__":
    unittest.main()
