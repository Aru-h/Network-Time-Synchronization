# Evaluation result status

Three result sets exist. They are **different experiments**; do not mix them in the report.

| Set | Folder | Environment | Status |
|---|---|---|---|
| A (primary) | `results/actual_sdn_results/` | Ubuntu VM: Mininet + Ryu + **kernel** Open vSwitch 3.7.1, netem available | the results to report |
| B | `results/local_socket_level/` | earlier plain-socket (loopback) results, no SDN | different experiment |
| C | not committed | earlier sandbox run (see "Earlier sandbox run" below) | superseded, kept only as a note |

Everything below is a value read from the committed files. Where something could not be verified, it says so.

## A. `results/actual_sdn_results/` - Ubuntu VM run (2026-10-27)

Environment (`environment.txt`): kernel OVS datapath, `ovs-vsctl` 3.7.1, netem available, `iperf` as load tool,
Python 3.14.4, h1 link = 20 Mbps (the bottleneck), h2/h3/h4 links = 100 Mbps. iperf on the VM reports
`iperf version 2.2.1 (4 Nov 2024)` (printed by `diagnose_load_rate.py`). This run used the current runner (htb `r2q 100`,
so no `sch_htb: quantum ... is big` warnings appeared) and the D2 controller with both fixes (`b437d0a`, `e116e38`).
It replaces an earlier VM run made before those changes; see "Previous VM run" at the end of this section.

### Per-test results (20 samples each, 20/20 returned unless stated)
| Test | Runner verdict | avg RTT (ms) | mean abs offset error (ms) | Notes |
|---|---|---|---|---|
| P1 baseline | PASS | 0.111 | 0.015 | first sample 1.371 ms, other 19 average 0.044 ms |
| P2 delay (25 ms netem on h1 and h2) | DELAY ACHIEVED | 51.379 | 0.207 | 464.4x P1 |
| P3a control, 10 Mbit/s load | CONTROL OK | 0.026 | 0.004 | no queue: `backlog 0b 0p`; load received 10.5 Mbit/s, 0/3,595 lost |
| P3b overload, nominal 30M load | CONGESTION ACHIEVED | 42.661 (33.0-56.0) | 21.285 | +42.55 ms over P1 |
| P4 load + delay | CONGESTION ACHIEVED | 95.876 (83.2-102.0) | 22.895 | +44.50 ms over the P2 delay-only RTT (1.9x, so the old 2x rule would still have failed it) |
| P5 server down | PASS | - | - | 0/20 returned, as expected |
| P6 server restarted | PASS | 0.027 | 0.005 | 20/20 |

No sync request was lost in any loaded test (20/20 in P3a, P3b, P4). P3a and P6 average below P1 because P1's first
sample (1.371 ms) dominates its average; the cause of that first-sample cost was not isolated.

### The load: nominal 30M, measured about 19.5 Mbit/s
The runner starts the overload as `iperf -u -b 30M -l 1470`, but the iperf client logs show the sender sent
**about 19.5 Mbit/s**:

| | datagrams sent (client) | duration | client rate | received by server | lost |
|---|---|---|---|---|---|
| P3b | 8,132 | 4.888 s | 19.6 Mbit/s | 8,131 (19.4 Mbit/s) | 0 (0 %) |
| P4 | 9,896 | 5.955 s | 19.5 Mbit/s | 9,895 (19.4 Mbit/s) | 0 (0 %) |

(The 1-datagram difference between sent and received was not investigated; both server logs also print
`WARNING: ack of last datagram failed.`)

So the overload is best described as: a load that **saturates the 20 Mbps bottleneck** and builds a queue (queueing
delay), **without loss**. Do not describe P3b/P4 as packet loss or as "30 Mbps offered"; 30M is only the requested rate.
The load flow counter at the P3b dump was 17,369,856 B / 11,488 packets (1,512-byte frames).

The queue is visible in `tc -s qdisc show dev s1-eth1` (the bottleneck egress) during the load, with `dropped 0`:
- P3b: backlog 57 packets / 86,184 B = about 34.5 ms at 20 Mbps (measured sync RTT increase over P1: 42.55 ms).
- P4: backlog 62 packets / 93,744 B = about 37.5 ms (measured RTT increase over P2: 44.50 ms).

The backlog is a single snapshot taken during the load, so it need not match the average RTT increase exactly.

**Why the sender stays at about 19.5 Mbit/s: narrowed down, mechanism not verified.** `diagnose_load_rate.py` was run on
the VM on 2026-10-27 (terminal output, not committed; 5 s per case, 1470-byte datagrams, sender rate / server rate):

| case | target | requested | sender Mbit/s | server Mbit/s | lost |
|---|---|---|---|---|---|
| A | h3 | 10M | 10.49 | 10.50 | 0/4,460 |
| B | h3 | 30M | 31.46 | 31.50 | 0/13,377 |
| C | h1 | 10M | 10.49 | 10.50 | 0/4,461 |
| D | h1 | 30M | 19.45 | 19.40 | 0/8,319 |
| E | h3 | 60M | 62.92 | 62.90 | 0/26,752 |

