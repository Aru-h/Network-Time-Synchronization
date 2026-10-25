# Evaluation result status

Three result sets exist. They are **different experiments**; do not mix them in the report.

| Set | Folder | Environment | Status |
|---|---|---|---|
| A (primary) | `results/actual_sdn_results/` | Ubuntu VM: Mininet + Ryu + **kernel** Open vSwitch 3.7.1, netem available | the results to report |
| B | `results/local_socket_level/` | earlier plain-socket (loopback) results, no SDN | different experiment |
| C | not committed | earlier sandbox run (see "Earlier sandbox run" below) | superseded, kept only as a note |

Everything below is a value read from the committed files. Where something could not be verified, it says so.

## A. `results/actual_sdn_results/` - Ubuntu VM run

Environment (`environment.txt`): kernel OVS datapath, `ovs-vsctl` 3.7.1, netem available, `iperf` as load tool,
Python 3.14.4, h1 link = 20 Mbps (the bottleneck), h2/h3/h4 links = 100 Mbps. The iperf version on the VM was not recorded.

### Per-test results (20 samples each, 20/20 returned unless stated)
| Test | Runner verdict | avg RTT (ms) | mean abs offset error (ms) | Notes |
|---|---|---|---|---|
| P1 baseline | PASS | 0.383 | 0.065 | first sample 1.524 ms, other 19 average 0.323 ms |
| P2 delay (25 ms netem on h1 and h2) | DELAY ACHIEVED | 51.983 | 0.241 | 135.8x P1 |
| P3a control, 10 Mbit/s load | CONTROL OK | 0.321 | 0.045 | no queue: `backlog 0b 0p`; load received 10.5 Mbit/s, 0 lost |
| P3b overload, nominal 30M load | CONGESTION ACHIEVED | 41.491 (29.3-50.8) | 20.609 | 108.4x P1 |
| P4 load + delay | **NO CONGESTION ACHIEVED** (see below) | 96.789 (84.5-101.3) | 23.237 | 1.9x the P2 delay-only RTT |
| P5 server down | PASS | - | - | 0/20 returned, as expected |
| P6 server restarted | PASS | 0.304 | 0.047 | 20/20 |

No sync request was lost in any loaded test (20/20 in P3a, P3b, P4).

### The load: nominal 30M, measured about 19.5 Mbit/s
The runner starts the overload as `iperf -u -b 30M -l 1470`, but the iperf client log (`P3b_load_over_load_client.log`)
shows the sender actually sent **about 19.5 Mbit/s**:

| | datagrams sent (client) | duration | received by server | lost |
|---|---|---|---|---|
| P3b | 8,180 | 4.93 s | 8,179 (19.4 Mbit/s) | 0 (0 %) |
| P4 | 9,992 | 6.01 s | 9,991 (19.4 Mbit/s) | 0 (0 %) |

(The 1-datagram difference between sent and received was not investigated; the P4 server log also prints
`WARNING: ack of last datagram failed.`)

So the overload is best described as: a load that **saturates the 20 Mbps bottleneck** and builds a queue (queueing
delay), **without loss**. Do not describe P3b/P4 as packet loss or as "30 Mbps offered"; 30M is only the requested rate.
At the frame level the load was about 20.1 Mbit/s (1512-byte frames, from the flow counters: 17,369,856 B / 11,488 packets),
i.e. right at the 20 Mbps link rate, which fits a queue that stays full but does not overflow.

The queue is visible in `tc -s qdisc show dev s1-eth1` (the bottleneck egress) during the load, with `dropped 0`:
- P3b: backlog 71 packets / 107,352 B = about 42.9 ms at 20 Mbps (measured sync RTT increase over P1: 41.1 ms).
- P4: backlog 78 packets / 117,936 B = about 47.2 ms (measured RTT increase over P2: 44.8 ms).

**Why the sender stayed at about 19.5 Mbit/s instead of 30M: not verified.** The client log says
`IPG target: 0.00 us`, but that banner is not diagnostic: it also appears in P3a, where the sender did reach its 10M target.
Possible causes (sender blocked by the full bottleneck queue on its path, or iperf-version pacing behaviour) were
not tested. Checking it needs `iperf --version` on the VM and a 30M run from h4 to a host that is not behind the
bottleneck (e.g. h3). That run was not made.

### Two different offset-error behaviours, and why
Offset = ((T2-T1)+(T3-T4))/2 = true offset + (d1-d2)/2, where d1 is the one-way delay of the request (client -> server)
and d2 of the reply. The error is therefore half the *asymmetry*, not half the total delay.

