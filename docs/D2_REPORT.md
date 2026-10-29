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

Numbers below are from `evaluation/results/actual_sdn_results/` (run 2) and, where stated, from
`evaluation/results/repeat_run/SUMMARY_run1.txt` (run 1). Each cell is a mean of 20 samples from h2 (skew +100 ms).

**Without QoS the load builds a queue on the sync path.** With 30 Mbit offered on the 20 Mbit link, iperf delivered 19.4 Mbit/s with
0 loss, so the sender was held back and the queue stood in front of h1. Sync RTT rose from 0.14 ms (P1) to 42.65 ms (P3b, QoS off)
and from 50.83 ms (P2) to 97.15 ms (P4, QoS off). The controller had already moved sync flows to priority 200, so OpenFlow priority
alone did not protect sync: it orders flow lookups, not egress queueing.

**With the sync queue the RTT returns to its unloaded value.** P3b QoS on: 0.03 ms. P4 QoS on: 50.09 ms, against 50.83 ms for the
delay-only P2. At the dump, class 1:1 (load) held a backlog of 74 packets while class 1:2 (sync) held none, so the load was still
saturating the bottleneck in the QoS-on legs and the sync packets bypassed its queue.

**Offset error follows the one-way queue.** Only the request direction (s1 to h1) queues, so the offset error is about half the queue
delay: 21.31 ms (QoS off, P3b) and 23.52 ms (P4) fall to 0.007 ms and 0.012 ms with QoS on. The second client h3 (skew -50 ms) behaves
the same way: P3b 21.30 ms off, 0.008 ms on.

**Two runs agree closely.** Run 1 versus run 2 mean sync RTT: P3b QoS off 42.19 / 42.65 ms, QoS on 0.024 / 0.027 ms; P4 QoS off
95.66 / 97.15 ms, QoS on 50.10 / 50.09 ms. The largest difference is 1.5 ms (P4 QoS off).

**The min-RTT filter helps a little under queueing.** Over 8-sample windows it lowered the mean error by 10% / 11% (P3b, run 1 / run 2)
and 23% / 25% (P4, QoS off), from 21.31 to 19.04 ms and from 23.52 to 17.69 ms in run 2. A standing queue delays most samples in
the window alike, so choosing the smallest RTT cannot remove it. The large percentages in the unloaded and QoS-on rows are from
errors that are already below 0.05 ms.

### Limits of these results

- **Two runs of 20 samples each.** Run-to-run spread beyond these two runs is unknown.
- **Which QoS setting did the work was not isolated.** The result is for the whole configuration: a separate class for sync, a
  higher OVS queue priority, and a 2 Mbit minimum rate. No run changed one of these alone.
- **Mininet's shaper is a software token bucket.** The sub-millisecond QoS-on RTT (0.03 ms) reflects that shaper and the
  hosts' virtual links, not a physical link. No one-frame transmission floor is claimed as a result.
- **Kernel timestamps:** on loopback the gain over user-space timestamps was under a microsecond, so it is negligible here. It was not
  measured across the Mininet path.
- **Min-RTT filter:** as above, about 10-11% (P3b) and 23-25% (P4) because a standing queue cannot be filtered away.
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
