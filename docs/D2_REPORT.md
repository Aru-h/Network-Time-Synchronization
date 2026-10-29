# Network Time Synchronization over SDN: D2 Report

All tables between `GEN` markers are written by `evaluation/code/fill_report.py` from the files in
`evaluation/results/actual_sdn_results/`. A row that says `pending` has no result file yet; no number here is typed by hand.

## 1. Scope

D1 (moved to `sandbox/d1/`) was a socket/SDN prototype. D2 adds measured behaviour under delay, congestion and failure,
a controller that reacts to congestion, and an OpenFlow-to-queue path (QoS) that protects the sync traffic.

## 2. System

- **Server** (h1, `10.0.0.1:5000`) and **clients** (h2 skew +100 ms, h3 skew -50 ms): four-timestamp exchange,
  `REQ|seq|T1` / `REP|seq|T1|T2|T3`. T2 (server) and T4 (client) are kernel receive timestamps (`SO_TIMESTAMPNS`); every
  fallback to user-space time is counted and printed. The client keeps reading until a per-sample deadline so a late reply
  to an earlier request does not cost the next sample.
- **Topology:** h1 on a 20 Mbit link (the bottleneck), h2/h3/h4 on 100 Mbit. Load goes h4 to h1 UDP/6000 and shares the
  `s1 -> h1` egress queue with the sync requests.
- **Controller** (`controller/d2_adaptive_controller.py`): learning switch; sync flows (UDP/5000) at priority 100;
  congestion detected from OpenFlow port 1 only (enter at 15 Mbit/s, leave after 2 polls at or below 8 Mbit/s); on detection it
  pushes priority 200 at once and reverts when the load clears. With `D2_QOS=on`, sync flows toward port 1 carry `set_queue:1`.
- **QoS** (`mininet/d2_qos.py`): OVS linux-htb on `s1-eth1`, total 20 Mbit; queue 0 default, queue 1 for sync with a 2 Mbit
  minimum and higher priority. Host-side shaping is untouched, so netem still works.

## 3. Results

Environment:

<!-- GEN:environment -->
```text
netem_available=True
ovs_datapath=kernel
ovs=ovs-vsctl (Open vSwitch) 3.7.1
load_tool=iperf
bottleneck_mbps(h1 link)=20
edge_mbps(h2,h3,h4 links)=100
under_load_mbps=10
over_load_mbps=30
python=3.14.4
ryu_manager=/home/seed/topic23-venv/bin/ryu-manager
```
<!-- /GEN:environment -->

### 3.1 Per-test performance

<!-- GEN:performance -->
| Test | Condition | Client | Skew | Samples OK | Avg RTT (ms) | Max RTT (ms) | Avg offset (ms) | Mean abs error (ms) | Timeouts |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | Normal | h2 | +100 ms | 20/20 | 0.22 | 1.73 | -99.96 | 0.045 | 0 |
| P1b | Normal, second client | h3 | -50 ms | 20/20 | 0.17 | 1.21 | +50.03 | 0.034 | 0 |
| P2 | 50 ms delay (25 ms on h1 and h2) | h2 | +100 ms | 20/20 | 51.87 | 53.65 | -100.06 | 0.540 | 0 |
| P3a | Load 10 Mbit (under capacity) | h2 | +100 ms | 20/20 | 0.10 | 0.59 | -99.97 | 0.030 | 0 |
| P3b | Load 30 Mbit offered, QoS off | h2 | +100 ms | 20/20 | 42.38 | 55.84 | -78.82 | 21.176 | 0 |
| P3b | Load 30 Mbit offered, QoS on | h2 | +100 ms | 20/20 | 0.03 | 0.07 | -99.99 | 0.006 | 0 |
| P3b-h3 | Same run, second client, QoS off | h3 | -50 ms | 20/20 | 42.39 | 55.81 | +71.18 | 21.184 | 0 |
| P3b-h3 | Same run, second client, QoS on | h3 | -50 ms | 20/20 | 0.03 | 0.07 | +50.01 | 0.008 | 0 |
| P4 | Load + 50 ms delay, QoS off | h2 | +100 ms | 20/20 | 95.96 | 101.87 | -77.10 | 22.897 | 0 |
| P4 | Load + 50 ms delay, QoS on | h2 | +100 ms | 20/20 | 50.10 | 50.23 | -100.00 | 0.011 | 0 |
| P5 | Server down | h2 | +100 ms | 0/20 | - | - | - | - | 20 |
| P6 | Server restarted | h2 | +100 ms | 20/20 | 0.10 | 0.27 | -99.98 | 0.024 | 0 |
<!-- /GEN:performance -->

### 3.2 Baseline versus SDN-controlled (QoS off versus on)

"Baseline" is the same load with the controller's priority policy but no queue (QoS off); "SDN-controlled" adds the
QoS queue and `set_queue` (QoS on). Same load, same client, same run.