The same iperf reaches 30M and 60M on a path without the 20 Mbps link (B, E), so this is not an iperf pacing limit.
It stops at about 19.5 Mbit/s only when the path goes through the h1 bottleneck (D), and nothing is lost there. That fits a
sender that is held back by the full bottleneck queue rather than one that overruns it; how that back-pressure reaches
the sender was not examined.

### Two different offset-error behaviours, and why
Offset = ((T2-T1)+(T3-T4))/2 = true offset + (d1-d2)/2, where d1 is the one-way delay of the request (client -> server)
and d2 of the reply. The error is therefore half the *asymmetry*, not half the total delay.

- **P2 (delay only): error 0.207 ms.** netem adds 25 ms on h1 and 25 ms on h2, so the request (leaves h2) and the reply
  (leaves h1) each get +25 ms. d1 ~ d2, the asymmetry cancels, RTT rises by 51.3 ms but the offset stays at -99.946 ms
  against the expected -100 ms.
- **Load (P3b): error 21.285 ms ~ RTT/2.** The bottleneck queue is on the s1 -> h1 egress, which is the *request*
  direction (h2 -> h1). The reply goes h1 -> s1 on the other direction of the link and is not queued. So d1 ~ RTT and
  d2 ~ 0, and the error is about RTT/2. Measured |error| / (RTT/2) per sample: average 0.998 (range 0.997-0.999).
  Mean offset -78.715 ms against the expected -100 ms.
- **Load + delay (P4): error 22.895 ms.** The 50 ms symmetric part cancels (as in P2), the queueing part does not.
  Added RTT over the P2 delay-only run is 44.50 ms, so the expected error is about 44.50/2 = 22.25 ms; measured 22.895 ms
  (22.895 / 22.25 = 1.03). Mean offset -77.105 ms. Per-sample |error| / (RTT/2) is 0.476 (0.398-0.509) here, because the
  RTT also contains the symmetric 50 ms.

Consequence for the report: RTT inflation and offset error are separate. A symmetric delay barely hurts the offset; an
asymmetric queue hurts it by half its size.

