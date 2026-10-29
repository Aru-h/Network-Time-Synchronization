"""
NTP-style clock filter: of the last N (default 8) samples, trust the offset of the
one with the smallest round-trip delay. Queueing delay is mostly one-directional, so
a high-RTT sample carries a large offset error and a low-RTT sample carries little.
"""
import statistics

WINDOW = 8


def min_rtt_filter(samples, window=WINDOW):
    """samples: list of (rtt_ms, offset_ms) in arrival order. Returns the filtered
    offset for every full window (len(samples) - window + 1 values)."""
    out = []
    for i in range(window, len(samples) + 1):
        win = samples[i - window:i]
        # ties go to the newest sample
        best = min(reversed(win), key=lambda s: s[0])
        out.append(best[1])
    return out


def compare(samples, expected_offset_ms, window=WINDOW):
    """Mean absolute offset error of the raw samples vs the min-RTT-filtered estimates.
    Returns None when there are fewer samples than the window."""
    if len(samples) < window:
        return None
    raw = [abs(o - expected_offset_ms) for _, o in samples]
    filt = [abs(o - expected_offset_ms) for o in min_rtt_filter(samples, window)]
    raw_mean, filt_mean = statistics.mean(raw), statistics.mean(filt)
    return dict(n_raw=len(raw), n_filtered=len(filt), window=window,
                raw_mean_ms=raw_mean, filtered_mean_ms=filt_mean,
                reduction_pct=(100.0 * (raw_mean - filt_mean) / raw_mean) if raw_mean > 0 else 0.0)
