#!/usr/bin/env python3
"""
Sync loop: a client that disciplines a software clock, not only measures its offset.

Every --poll seconds one four-timestamp exchange against the unchanged time server
(REQ|seq|T1 -> REP|seq|T1|T2|T3). T1 is read from the SoftClock; T4 is the kernel receive stamp
(ktime.Stamper) mapped through the SoftClock. Samples go into an age-aware 8-sample window
(agefilter.py: offsets corrected for adjustments made since, ranked by rtt/2 + age*phi). Then:

  |filtered_offset| > --step-ms (default 128)  -> step the clock by that offset
  otherwise                                    -> slew only: a PI controller turns the filtered offset
                                                  into a rate (ppm), clamped to +-(--max-slew-ppm)
The step threshold follows real NTP: a small offset is never stepped, so a 100 ms skew is removed by
slewing alone, which at the default 500 ppm cap takes about 200 s. --max-slew-ppm 5000 is a DEMO
setting that makes such a run converge in a short test; it is not realistic NTP behaviour.

The PI integral term is the loop's frequency estimate (it settles near minus the oscillator drift);
anti-windup: the integral is clamped to the rate cap, is not accumulated while the output is saturated
in the direction of the error, and is only accumulated while |offset| < INTEGRAL_BAND_MS (integral
separation: a large offset is a phase error being slewed out, not a frequency error). --freq-compensate also feeds that estimate to the filter,
so an old sample is corrected for drift as well as for the corrections applied since (off by default).

CSV, one row per poll: t, offset_est, rtt, filtered_offset, correction, rate_ppm, true_error, stepped
(ms except rate_ppm and t in s), plus status, filtered_rtt, backwards and clock_jump_ms. true_error is only known because
Mininet hosts share one kernel clock (see softclock.py). `backwards` counts readings of the clock that
went back for any reason other than a step; it must stay 0. `clock_jump_ms` is how much (wall clock - CLOCK_MONOTONIC)
changed since the previous poll. CLOCK_MONOTONIC is slewed like the wall clock, so that difference stays constant while
chrony slews and changes only when the wall clock is stepped or the machine is suspended and resumed (a laptop going to
sleep under the VM). sync_loop_check.py marks a leg INVALID if any poll shows more than 5 ms.
"""
import argparse
import csv
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ktime  # noqa: E402
from agefilter import AgeFilter, DEFAULT_PHI_PPM  # noqa: E402
from softclock import SoftClock  # noqa: E402

FIELDS = ["t", "status", "offset_est", "rtt", "filtered_offset", "filtered_rtt", "correction",
          "rate_ppm", "true_error", "stepped", "backwards", "clock_jump_ms"]
TAU_POLLS = 4          # PI time constant: the offset is removed over about 4 polls; critically damped (ki = kp^2 / 4)
INTEGRAL_BAND_MS = 2.0  # integral separation: accumulate only when |offset| is below this. A larger offset is a
                        # phase error being slewed out, not a frequency error; integrating it winds the integrator up
                        # and costs an overshoot of ~2% (found by test: 100 ms -> -2 ms, then tens of seconds to unwind).
                        # A steady drift of d ppm holds the P term at d/(kp*1e3) ms (0.2 ms for 50 ppm), well inside.


class SyncLoop:
    """The discipline logic. `exchange(clock)` returns {'rtt_ms','offset_ms','rx_ns'} or None on a timeout;
    tests drive it with a fake clock and no sockets."""

    def __init__(self, clock, exchange, time_fn=time.time_ns, poll_s=1.0, step_ms=128.0,
                 phi_ppm=DEFAULT_PHI_PPM, freq_compensate=False, mono_fn=time.monotonic_ns):
        self.clock, self.exchange, self.time, self.mono = clock, exchange, time_fn, mono_fn
        self._wall_minus_mono = None
        self.poll_s, self.step_ms, self.freq_compensate = poll_s, step_ms, freq_compensate
        self.filter = AgeFilter(phi_ppm=phi_ppm)
        self.kp = 1.0 / (TAU_POLLS * poll_s)              # 1/s
        self.ki = self.kp * self.kp / 4                   # 1/s^2
        self.integral_ppm = 0.0                           # the frequency estimate
        self.steps = 0
        self.backwards = 0
        self._last_now, self._stepped = None, False

    @property
    def freq_estimate_ppm(self):
        """Estimated oscillator drift (ppm): minus what the integrator has settled on."""
        return -self.integral_ppm

    def _read(self):
        """Read the clock and count any backwards movement that is not a step."""
        now = self.clock.now_ns()
        if self._last_now is not None and now < self._last_now and not self._stepped:
            self.backwards += 1
        self._last_now, self._stepped = now, False
        return now

    def _clock_jump_ms(self):
        """Change of (wall - monotonic) since the previous poll; 0 on the first poll."""
        d = self.time() - self.mono()
        jump = 0.0 if self._wall_minus_mono is None else (d - self._wall_minus_mono) / 1e6
        self._wall_minus_mono = d
        return jump

    def poll(self, t_s):
        clock = self.clock
        jump = self._clock_jump_ms()
        self._read()
        res = self.exchange(clock)
        at = res["rx_ns"] if res else self.time()
        row = dict(t=round(t_s, 3), status="OK", offset_est="", rtt="", filtered_offset="", filtered_rtt="",
                   correction=round(clock.correction_ns(at) / 1e6, 6), rate_ppm=round(clock.rate_ppm, 3),
                   true_error=round(clock.true_error_ns(at) / 1e6, 6), stepped=0, backwards=self.backwards,
                   clock_jump_ms=round(jump, 6))
        if res is None:
            row["status"] = "TIMEOUT"
            return row
        row.update(offset_est=round(res["offset_ms"], 6), rtt=round(res["rtt_ms"], 6))
        self.filter.add(res["rtt_ms"], res["offset_ms"], clock.correction_ns(at), at)
        now = self.time()
        best = self.filter.best(clock.correction_ns(now), now,
                                self.freq_estimate_ppm if self.freq_compensate else 0.0)
        f = best["offset_ms"]
        row.update(filtered_offset=round(f, 6), filtered_rtt=round(best["rtt_ms"], 6))
        cap = clock.max_slew_ppm
        if abs(f) > self.step_ms:
            clock.step(f * 1e6)                            # large offset: step; the offset is gone, keep the frequency estimate
            self.steps += 1
            self._stepped = True
            row["stepped"] = 1
            rate = self.integral_ppm
        else:
            p = self.kp * f * 1e3                          # ms -> ppm: offset removed over TAU polls
            unsat = p + self.integral_ppm
            sat = max(-cap, min(cap, unsat))
            opposing = (unsat > cap and f < 0) or (unsat < -cap and f > 0)
            if abs(f) < INTEGRAL_BAND_MS and (unsat == sat or opposing):        # anti-windup: not while saturated, not for a big offset
                self.integral_ppm = max(-cap, min(cap, self.integral_ppm + self.ki * f * 1e3 * self.poll_s))
            rate = p + self.integral_ppm
        row["rate_ppm"] = round(clock.set_rate_ppm(rate), 3)
        self._read()
        row["backwards"] = self.backwards
        return row