- **P2 (delay only): error 0.241 ms.** netem adds 25 ms on h1 and 25 ms on h2, so the request (leaves h2) and the reply
  (leaves h1) each get +25 ms. d1 ~ d2, the asymmetry cancels, RTT rises by 51.6 ms but the offset stays at -99.947 ms
  against the expected -100 ms.
- **Load (P3b): error 20.609 ms ~ RTT/2.** The bottleneck queue is on the s1 -> h1 egress, which is the *request*
  direction (h2 -> h1). The reply goes h1 -> s1 on the other direction of the link and is not queued. So d1 ~ RTT and
  d2 ~ 0, and the error is about RTT/2. Measured |error| / (RTT/2) per sample: average 0.993 (range 0.985-0.998).
  Mean offset -79.39 ms against the expected -100 ms.
- **Load + delay (P4): error 23.237 ms.** The 50 ms symmetric part cancels (as in P2), the queueing part does not.
  Added RTT over the P2 delay-only run is 44.8 ms, so the expected error is about 44.8/2 = 22.4 ms; measured 23.237 ms
  (23.237 / 22.4 = 1.04). Mean offset -76.76 ms. Per-sample |error| / (RTT/2) is 0.479 (0.404-0.503) here, because the
  RTT also contains the symmetric 50 ms.

Consequence for the report: RTT inflation and offset error are separate. A symmetric delay barely hurts the offset; an
asymmetric queue hurts it by half its size.

### P4 "NO CONGESTION ACHIEVED" - what it does and does not mean
The runner flags a loaded test as congested only if avg RTT >= 2x the matching unloaded baseline (and >= +1 ms).
For P4 the baseline is the P2 delay-only run (51.983 ms), so the bar is 103.97 ms. Measured 96.789 ms = **1.86x**, so
the flag is "NO CONGESTION ACHIEVED".

That flag comes from the threshold, not from an absence of queueing. The measured added delay is **44.8 ms**
(96.789 - 51.983), similar to P3b's 41.1 ms, the bottleneck backlog was 78 packets, and the offset error moved to
23.2 ms from 0.24 ms. A 2x ratio is simply harder to reach when the baseline is already 52 ms. The threshold was **not
changed**; P4 is reported with the verdict the runner produced. Read it as "queueing of about 45 ms was present;
the 2x rule was not met".

### Priority: no protection observed
- The controller **logged** `traffic high ... sync priority policy = 200` 11 times in the whole run
  (`policy_lines_all.txt`); 5 of them fall inside the test windows (P3a 1, P3b 2, P4 2; `policy_P3a/P3b/P4_*.txt`).
  The log alternates a `high` reading with a ~0-byte `normal` reading (cause not investigated).
- **No flow with priority 200 appears in any evidence file** (`grep priority=200` over all `*.txt`: no match). The only
  sync flows the controller installed in the run are two priority-100 flows (`DYNAMIC SYNC FLOW` x2 in
  `ryu_controller.log`). The "200" policy was logged but was not seen applied to the data plane.
- The sync flows (priority 100) and the load flow (priority 10) both have `actions=output:1`: same port, same
  htb FIFO queue; the controller uses no set-queue action, meter or DSCP. Priority only selects the flow-table entry;
  it does not reorder packets in the egress queue.
- Result: the sync traffic waited in the same queue as the load (avg RTT 0.38 ms in P1 -> 41.5 ms in P3b). **No protection was
  observed.** Note that no run without the sync-priority rule exists, so this is "no protection observed", not a
  measured difference against a no-priority baseline. Real protection would need OVS queues plus a set-queue action.
- The `high` threshold (1 MB per 2 s of rx+tx over all ports) also fired during the 10 Mbit/s control (P3a), which had
  no queue.

### Controller and data plane
- Background UDP/6000 is forwarded in the data plane by a priority-10 flow (`in_port=4 ... tp_dst=6000`, 11,488
  packets in P3b by the time of the dump). Packets sent to the controller (`controller_pkts` in `SUMMARY.txt`):
  P3a 4, P3b 0, P4 1. The Ryu log has 89 lines and two `BACKGROUND TRAFFIC` entries.
- P1's first sample (1.524 ms vs 0.323 ms for the other 19) is consistent with the flow-install round trip, but the
  cause was not isolated.

### Not verified
- Why the iperf sender reached only about 19.5 Mbit/s of a 30M request (see above); the VM's iperf version.
- Whether sync traffic behaves differently without the priority-100 rule (no such run).
- Why the policy log alternates `high`/`normal` in pairs.
- The cause of the P1 first-sample outlier.
- Only one run of the VM set is committed; run-to-run variation on the VM is unknown.

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

No numbers in this document are estimated; every value comes from the committed files.
