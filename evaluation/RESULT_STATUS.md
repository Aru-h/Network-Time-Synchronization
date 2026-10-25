# Evaluation result status

Two independent result sets exist. They are **different experiments**; do not mix them in the report.

## A. `results/actual_sdn_results/` - Mininet + Ryu + Open vSwitch (OpenFlow 1.3)
Produced by `ubuntu_runner/run_evaluation.sh`.

**Where it was produced: a sandbox, NOT the target Ubuntu VM.** Environment (`environment.txt`):
OVS 3.3.9 **userspace datapath** (no OVS kernel module), **no `netem`**, Python 3.13, iperf 2 load tool,
h1 link = 20 Mbps bottleneck, h2/h3/h4 links = 100 Mbps. Two full runs gave the same picture
(P3b: 10/20 samples lost, surviving RTT 56.56 ms and 56.63 ms; the committed folder is run 2).

**Final numbers must come from the Ubuntu VM** (kernel datapath + netem). Replace this folder with the
VM output (see README.md for the command). Until then P2 and P4 do not exist.

### Per-test status (committed run)
| Test | Status | Measured |
|---|---|---|
| P1 baseline | PASS | 20/20, avg RTT 0.798 ms (first sample 3.19 ms: it goes through the controller to install the flow; the other 19 average 0.672 ms) |
| P2 delay 50 ms | **SKIPPED** - no netem in this kernel | - |
| P3a control, 10 Mbps load on 20 Mbps link | CONTROL OK (no congestion, as expected) | 20/20, avg RTT 0.397 ms, no iperf loss (rx 10.5 Mbps) |
| P3b load 30 Mbps on 20 Mbps link | CONGESTION ACHIEVED | **10/20 timed out**; the 10 that returned: RTT 56.3-57.8 ms (avg 56.63 ms); iperf server rx 19.4 Mbps, 38 % loss |
| P4 load + delay | **SKIPPED** - no netem | - |
| P5 server down | PASS | 0/20 (as expected) |
| P6 server restarted | PASS | 20/20, avg RTT 0.650 ms |

"CONGESTION ACHIEVED" means the runner's check passed: avg RTT >= 2x the unloaded baseline and >= 1 ms above it.
The "x baseline" ratio is noisy because the baseline is sub-millisecond (63x in run 1, 71x in run 2); the absolute
56.6 ms and the 50 % sample loss were the same in both runs. The RTT average counts only the samples that came back.

### What the data supports
- **Load now shares the bottleneck with sync traffic.** Load goes h4 -> h1, the same s1->h1 egress queue as the
  h2 -> h1 sync requests. Under 30 Mbps the queue builds (`tc -s qdisc` during the load: backlog 93 packets / 141 KB,
  which at 20 Mbps is ~56.2 ms, matching the constant ~56.6 ms RTT) and half of the sync requests are lost.
  Under 10 Mbps nothing builds: a queue appears only when load exceeds capacity.
- **Only the request direction is queued, so offset error ~ RTT/2.** In P3b, |offset error| / (RTT/2) was 0.989-0.996
  for all 10 returned samples (d1 ~ RTT, d2 ~ 0). The mean offset was -71.9 ms against an expected -100 ms.
- **Background traffic is now forwarded in the data plane** (controller fix, commit 8a245a6). During the P3b load the
  table-miss rule had counted 4 packets, while the `priority=10 udp tp_dst=6000` flow had carried 68,511 packets
  (`evidence_P3b_load_over_during_load.txt`). The Ryu log is 8 KB instead of ~1.5 MB.
- **OpenFlow priority did not protect the sync traffic.** The flows dumped during the load show the sync flows at
  priority 100 and the load flow at priority 10, both with `actions=output:1` - the same port and the same FIFO
  queue; the controller uses no set-queue action, meter or DSCP. Despite the priority-100 rule, 50 % of sync
  requests were lost. (No run without the sync priority rule was made, so this shows "no protection", not a measured
  difference against a no-priority baseline.) Real protection would need OVS queues plus a set-queue action.

### The "priority 200" policy - what is and is not shown
- The controller **logs** `traffic high ... sync priority policy = 200` during load (`policy_P3a_load_under.txt`,
  `policy_P3b_load_over.txt`, `policy_lines_all.txt`). The log alternates in pairs: one `high` reading then a ~0-byte
  `normal ... = 100` reading, so even under sustained overload it is not a stable signal (cause not investigated).
- **No flow with priority 200 was ever installed** (`grep priority=200` over all evidence: none). The only sync flows
  installed in the whole run are the two priority-100 ones (`policy_lines_all.txt`). From reading the controller code,
  a sync flow is (re)installed only when a sync packet reaches the controller, and the flows installed in P1 stayed
  alive (idle timeout 20 s) the whole run. So the "200" policy was logged but never applied to the data plane in this run.
  The earlier claim "Ryu switched to the priority-200 policy" was removed from these docs for that reason.
- The `high` threshold (1 MB per 2 s of rx+tx over all ports) also fired for the 10 Mbps control, which is not congested.

### Not verified here
- Delay (P2) and load+delay (P4): the netem code path could not run in the sandbox. Only its `tc` parent/handle
  syntax was checked with a different qdisc. The runner verifies applied delay (`tc qdisc show`) and requires P2 to add
  >= 30 ms RTT, otherwise it reports "DELAY NOT ACHIEVED".
- Behaviour on the kernel OVS datapath. Userspace OVS may differ in timing/queueing.
- Numbers in the PDF are from set B, not from this set.

## B. `results/local_socket_level/` and the PDF report - plain sockets, no SDN
Measurements of the Track A server + evaluator over loopback with a UDP delay proxy (P2/P4 ~50 ms RTT) and
background UDP load against the server socket. Mininet/OVS/Ryu were not involved and no bottleneck was verified. The PDF
`Evaluation_Report_Loopback_Results.pdf` reports this set and says so on its first page.

No numbers in either set are fabricated or estimated; every value comes from a run.
