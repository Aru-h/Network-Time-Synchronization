"""
A software clock for the sync loop: a simulated local clock that can be stepped and slewed.

    now_ns() = real_ns + skew_ns + drift_ppm * 1e-6 * elapsed_ns + correction_ns

`real_ns` is the host's time_ns() (CLOCK_REALTIME). `skew_ns` and `drift_ppm` simulate a bad
oscillator; `correction_ns` is what the sync loop has applied: step(delta) adds to it at once,
set_rate_ppm(r) makes it grow at r ppm until the next call. The OS clock is never changed.

true_error_ns() = now_ns() - real_ns = skew + drift * elapsed + correction. It is only valid because
every Mininet host shares one kernel clock, so "real" time is the same reference the server uses. On
separate machines this number would not exist: a real client only knows its offset estimate.

Slewing never makes now_ns() go backwards: the rate is capped (default 500 ppm), so the clock always
runs at 1 + (drift + rate) * 1e-6 > 0 times real time, whatever sequence of rates is set. step() is a
one-time jump and moves the clock back when it is given a negative delta (that is what it is for).
"""
import time


class SoftClock:
    def __init__(self, skew_ns=0, drift_ppm=0.0, max_slew_ppm=500.0, time_fn=time.time_ns):
        if max_slew_ppm < 0 or abs(drift_ppm) + max_slew_ppm >= 1e6:
            raise ValueError("slew cap and drift must leave a clock that still moves forward")
        self.skew_ns = int(skew_ns)
        self.drift_ppm = float(drift_ppm)
        self.max_slew_ppm = float(max_slew_ppm)
        self._time = time_fn
        self._t0 = self._last = time_fn()
        self._corr = 0.0        # correction (ns) as of self._last
        self._rate = 0.0        # correction rate (ppm) since self._last

    @property
    def rate_ppm(self):
        return self._rate

    def correction_ns(self, real_ns=None):
        """Correction at real time `real_ns` (not earlier than the last step()/set_rate_ppm())."""
        real_ns = self._time() if real_ns is None else real_ns
        return self._corr + self._rate * 1e-6 * (real_ns - self._last)

    def at(self, real_ns):
        """The soft clock's reading at real time `real_ns`, e.g. a kernel receive stamp."""
        drift = self.drift_ppm * 1e-6 * (real_ns - self._t0)
        # real_ns is ~1.7e18, beyond a float's exact integers: round the small float terms, then add to the int
        return real_ns + int(round(self.skew_ns + drift + self.correction_ns(real_ns)))

    def now_ns(self):
        return self.at(self._time())

    def true_error_ns(self, real_ns=None):
        real_ns = self._time() if real_ns is None else real_ns
        return self.at(real_ns) - real_ns

    def _advance(self):
        now = self._time()
        self._corr = self.correction_ns(now)
        self._last = now

    def step(self, delta_ns):
        self._advance()
        self._corr += delta_ns

    def set_rate_ppm(self, rate_ppm):
        """Run the correction at `rate_ppm` from now on, clamped to +-max_slew_ppm. Returns the applied rate."""
        self._advance()
        self._rate = max(-self.max_slew_ppm, min(self.max_slew_ppm, float(rate_ppm)))
        return self._rate
