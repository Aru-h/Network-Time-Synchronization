# Sync loop: a client that corrects its own clock

A client keeps a **software clock** (the OS clock is never touched), measures its offset against the unchanged time
server (`REQ|seq|T1` / `REP|seq|T1|T2|T3`, kernel receive stamps), and disciplines the soft clock with a step or a slew.
This is a small teaching sync loop, **not NTP**: one server, no peer selection, no authentication, no leap handling.

Files: `server_client/softclock.py`, `server_client/sync_loop.py`, `server_client/agefilter.py`; runner
`evaluation/ubuntu_runner/run_sync_loop.sh`; checks `evaluation/code/sync_loop_check.py`; this page is written by
`evaluation/code/make_sync_loop_doc.py` from the result files.

## Two caveats that apply to every number below

1. **Shared clock.** `true_error` (the soft clock minus real time) can be logged only because every Mininet host shares one
   kernel clock, so "real time" is the server's reference too. On separate machines this number would not exist; a real
   client sees only its own offset estimate. The checks below use it as ground truth.
2. **S1 is a demo setting.** The step threshold follows real NTP (128 ms): an offset below it is never stepped. A 100 ms
   skew is then removed by slewing alone, which at the realistic cap of 500 ppm takes about 200 s. S1 runs with
   `--max-slew-ppm 5000` so it converges inside a test; that is **not realistic NTP behaviour**. Every other leg uses the
   default 500 ppm.

## How it works

- **Discipline.** If `|filtered_offset| > --step-ms` (128) the clock is stepped once. Otherwise it is slewed only: a PI
  controller turns the filtered offset into a rate (ppm), clamped to `--max-slew-ppm`, so the clock never goes backwards
  while slewing (it runs at 1 + (drift + rate) x 1e-6 > 0 times real time). A step moves the clock back by design and is
  reported separately (the `stepped` column).
- **Frequency estimate.** The PI integral term settles near minus the oscillator drift. Anti-windup: it is clamped to the
  rate cap, is not accumulated while the output is saturated in the direction of the error, and is accumulated only while
  `|offset| < 2 ms` (integral separation). The last rule was added after the unit tests showed that integrating during
  the approach from a 100 ms offset overshoots by about 2 ms and takes tens of seconds to unwind.
- **Filter** (`agefilter.py`): the last 8 samples, each offset corrected for the adjustments applied since it was taken,
  ranked by `rtt/2 + age x phi`. phi = 100 ppm by default: the assumed oscillator tolerance, twice the largest drift
  injected (50 ppm). It is a stated assumption, not a value tuned until a bound passed. NTP's 15 ppm assumes a good crystal.
- **CSV** per poll: `t, offset_est, rtt, filtered_offset, correction, rate_ppm, true_error, stepped` (+ `status,
  filtered_rtt, backwards`).

## Root cause of the drift failure

An earlier version used a plain minimum-RTT window. With a 50 ppm drift its steady error reached 0.43 ms against a bound
of 0.09 to 0.15 ms in two Mininet runs (their result files were not committed; the code is on the local branch
`d2-stretch-v1`). It reproduces in simulation
(`tests/repro_drift_staleness.py`, 200 seeds, polls once a second, independent random delay per direction):

| Filter variant | phi (ppm) | Mean worst steady \|error\| (ms) | Mean steady \|error\| (ms) | Legs over the bound |
|---|---:|---:|---:|---:|
| min-RTT, offsets NOT corrected for adjustments (cause a) | 0 | 2.739 | 1.023 | 200/200 |
| min-RTT, offsets corrected (the failing case, cause b) | 0 | 0.407 | 0.224 | 200/200 |
| age-ranked, corrected | 15 | 0.176 | 0.075 | 200/200 |
| age-ranked, corrected | 50 | 0.117 | 0.055 | 177/200 |
| age-ranked, corrected | 100 | 0.114 | 0.052 | 38/200 |
| age-ranked, corrected, + drift estimate | 100 | 0.112 | 0.051 | 0/200 |

Cause: the window kept returning an old low-RTT sample. Its stored offset ignored the corrections applied since it was
taken (cause a: far worse), and even when corrected, nothing penalised its age, so the clock kept being steered by a
sample that was several seconds old while the oscillator moved about 0.05 ms per second (cause b). Ranking by
`rtt/2 + age x phi` and correcting stored offsets fixes both once the controller can learn the drift; with a simple
proportional controller alone, ranking helps but does not meet the bound at any phi tried.

## Results

Pass bound, computed from each run: over the steady state (second half of the OK polls) every poll must satisfy
`|true_error| <= filtered_RTT/2 + drift x poll`. **`filtered_RTT` is the one from the previous poll**: the error logged at
poll i was set by the discipline of poll i-1, so that is the estimate whose uncertainty bounds it. The bound is printed,
never relaxed. Missing data is SKIP, never PASS. S4 is report-only (the constant queue asymmetry puts its error at about
RTT/2, right on the bound, and a min-RTT filter cannot remove it); S5 is PASS/FAIL plus the check that S5's error is below S4's.

### run1