<!-- GEN:qos -->
| Scenario | Unloaded reference (ms) | Sync RTT, QoS off (ms) | Sync RTT, QoS on (ms) | Change (ms) | Offset error off -> on (ms) |
|---|---:|---:|---:|---:|---:|
| Load over capacity (P3b) | 0.22 | 42.38 | 0.03 | -42.36 | 21.176 -> 0.006 |
| Load + delay (P4) | 51.87 | 95.96 | 50.10 | -45.85 | 22.897 -> 0.011 |
<!-- /GEN:qos -->

Verdicts printed by the runner:

<!-- GEN:verdicts -->
```text
P1_baseline      PASS
P1b_baseline_h3  PASS [mean offset +50.03 ms for skew -50 ms]
P2_delay         DELAY ACHIEVED [avg RTT 51.87 ms vs baseline 0.22 ms]
P3a_load_under   CONTROL OK - no congestion, as expected [avg RTT 0.10 ms = -0.12 ms over P1 baseline (0.22 ms), 0.5x; gate: added >= 5 ms; 2x ratio (info only): NOT MET]
P3b_load_over_qosoff CONGESTION ACHIEVED [avg RTT 42.38 ms = +42.16 ms over P1 baseline (0.22 ms), 189.8x; gate: added >= 5 ms; 2x ratio (info only): MET]
P4_load_delay_qosoff CONGESTION ACHIEVED [avg RTT 95.96 ms = +44.09 ms over P2 delay-only baseline (51.87 ms), 1.9x; gate: added >= 5 ms; 2x ratio (info only): NOT MET]
P5_recovery_down PASS
P6_recovery_up   PASS
QOS_setup        PASS [qos linux-htb on s1-eth1: default q0, sync q1 min 2000000 bps, total 20000000 bps]
P3b_load_over_qoson MEASURED [avg RTT 0.03 ms = -0.20 ms over P1 baseline (0.22 ms)]
QOS_verdict_P3b  QOS EFFECTIVE [sync RTT QoS off 42.38 ms -> QoS on 0.03 ms (+42.36 ms), -0.20 ms over P1 baseline (0.22 ms)]
P4_load_delay_qoson MEASURED [avg RTT 50.10 ms = -1.76 ms over P2 delay-only baseline (51.87 ms)]
QOS_verdict_P4   QOS EFFECTIVE [sync RTT QoS off 95.96 ms -> QoS on 50.10 ms (+45.85 ms), -1.76 ms over P2 delay-only baseline (51.87 ms)]
```
<!-- /GEN:verdicts -->

### 3.3 Error reduction: mean versus NTP-style min-RTT filter (8 samples)

<!-- GEN:errors -->
| Test | OK samples | Mean RTT (ms) | Raw mean error (ms) | Min-RTT filtered error (ms) | Reduction |
|---|---:|---:|---:|---:|---:|
| P1_baseline | 20 | 0.22 | 0.045 | 0.013 | +70% |
| P1b_baseline_h3 | 20 | 0.17 | 0.034 | 0.006 | +81% |
| P2_delay | 20 | 51.87 | 0.540 | 0.046 | +92% |
| P3a_load_under | 20 | 0.10 | 0.030 | 0.008 | +75% |
| P3b_load_over_qosoff | 20 | 42.38 | 21.176 | 18.916 | +11% |
| P3b_load_over_qoson | 20 | 0.03 | 0.006 | 0.002 | +59% |
| P3b_load_over_qosoff_h3 | 20 | 42.39 | 21.184 | 18.932 | +11% |
| P3b_load_over_qoson_h3 | 20 | 0.03 | 0.008 | 0.004 | +51% |
| P4_load_delay_qosoff | 20 | 95.96 | 22.897 | 17.903 | +22% |
| P4_load_delay_qoson | 20 | 50.10 | 0.011 | 0.005 | +54% |
| P6_recovery_up | 20 | 0.10 | 0.024 | 0.011 | +55% |
<!-- /GEN:errors -->

## 4. Reading the results

Numbers below are from `evaluation/results/actual_sdn_results/` (run 2, committed with this report) and from
`evaluation/results/repeat_run/SUMMARY_run1.txt` (run 1, an earlier run of the same runner whose per-sample files were not
kept). Each cell is the mean of 20 samples from h2 (skew +100 ms). There are two runs only.

**Without QoS the load builds a queue on the sync path.** With 30 Mbit offered on the 20 Mbit link, the iperf server received
19.4 Mbit/s with 0.0% loss in both runs, so the sender was held back by the link and a queue stood in front of h1. Sync RTT rose
from 0.22 ms (P1) to 42.38 ms (P3b, QoS off) and from 51.87 ms (P2, delay only) to 95.96 ms (P4, QoS off); run 1 gave 0.12 to
42.19 ms and 50.73 to 95.66 ms. In run 2 the controller had already moved the sync flows to priority 200 in these legs
(`assertions_P3b_load_over_qosoff.txt`: 4 priority=200 UDP/5000 flows present under load), so OpenFlow priority alone did not
protect sync: it orders flow lookups, not egress queueing.

