# Track C result status

There are two independent sets of results. They are NOT the same experiment; do not mix them up in the report.

## 1. `results/actual_sdn_results/` - real Mininet + Ryu + Open vSwitch run (OpenFlow 1.3)
Produced by `ubuntu_runner/run_track_c_mininet.sh` (Track A server on h1, Track B Ryu controller,
evaluator on h2, UDP background load from h4). `SUMMARY.txt` lists PASS/FAIL per test and
`flows.txt` is the `ovs-ofctl dump-flows s1` evidence (priority-100 `udp, tp_dst=5000` sync rule).

Environment limits of the machine that produced the committed run (see `environment.txt`):
- No `netem` kernel module -> **P2 (50 ms delay) was SKIPPED and P4 ran as load-only**, not load+delay.
- No Open vSwitch kernel module -> OVS **userspace (netdev) datapath** was used (TX checksum offload disabled on hosts).
- Links were plain (no bandwidth/delay shaping).
- Ryu logged "traffic high ... sync priority policy = 200" during P3/P4, i.e. the dynamic policy triggered.

**Before final submission, re-run on stock Ubuntu (has netem) so P2 and P4 are real delay tests:**
`sudo ./track_c/ubuntu_runner/run_track_c_mininet.sh` and replace the committed `actual_sdn_results/`.

## 2. `results/local_socket_level/` and the PDF report - plain-socket measurements (no SDN)
Real measurements of the Track A server + Track C evaluator over loopback with a UDP delay proxy
(P2/P4 ~50 ms RTT) and real background UDP load. Mininet/OVS/Ryu were NOT involved. The PDF
`Track_C_Final_Report_With_Executed_Results.pdf` reports this set and says so on its first page.

No numbers in either set are fabricated.
