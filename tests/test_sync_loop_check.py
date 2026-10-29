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


def write(d, name, rows, jumps=None):
    """rows: (true_error, filtered_rtt, stepped, backwards); jumps: clock_jump_ms per row (None = not recorded)"""
    with (Path(d) / f"{name}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for i, (err, frtt, st, bw) in enumerate(rows):
            w.writerow(dict(t=i, status="OK", offset_est=0, rtt=frtt, filtered_offset=0, filtered_rtt=frtt, correction=0,
                            rate_ppm=0, true_error=err, stepped=st, backwards=bw,
                            clock_jump_ms="" if jumps is None else jumps[i]))


def write_load(d, name, per_second, alive=True, unit="Mbits"):
    """An iperf server log with one 1 s interval per entry, and the runner's note about the sender."""
    lines = []
    for i, r in enumerate(per_second):
        txt = f"{r:.1f} Mbits/sec" if r > 0 else "0.000 bits/sec"
        lines.append(f"[  1] {i:.4f}-{i + 1:.4f} sec  2.3 MBytes  {txt}   0.8 ms 0/1654 (0%)")
    (Path(d) / f"{name}_iperf_server.log").write_text("\n".join(lines) + "\n")
    (Path(d) / f"{name}.txt").write_text(f"polls 90\nload 30M offered, still running at end of leg: {alive}\n")


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
        write_load(self.d, "S4_load_qosoff", [19.4] * 30)
        write_load(self.d, "S5_load_qoson", [19.4] * 30)
        r = self.res()
        self.assertEqual(r["S4_load_qosoff"][0], "INFO")
        self.assertEqual(r["S5_load_qoson"][0], "PASS")
        self.assertEqual(r["S5 < S4 error"][0], "PASS")
        write(self.d, "S5_load_qoson", good(err=20.0, frtt=0.05, first_step=True))
        self.assertEqual(self.res()["S5 < S4 error"][0], "FAIL")

    def test_ninety_five_percent_rule(self):
        def one_over(n_over, n=60):
            rows = [(5.0, 0.1, 0, 0)] + [(0.01, 0.1, 0, 0)] * (n - 1)       # 60 rows: 30 steady polls
            idx = len(rows) // 2 + 3
            for k in range(n_over):
                rows[idx + k] = (0.2, 0.1, 0, 0)                            # 0.2 vs bound 0.05: over by 0.15
            return rows
        write(self.d, "S1_slew", one_over(0))
        self.assertEqual(self.res()["S1_slew"][0], "PASS")
        write(self.d, "S1_slew", one_over(1))                              # 1 of 30 steady polls over: 96.7% within
        a = chk.analyze(Path(self.d) / "S1_slew.csv", 0.0)
        self.assertEqual((a["steady"], a["violations"]), (30, 1))
        self.assertAlmostEqual(a["worst_excess"], 0.15)
        self.assertEqual(chk.verdict(a, 0, "PASS")[0], "PASS")             # the 95% rule passes it ...
        self.assertEqual(chk.verdict(a, 0, "PASS", strict=True)[0], "FAIL")   # ... the original strict rule does not
        self.assertIn("worst excess 0.1500 ms", chk.verdict(a, 0, "PASS")[1])
        write(self.d, "S1_slew", one_over(2))                              # 2 of 30: 93.3% within
        a = chk.analyze(Path(self.d) / "S1_slew.csv", 0.0)
        self.assertEqual(chk.verdict(a, 0, "PASS")[0], "FAIL")
        # steps and monotonic stay strict under the new rule
        a["steps"] = 2
        self.assertEqual(chk.verdict(dict(a, violations=0, within=1.0), 0, "PASS")[0], "FAIL")

    def test_optional_cpubusy_leg_is_omitted_when_not_run(self):
        self.assertNotIn("S6_idle_cpubusy", self.res())
        write(self.d, "S6_idle_cpubusy", good(first_step=True))
        self.assertEqual(self.res()["S6_idle_cpubusy"][0], "INFO")

    def test_clock_step_makes_a_leg_invalid_and_counts_as_skip(self):
        rows = good(n=20)
        write(self.d, "S1_slew", rows, jumps=[0.0] * 20)
        r = self.res()["S1_slew"]
        self.assertEqual(r[0], "PASS")
        self.assertNotIn("not recorded", r[1])
        write(self.d, "S1_slew", rows, jumps=[0.0] * 7 + [456_300.0] + [0.0] * 12)      # the suspend/resume of run 3
        r = self.res()["S1_slew"]
        self.assertEqual(r[0], "INVALID")
        self.assertIn("456300.0 ms", r[1])
        self.assertIn("Data kept", r[1])
        write(self.d, "S1_slew", rows, jumps=[0.0] * 7 + [4.9] + [0.0] * 12)             # under 5 ms: valid
        self.assertEqual(self.res()["S1_slew"][0], "PASS")
        write(self.d, "S1_slew", rows, jumps=[0.0] * 7 + [-5.1] + [0.0] * 12)            # a step backwards counts too
        self.assertEqual(self.res()["S1_slew"][0], "INVALID")
        write(self.d, "S1_slew", rows)                                                    # column not recorded (runs 1-3)
        r = self.res()["S1_slew"]
        self.assertEqual(r[0], "PASS")
        self.assertIn("clock-step check not recorded", r[1])
        legs, _ = chk.evaluate(self.d)
        write(self.d, "S1_slew", rows, jumps=[0.0] * 7 + [456_300.0] + [0.0] * 12)
        legs, _ = chk.evaluate(self.d)
        text, n = chk.render(legs)
        self.assertEqual(n["INVALID"], 1)
        self.assertGreaterEqual(n["SKIP"], n["INVALID"])                                  # INVALID is inside the SKIP count
        self.assertIn("of which INVALID 1", text)
        self.assertNotIn("OVERALL: PASS", text)

    def test_load_gate(self):
        write(self.d, "S5_load_qoson", good(n=60, first_step=True))                      # 60 polls: steady half is t >= 30
        write_load(self.d, "S5_load_qoson", [19.4] * 70)
        r = self.res()["S5_load_qoson"]
        self.assertEqual(r[0], "PASS")
        self.assertIn("19.4 Mbit/s mean, 19.4 min", r[1])                                # saturation is printed, no threshold applied
        write_load(self.d, "S5_load_qoson", [19.4] * 40 + [0.0] * 30)                    # load stalls at 40 s: steady window starts at ~31 s
        r = self.res()["S5_load_qoson"]
        self.assertEqual(r[0], "INVALID")
        self.assertIn("0 Mbit/s", r[1])
        write_load(self.d, "S5_load_qoson", [19.4] * 70, alive=False)                    # sender gone at the end
        self.assertEqual(self.res()["S5_load_qoson"][0], "INVALID")
        write_load(self.d, "S5_load_qoson", [19.4] * 20)                                  # server log ends early: missing seconds count as 0
        self.assertEqual(self.res()["S5_load_qoson"][0], "INVALID")
        write_load(self.d, "S5_load_qoson", [0.5] * 70)                                   # a low but non-zero load is valid: no threshold
        self.assertEqual(self.res()["S5_load_qoson"][0], "PASS")
        (Path(self.d) / "S5_load_qoson_iperf_server.log").unlink()                        # no log at all
        self.assertEqual(self.res()["S5_load_qoson"][0], "INVALID")

    def test_zero_rate_lines_are_parsed(self):
        write_load(self.d, "S4_load_qosoff", [19.4, 0.0, 19.4])
        got = chk.load_per_second(Path(self.d) / "S4_load_qosoff_iperf_server.log")
        self.assertEqual(sorted(got), [0, 1, 2])
        self.assertEqual(got[1], 0.0)                                                     # D2's iperf_server_summary regex would drop this line

    def test_s5_vs_s4_is_skip_when_either_load_leg_is_invalid(self):
        write(self.d, "S4_load_qosoff", good(n=60, err=17.0, frtt=34.0, first_step=True))
        write(self.d, "S5_load_qoson", good(n=60, err=0.01, frtt=0.05, first_step=True))
        write_load(self.d, "S4_load_qosoff", [19.4] * 70)
        write_load(self.d, "S5_load_qoson", [19.4] * 70)
        r = self.res()
        self.assertEqual((r["S4_load_qosoff"][0], r["S5 < S4 error"][0]), ("INFO", "PASS"))
        write_load(self.d, "S4_load_qosoff", [19.4] * 40 + [0.0] * 30)
        r = self.res()
        self.assertEqual((r["S4_load_qosoff"][0], r["S5 < S4 error"]), ("INVALID", ("SKIP", "S4 INVALID")))
        write_load(self.d, "S4_load_qosoff", [19.4] * 70)
        write_load(self.d, "S5_load_qoson", [19.4] * 70, alive=False)
        self.assertEqual(self.res()["S5 < S4 error"][1], "S5 INVALID")

    def test_one_counting_rule_gives_the_same_total_in_every_run(self):
        setup = [("sandbox: a", "PASS", ""), ("sandbox: b", "PASS", ""), ("sandbox: c", "PASS", ""),
                 ("environment probe", "PASS", ""), ("mininet run (exit status)", "PASS", "")]
        def totals(d):
            legs, _ = chk.evaluate(d)
            n = chk.count(setup + legs)
            return n, n["PASS"] + n["FAIL"] + n["SKIP"]

        def full(good_s4=True, with_s6=True):
            d = tempfile.mkdtemp()
            for name in ("S1_slew", "S2_step", "S3_drift", "S3f_drift_freq"):
                write(d, name, good(first_step=name == "S2_step"))
            for name in ("S4_load_qosoff", "S5_load_qoson"):
                write(d, name, good(n=60, err=0.01 if "S5" in name else 17.0, frtt=0.05 if "S5" in name else 34.0, first_step=True))
                write_load(d, name, [19.4] * 70)
            if not good_s4:
                write_load(d, "S4_load_qosoff", [19.4] * 40 + [0.0] * 30)                 # the run 3 situation
            if with_s6:
                write(d, "S6_idle_cpubusy", good(first_step=True))
            return d
        n4, t4 = totals(full())
        n3, t3 = totals(full(good_s4=False))
        n1, t1 = totals(full(with_s6=False))                                              # runs 1 and 2 had no S6
        self.assertEqual((t4, t3, t1), (chk.COUNTED_CHECKS,) * 3)
        self.assertEqual((n4["PASS"], n4["FAIL"], n4["SKIP"]), (10, 0, 0))
        self.assertEqual((n3["PASS"], n3["FAIL"], n3["SKIP"]), (9, 0, 1))                 # only the S4-dependent check is SKIP
        self.assertEqual(n3["INVALID"], 0)                                                # the INVALID S4 itself is report-only: not counted
        self.assertEqual((n1["PASS"], n1["FAIL"], n1["SKIP"]), (10, 0, 0))
        self.assertEqual(n4["INFO"], 3)
        self.assertEqual(n1["INFO"], 2)

    def test_head_start_matches_the_runner(self):
        src = (ROOT / "evaluation" / "ubuntu_runner" / "run_sync_loop.py").read_text()
        self.assertIn(f"LOAD_HEAD_START_S = {chk.LOAD_HEAD_START_S}", src.replace("LOAD_MBPS, LOAD_HEAD_START_S = rt.OVER_LOAD_MBPS, ", "LOAD_HEAD_START_S = "))

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
