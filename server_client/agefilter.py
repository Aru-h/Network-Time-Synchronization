"""
Age-aware clock filter for the sync loop.

Keeps the last `window` (default 8) samples. Each stores the offset it measured, the correction the
client clock had applied when it was taken, and when. Two fixes over a plain minimum-RTT window:

(a) Corrections applied since are removed from the stored offset, so every candidate reads as the
    offset the client would measure NOW:   offset_now = offset - (correction_now - correction_then).
    Optionally the oscillator's own drift since the sample is removed too (`drift_est_ppm`): once a
    loop has learned its frequency the corrections cancel the drift, and without this term an old
    sample would be wrong by drift * age. With drift_est_ppm = 0 (the default) it is exactly (a).

(b) Samples are ranked by  rtt/2 + age * phi  (ms), not by RTT alone. rtt/2 is the most an offset can
    be wrong when the delay is all on one side; age * phi is how far the clock may have wandered
    since. A low-RTT sample that is many polls old therefore loses to a fresher one with a slightly
    higher RTT, but still wins when the RTT difference is large (queueing).

phi is the assumed oscillator frequency tolerance in ppm. NTP's dispersion growth uses 15 ppm, which
suits a good crystal; here the injected drift is 50 ppm, so the default is 100 ppm (twice the largest
drift we inject). It is chosen from that assumption, not tuned until a bound passes. If the real
drift exceeds phi, stale samples are trusted more than they deserve.
"""
from collections import deque

DEFAULT_WINDOW = 8
DEFAULT_PHI_PPM = 100.0


def adjusted_offset_ms(offset_ms, corr_then_ns, corr_now_ns, age_ns, drift_est_ppm=0.0):
    """The offset (server - client, ms) a sample would show now.  drift_est_ppm > 0: the client oscillator
    runs fast, so the offset keeps falling by drift * age."""
    return offset_ms - (corr_now_ns - corr_then_ns) / 1e6 - drift_est_ppm * 1e-6 * age_ns / 1e6


class AgeFilter:
    def __init__(self, window=DEFAULT_WINDOW, phi_ppm=DEFAULT_PHI_PPM):
        self.window = window
        self.phi_ppm = float(phi_ppm)
        self._s = deque(maxlen=window)          # (rtt_ms, offset_ms, corr_ns, t_ns)

    def __len__(self):
        return len(self._s)

    def add(self, rtt_ms, offset_ms, corr_ns, t_ns):
        self._s.append((rtt_ms, offset_ms, corr_ns, t_ns))

    def best(self, corr_now_ns, t_now_ns, drift_est_ppm=0.0):
        """The best candidate now: {rtt_ms, offset_ms (adjusted), age_s, rank_ms}. None if empty. Ties go to the newest."""
        best = None
        for rtt, off, corr, t in self._s:
            age_ns = t_now_ns - t
            rank = rtt / 2 + (age_ns / 1e6) * self.phi_ppm * 1e-6
            if best is None or rank <= best["rank_ms"]:
                best = dict(rtt_ms=rtt, rank_ms=rank, age_s=age_ns / 1e9,
                            offset_ms=adjusted_offset_ms(off, corr, corr_now_ns, age_ns, drift_est_ppm))
        return best
