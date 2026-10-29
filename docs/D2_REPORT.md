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
pending
<!-- /GEN:environment -->

### 3.1 Per-test performance

<!-- GEN:performance -->
pending
<!-- /GEN:performance -->

### 3.2 Baseline versus SDN-controlled (QoS off versus on)

"Baseline" is the same load with the controller's priority policy but no queue (QoS off); "SDN-controlled" adds the
QoS queue and `set_queue` (QoS on). Same load, same client, same run.

<!-- GEN:qos -->
pending
<!-- /GEN:qos -->

Verdicts printed by the runner:

<!-- GEN:verdicts -->
pending
<!-- /GEN:verdicts -->

### 3.3 Error reduction: mean versus NTP-style min-RTT filter (8 samples)

<!-- GEN:errors -->
pending
<!-- /GEN:errors -->

## 4. Reading the results

Write this section after the final run, from the tables above: what the QoS-off legs show, what QoS changed, how the offset
error follows the one-directional queue (error is about half the request-direction queue delay), and what the min-RTT filter
does and does not help.

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