**With the sync queue the RTT is back at or below the unloaded values.** Sync RTT with QoS on was 0.027 ms in P3b and 50.10 ms in
P4 (run 1: 0.024 and 50.10). For P4 that is 1.76 ms below the delay-only P2 (51.87 ms; run 1: 0.63 ms below 50.73 ms). For P3b it is
below the unloaded P1 (0.22 ms; run 1: 0.12 ms); that QoS-on sync RTT is lower than the unloaded RTT is observed and not explained
here. At the dump (run 2) class 1:1 (load) held a backlog of 65 packets in P3b and 83 in P4 while class 1:2 (sync) held none, having
sent 43 and 63 packets, so the load was still saturating the bottleneck in the QoS-on legs and sync packets did not wait behind it.

**Offset error follows the one-way queue.** Only the request direction (s1 to h1) queues, so the offset error is about half the RTT
increase: P3b 21.18 ms and P4 22.90 ms with QoS off fall to 0.006 ms and 0.011 ms with QoS on (run 1: 21.08 to 0.005 and 22.78 to
0.013). The second client h3 (skew -50 ms) behaves the same way in P3b: 21.18 ms off, 0.008 ms on (run 1: 21.26 and 0.008).

**The two runs agree closely on the loaded legs and less closely on the unloaded ones.** Run 1 against run 2, mean sync RTT in ms:
P3b QoS off 42.19 / 42.38, QoS on 0.024 / 0.027; P4 QoS off 95.66 / 95.96, QoS on 50.10 / 50.10. The unloaded legs vary more in relative
terms: P1 0.122 / 0.223 ms (1.8 times) with mean offset error 0.026 / 0.045 ms, and P2 50.73 / 51.87 ms with offset error
0.199 / 0.540 ms (2.7 times). The largest absolute difference between the runs is 1.14 ms (P2); the QoS-off loaded legs differ by
0.20 and 0.30 ms. With two runs this is not a variance estimate.

**The min-RTT filter helps a little under queueing.** Over 8-sample windows it lowered the mean offset error by 11% in P3b
(21.18 to 18.92 ms) and by 22% in P4 (22.90 to 17.90 ms), in run 2 only: run 1's per-sample files were not kept, so its reduction is not
quoted. A standing queue delays most samples in the window alike, so choosing the smallest RTT cannot remove it. The large percentages
in the unloaded and QoS-on rows (51% to 92%) come from errors of at most 0.54 ms.

### Limits of these results

- **Two runs of 20 samples each.** The unloaded legs differ between them by up to 1.8 times (P1 RTT) and 2.7 times (P2 offset error);
  run-to-run spread beyond these two runs is unknown.
- **Which QoS setting did the work was not isolated.** The result is for the whole configuration: a separate class for sync, a
  higher OVS queue priority, and a 2 Mbit minimum rate. No committed run changed one of these alone.
- **Mininet's shaper is a software token bucket.** The sub-millisecond QoS-on RTT (0.027 ms) reflects that shaper and the
  hosts' virtual links, not a physical link. No one-frame transmission floor is claimed as a result.
- **Kernel timestamps:** the loopback test (`tests/test_kernel_timestamps.py`) did not show a meaningful gain over user-space
  timestamps; it prints both medians but they are not stored in a result file, so no figure is quoted. The gain was not measured
  across the Mininet path.
- **Min-RTT filter:** about 11% (P3b) and 22% (P4) in run 2, because a standing queue cannot be filtered away.
- **One bottleneck, one switch, one queued port** (toward h1); the load and the reverse direction were not queued differently.

## 5. Replay page

`evaluation/code/build_replay.py` writes `replay.html` next to the results: sync RTT and offset error with QoS off versus on,
the controller policy timeline and the flow table with priorities. It is one offline file.

## 6. Reproducing

`sudo ./run_d2.sh` (see `evaluation/docs/EVALUATION_COMMANDS.md`). Needs Ubuntu, Mininet, Open vSwitch, Ryu, iperf.

## 7. Limitations

- Educational prototype, not production NTP; no clock is disciplined.
- 20 samples per test and one run per condition: run-to-run variation is not measured.
- One bottleneck, one switch, one QoS port; the queue protects sync only toward h1.
- Congestion detection is a rate threshold on port 1 with fixed values; the QoS minimum rate and queue priority were not tuned.
- Only the request direction queues, so the offset error under load is asymmetry, not noise; the min-RTT filter reduces it a
  little when some samples see a shorter queue and cannot remove a standing queue.
- Kernel timestamps remove user-space wake-up delay only; on loopback this was under a microsecond.