| Leg | Setting | Role | Steps (expected) | Backwards | First-poll error (ms) | Steady mean \|error\| (ms) | Steady max \|error\| (ms) | Bound max (ms) | Polls over bound | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| S1_slew | skew 100 ms, slew cap 5000 ppm (DEMO), 120 s | PASS/FAIL | 0 (0) | 0 | 100.0 | 0.0315 | 0.0544 | 0.1350 | 1/60 | FAIL |
| S2_step | skew 500 ms, cap 500 ppm, 60 s | PASS/FAIL | 1 (1) | 0 | 500.0 | 0.0387 | 0.0459 | 0.1497 | 0/30 | PASS |
| S3_drift | 50 ppm drift, 60 s | PASS/FAIL | 0 (0) | 0 | 0.0 | 0.0384 | 0.0675 | 0.1817 | 0/30 | PASS |
| S3f_drift_freq | 50 ppm drift, --freq-compensate, 60 s | report only | 0 (0) | 0 | 0.0 | 0.0421 | 0.0682 | 0.1742 | 0/30 | INFO |
| S4_load_qosoff | 30 Mbit load, QoS off, skew 500 ms, 90 s | report only | 1 (1) | 0 | 500.0 | 15.9644 | 18.0385 | 18.0430 | 16/45 | INFO |
| S5_load_qoson | 30 Mbit load, QoS on, skew 500 ms, 90 s | PASS/FAIL | 1 (1) | 0 | 500.0 | 0.0080 | 0.0128 | 0.0384 | 0/45 | PASS |

S5 < S4 check: PASS (steady mean |true_error| QoS on 0.0080 ms vs QoS off 15.9644 ms (max 0.0128 vs 18.0385 ms)).
Counts: PASS 4, FAIL 1, SKIP 0, report-only 2.

### run2

| Leg | Setting | Role | Steps (expected) | Backwards | First-poll error (ms) | Steady mean \|error\| (ms) | Steady max \|error\| (ms) | Bound max (ms) | Polls over bound | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| S1_slew | skew 100 ms, slew cap 5000 ppm (DEMO), 120 s | PASS/FAIL | 0 (0) | 0 | 100.0 | 0.0242 | 0.0404 | 0.1257 | 0/60 | PASS |
| S2_step | skew 500 ms, cap 500 ppm, 60 s | PASS/FAIL | 1 (1) | 0 | 500.0 | 0.0337 | 0.0458 | 0.1354 | 1/30 | FAIL |
| S3_drift | 50 ppm drift, 60 s | PASS/FAIL | 0 (0) | 0 | 0.0 | 0.0391 | 0.0688 | 0.1840 | 0/30 | PASS |
| S3f_drift_freq | 50 ppm drift, --freq-compensate, 60 s | report only | 0 (0) | 0 | 0.0 | 0.0434 | 0.0586 | 0.1865 | 0/30 | INFO |
| S4_load_qosoff | 30 Mbit load, QoS off, skew 500 ms, 90 s | report only | 1 (1) | 0 | 500.0 | 15.2103 | 16.2389 | 16.2408 | 17/45 | INFO |
| S5_load_qoson | 30 Mbit load, QoS on, skew 500 ms, 90 s | PASS/FAIL | 1 (1) | 0 | 500.0 | 0.0087 | 0.0129 | 0.0529 | 0/45 | PASS |

S5 < S4 check: PASS (steady mean |true_error| QoS on 0.0087 ms vs QoS off 15.2103 ms (max 0.0129 vs 16.2389 ms)).
Counts: PASS 4, FAIL 1, SKIP 0, report-only 2.

### Both filter variants, measured (S3 versus S3f)

| Run | Variant | Steady mean \|error\| (ms) | Steady max \|error\| (ms) | Bound max (ms) | Frequency estimate (ppm, true +50) |
|---|---|---:|---:|---:|---:|
| run1 | default (corrections only) | 0.0384 | 0.0675 | 0.1817 | +49.4 |
| run1 | --freq-compensate | 0.0421 | 0.0682 | 0.1742 | +49.8 |
| run2 | default (corrections only) | 0.0391 | 0.0688 | 0.1840 | +49.3 |
| run2 | --freq-compensate | 0.0434 | 0.0586 | 0.1865 | +49.8 |

In the sandbox the two variants were indistinguishable at phi = 100 ppm (the age ranking already keeps stale samples out), so
the drift term is an option and is off by default.

## What the failures mean

Each run has exactly one failing check, and it is a different idle leg each time (see the tables). On the idle legs the
bound is only a few hundredths of a millisecond and the steady error sits at about 0.03 ms (the path's own request/reply
asymmetry), so one poll in 30 to 60 occasionally lands a few microseconds over it. That is noise at the bound's resolution,
not a loop failure: the clock stays within about 0.05 ms of real time on those legs. The bound was not relaxed; a
criterion with a few-microsecond margin on idle legs will keep flagging such single polls.

## Limitations

- Two runs, 20 to 120 polls per leg; the spread beyond these two runs is unknown.
- One server, one path, one bottleneck; the loop is not robust to a lying or failed server.
- `true_error` exists only because the hosts share a clock (caveat 1).
- The 5000 ppm cap in S1 is a demo setting (caveat 2). At the realistic 500 ppm a 100 ms offset takes about 200 s.
- phi (100 ppm) is an assumption about the oscillator; a drift above it would make stale samples look better than they are.
- Mininet's shaper is a software token bucket, so sub-millisecond figures describe this emulation, not a physical link.
