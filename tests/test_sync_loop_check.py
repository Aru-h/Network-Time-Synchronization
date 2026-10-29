"""Sandbox tests for the sync-loop verdicts: synthetic CSVs, no Mininet."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "evaluation" / "code"), str(ROOT / "server_client")]
import sync_loop_check as chk  # noqa: E402
from sync_loop import FIELDS  # noqa: E402


def write(d, name, rows):
    """rows: (true_error, filtered_rtt, stepped, backwards)"""
    with (Path(d) / f"{name}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, (err, frtt, st, bw) in enumerate(rows):
            w.writerow(dict(t=i, status="OK", offset_est=0, rtt=frtt, filtered_offset=0, filtered_rtt=frtt, correction=0,
                            rate_ppm=0, true_error=err, stepped=st, backwards=bw))


def good(n=20, err=0.01, frtt=0.1, first_step=False):
    rows = [(5.0, frtt, 1 if first_step else 0, 0)] + [(err, frtt, 0, 0)] * (n - 1)
    return rows


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def res(self):
        legs, _ = chk.evaluate(self.d)
        return {n: (r, det) for n, r, det in legs}

    def test_missing_data_is_skip_never_pass(self):
        r = self.res()
        self.assertTrue(all(v[0] == "SKIP" for v in r.values()))         # nothing ran: every leg is SKIP, even report-only ones
        self.assertEqual(r["S5 < S4 error"][0], "SKIP")
        write(self.d, "S1_slew", good()[:3])                              # too few polls
        self.assertEqual(self.res()["S1_slew"][0], "SKIP")

    def test_pass_fail_on_bound_steps_and_monotonic(self):
        write(self.d, "S1_slew", good())
        self.assertEqual(self.res()["S1_slew"][0], "PASS")
        write(self.d, "S1_slew", good(err=0.2))                           # 0.2 > 0.05 bound
        self.assertEqual(self.res()["S1_slew"][0], "FAIL")
        write(self.d, "S1_slew", good(first_step=True))                   # a step where none is expected
        r = self.res()["S1_slew"]
        self.assertEqual(r[0], "FAIL")
        self.assertIn("steps", r[1])
        bad = good()
        bad[-1] = (0.01, 0.1, 0, 1)                                       # the clock went backwards
        write(self.d, "S1_slew", bad)
        self.assertEqual(self.res()["S1_slew"][0], "FAIL")
        write(self.d, "S2_step", good(first_step=True))                   # exactly one step
        self.assertEqual(self.res()["S2_step"][0], "PASS")

    def test_bound_uses_previous_filtered_rtt_and_the_drift_term(self):
        rows = [(9.0, 0.1, 0, 0)] * 3 + [(9.0, 0.2, 0, 0)] + [(0.09, 0.2, 0, 0)] * 4
        write(self.d, "S1_slew", rows)                                   # 0.09 <= prev 0.2/2 = 0.1: pass
        self.assertEqual(self.res()["S1_slew"][0], "PASS")
        write(self.d, "S3_drift", [(9.0, 0.1, 0, 0)] * 4 + [(0.09, 0.1, 0, 0)] * 6)   # 0.09 > 0.05 + 0 ...
        self.assertEqual(self.res()["S3_drift"][0], "PASS")               # ... but drift 50 ppm * 1 s adds 0.05: bound 0.10

    def test_report_only_legs_are_info_and_s5_must_beat_s4(self):
        write(self.d, "S4_load_qosoff", good(err=17.0, frtt=34.0, first_step=True))
        write(self.d, "S5_load_qoson", good(err=0.01, frtt=0.05, first_step=True))
        r = self.res()
        self.assertEqual(r["S4_load_qosoff"][0], "INFO")
        self.assertEqual(r["S5_load_qoson"][0], "PASS")
        self.assertEqual(r["S5 < S4 error"][0], "PASS")
        write(self.d, "S5_load_qoson", good(err=20.0, frtt=0.05, first_step=True))
        self.assertEqual(self.res()["S5 < S4 error"][0], "FAIL")

    def test_table_counts(self):
        write(self.d, "S1_slew", good())
        legs, _ = chk.evaluate(self.d)
        text, n = chk.render([("unit: x", "PASS", "")] + legs)
        self.assertEqual((n["PASS"], n["FAIL"]), (2, 0))
        self.assertGreaterEqual(n["SKIP"], 4)
        self.assertIn("INCOMPLETE", text)                                 # skips are never reported as a clean PASS
        self.assertNotIn("OVERALL: PASS", text)


if __name__ == "__main__":
    unittest.main()