def make_exchange(sock, stamper, server, timeout):
    """One exchange against the server; a late reply to an earlier request is skipped until the deadline."""
    seq = [0]

    def exchange(clock):
        seq[0] += 1
        t1 = clock.now_ns()
        deadline = time.monotonic() + timeout
        try:
            sock.sendto(f"REQ|{seq[0]}|{t1}".encode(), server)
        except OSError:
            return None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            sock.settimeout(remaining)
            try:
                data, _addr, rx_ns, _src = stamper.recv(2048)
                p = data.decode().strip().split("|")
                if len(p) != 5 or p[0] != "REP":
                    continue
                rseq, t1_echo, t2, t3 = map(int, p[1:])
            except socket.timeout:
                return None
            except (ValueError, UnicodeDecodeError):
                continue
            if rseq != seq[0] or t1_echo != t1:
                continue
            t4 = clock.at(rx_ns)
            return dict(rtt_ms=((t4 - t1) - (t3 - t2)) / 1e6, offset_ms=((t2 - t1) + (t3 - t4)) / 2 / 1e6, rx_ns=rx_ns)
    return exchange


def main():
    ap = argparse.ArgumentParser(description="Disciplines a software clock against the time server")
    ap.add_argument("--server", default="10.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--timeout", type=float, default=0.9, help="per-sample deadline (s); keep below --poll")
    ap.add_argument("--skew-ms", type=float, default=100.0)
    ap.add_argument("--drift-ppm", type=float, default=0.0)
    ap.add_argument("--step-ms", type=float, default=128.0)
    ap.add_argument("--max-slew-ppm", type=float, default=500.0, help="500 is realistic; 5000 is a demo setting")
    ap.add_argument("--phi-ppm", type=float, default=DEFAULT_PHI_PPM, help="assumed oscillator tolerance for sample ageing")
    ap.add_argument("--freq-compensate", action="store_true", help="remove the estimated drift from old samples too")
    ap.add_argument("--csv", required=True)
    a = ap.parse_args()

    clock = SoftClock(skew_ns=a.skew_ms * 1e6, drift_ppm=a.drift_ppm, max_slew_ppm=a.max_slew_ppm)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stamper = ktime.Stamper(sock)
    loop = SyncLoop(clock, make_exchange(sock, stamper, (a.server, a.port), a.timeout), poll_s=a.poll,
                    step_ms=a.step_ms, phi_ppm=a.phi_ppm, freq_compensate=a.freq_compensate)
    print(f"sync loop: {a.server}:{a.port} skew {a.skew_ms:+.1f} ms drift {a.drift_ppm:+.1f} ppm poll {a.poll} s "
          f"duration {a.duration} s step>{a.step_ms} ms slew cap {a.max_slew_ppm} ppm phi {a.phi_ppm} ppm"
          f"{' [DEMO slew cap]' if a.max_slew_ppm > 500 else ''}")
    rows, start = [], time.monotonic()
    nxt = start
    while time.monotonic() - start < a.duration:
        row = loop.poll(time.monotonic() - start)
        rows.append(row)
        print(f"t={row['t']:6.1f} {row['status']:<7} offset_est={row['offset_est']!s:>10} rtt={row['rtt']!s:>9} "
              f"rate={row['rate_ppm']:>8} ppm  true_error={row['true_error']:+.4f} ms{'  STEP' if row['stepped'] else ''}", flush=True)
        nxt += a.poll
        time.sleep(max(0.0, nxt - time.monotonic()))
    out = Path(a.csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if r["status"] == "OK"]
    print(f"polls {len(rows)}, ok {len(ok)}, timeouts {len(rows) - len(ok)}, steps {loop.steps}, "
          f"backwards {loop.backwards}, frequency estimate {loop.freq_estimate_ppm:+.2f} ppm, max wall-vs-monotonic jump "
          f"{max((abs(r['clock_jump_ms']) for r in rows), default=0):.3f} ms; {stamper.summary()}")
    if stamper.fallbacks:
        print(f"WARNING: {stamper.fallbacks} sample(s) used user-space time for T4")
    print(f"CSV: {out}")


if __name__ == "__main__":
    main()