### Congestion rule: added delay, not a ratio
The runner judges a loaded test as congested when its avg RTT is **at least 5 ms above** the matching unloaded baseline
(P1 for P3a/P3b, P2 for P4), and prints the old 2x ratio as "info only". The rule was changed after the previous VM run
flagged P4 "NO CONGESTION ACHIEVED" under the 2x rule (1.86x), although P4 had the same kind of queue as P3b (so treat the
change as post-hoc). Queueing delay adds to fixed delay; it does not multiply it, so a ratio punishes tests that already
contain 52 ms of fixed delay. Common practice for "does the load create a queue" is latency under load: loaded minus idle
RTT in ms, as in bufferbloat grading (under 5 ms is the best grade, 5-30 ms the next) and in flent's RRUL test, with a
standing queue of 5 ms or less treated as acceptable (CoDel's target, RFC 8289). The 5 ms value comes from those
references, not from the P4 numbers. The verdicts do not depend on its exact value: in this run the control sits at
-0.08 ms and the overload tests at +42.55 and +44.50 ms, so any gate from about 1 ms to about 40 ms gives the same verdicts.
This run's P4 is 1.9x its baseline, so under the old rule it would again have been "NO CONGESTION ACHIEVED".

### Priority: no protection observed
- The controller **logged** `traffic high ... sync priority policy = 200` 11 times in the whole run
  (`policy_lines_all.txt`, against 28 `normal` readings); 5 of them fall inside the test windows (P3a 1, P3b 2, P4 2;
  `policy_P3a/P3b/P4_*.txt`), with no `normal` reading inside any window. The log no longer alternates `high` with a
  ~0-byte `normal` reading (the double-poll bug, see below, is fixed).
- **No flow with priority 200 appears in any evidence file** (`grep priority=200` over all `*.txt`: no match). The only
  sync flows the controller installed in the run are two priority-100 flows (`DYNAMIC SYNC FLOW` x2 in
  `ryu_controller.log`). With the fixed controller this is expected: a sync flow is (re)installed with the current
  policy only on a packet-in, and the runner's sync flows (`idle_timeout=20`) never expire before the load starts.
- The sync flows (priority 100) and the load flow (priority 10) both have `actions=output:1`: same port, same
  htb FIFO queue; the controller uses no set-queue action, meter or DSCP. Priority only selects the flow-table entry;
  it does not reorder packets in the egress queue.
- Result: the sync traffic waited in the same queue as the load (avg RTT 0.111 ms in P1 -> 42.661 ms in P3b). **No
  protection was observed.** Note that no run without the sync-priority rule exists, so this is "no protection observed",
  not a measured difference against a no-priority baseline. Real protection would need OVS queues plus a set-queue action.
- The `high` threshold (1 MB per 2 s of rx+tx over all ports) also fired during the 10 Mbit/s control (P3a), which had
  no queue.

### D2 controller: two bugs found from the D2 demo output, fixed afterwards
Source: a terminal paste of a D2 demo on the VM (`d2_topology.py` + `d2_adaptive_controller.py`, hand-run clients; not
committed as files), then reproduced in the sandbox (userspace OVS, no netem, so RTTs there are small; single runs).
- **Stale "installed" cache.** The controller installed the two sync flows (`idle_timeout=20`) once and then skipped
  reinstalling, because `sync_keys` still said "installed". After the idle timeout nothing brought the flows back, so every
  later sync packet was a packet-in + packet-out. On the VM paste: the first client run (flows installed) averaged RTT
  4.94 ms / error 0.09 ms; the second run (after an idle gap, flows gone) 8.12 ms / 0.60 ms; the `dump-flows` taken after the
  load run showed no UDP/5000 flow at all. Sandbox: second run 3.26 ms vs 1.2 ms for the first. Fixed in `e116e38`
  (reinstall on every sync packet-in, as the D1 controller does).
- **Switch registered twice.** `state_change` ran while `dp.id` was still `None`, so the controller held the same datapath under
  keys `None` and `1` and sent two port-stats requests per 2 s cycle (sandbox: two requests 1 ms apart, `datapaths keys=[None, 1]`).
  The second reply's delta is ~0, which gives the `high`/`normal(0)` pairs, and `packet_in` read `last_stats` right after the
  ~0 reading, so it almost always saw "not congested". Fixed in `b437d0a`. The previous VM run's log shows the same pairs;
  the 2026-10-27 VM run (fixed controller) does not.
- **After both fixes:** a sync flow that had expired, followed by load, is reinstalled at **priority 200**. Seen in the
  sandbox and, on 2026-10-27, in a hand-run D2 demo on the VM (terminal output, not committed): after a 25 s idle gap and
  3000 pps of load, the log showed `DYNAMIC SYNC FLOW ... priority=200` and `dump-flows` two `priority=200` UDP/5000 flows.
  A flow that is still alive when the load starts stays at 100, because no packet-in happens to upgrade it. These fixes
  make the policy accurate; they add **no protection**: flow priority still does not reorder the egress queue.

### Controller and data plane
- Background UDP/6000 is forwarded in the data plane by a priority-10 flow (`in_port=4 ... tp_dst=6000`, 11,488
  packets in P3b by the time of the dump). Packets sent to the controller (`controller_pkts` in `SUMMARY.txt`):
  P3a 4, P3b 0, P4 3. The Ryu log has 49 lines and one `BACKGROUND TRAFFIC` entry.
- P1's first sample (1.371 ms vs 0.044 ms for the other 19) is consistent with the flow-install round trip, but the
  cause was not isolated.

### Previous VM run (before 2026-10-27, superseded)
The files committed before 2026-10-27 (see `git log -- evaluation/results/actual_sdn_results`) came from the same VM, made
with Mininet's default htb `r2q` (10) and the D2 controller before the two fixes. Its main numbers: P1 0.383 ms,
P2 51.983 ms, P3b 41.491 ms (+41.1 ms), P4 96.789 ms (+44.8 ms, flagged "NO CONGESTION ACHIEVED" by the old 2x rule),
offset errors P2 0.241 / P3b 20.609 / P4 23.237 ms, sender about 19.5 Mbit/s, 0 loss, and the policy log in
`high`/`normal(0)` pairs. A second VM run from that time exists only as terminal output (P3b +41.7 ms, P4 +45.0 ms).
Across these runs the loaded results agree to within about 1.5 ms of added delay; no further runs were made, so wider
run-to-run variation is unknown.

### Not verified
- How the bottleneck queue holds the iperf sender at about 19.5 Mbit/s (see "The load" above: the cap is shown, the
  mechanism is not).
- Whether sync traffic behaves differently without the priority-100 rule (no such run).
- The cause of the P1 first-sample outlier.

## B. `results/local_socket_level/` - earlier plain-socket (loopback) results, no SDN
Measurements of the Track A server + evaluator over loopback with a UDP delay proxy (P2/P4 ~50 ms RTT) and
background UDP load against the server socket. Mininet/OVS/Ryu were not involved and no bottleneck was verified. This is a
different experiment from set A, and its numbers must not be mixed with set A's.

## Earlier sandbox run (not committed, superseded by A)
A first end-to-end run was made in a different environment: OVS 3.3.9 **userspace** datapath, **no netem**, Python 3.13.
It is a different environment from A and is mentioned only so its numbers are not confused with A's. In it P2 and P4
were SKIPPED, and in P3b 10 of 20 sync requests timed out (50 % sync loss, surviving RTT about 56.6 ms; iperf server
loss 38 %). That loss did **not** appear on the VM (0/20 sync loss, 0 iperf loss). Possible reasons (userspace datapath
vs kernel datapath, queue behaviour, load rate: the sandbox sender sent about 31.5 Mbit/s) were not isolated.

No numbers in this document are estimated; every value comes from the committed files, except where a value is marked
as terminal output (not committed).
