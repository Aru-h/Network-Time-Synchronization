# Team contributions

Topic 23, Network Time Synchronization System (PES University, Computer Networks). Team of three, split into three tracks.
The track names below are the ones used inside the repository itself (see `evaluation/README.md`).

<!-- BEFORE SUBMITTING: replace every <...> placeholder below with the real name / SRN / task, then delete this comment. -->

| Member | SRN | Track | One-line summary |
|---|---|---|---|
| Harush S G Temkar | PES1UG25CS204 | Track A: core time synchronization | UDP time server and client, four-timestamp RTT/offset, Mininet topology, socket-SDN integration, D1 demo. |
| <Teammate 2 name> | <SRN> | Track B: dynamic SDN | Ryu controller behaviour: congestion detection, priority escalation, QoS (`set_queue`) path. |
| <Teammate 3 name> | <SRN> | Track C: robustness, evaluation, documentation | Test scenarios, automated runner, result analysis, report. |

## Track A: core time synchronization (Harush S G Temkar)

- UDP reference time server (`server_client/time_server.py`): request parsing, T2/T3 timestamps, reply format
  `REP|seq|T1|T2|T3`, ignoring malformed packets.
- UDP client with simulated clock skew (`sandbox/d1/server_client/time_client.py`): T1/T4 timestamps, round-trip delay and
  offset computation, per-sample and summary output, timeout handling.
- D1 Mininet topology (`sandbox/d1/mininet/time_sync_topology.py`) with a remote Ryu controller.
- Socket-SDN integration in D1: the controller recognises UDP/5000 sync traffic and installs priority-100 flows for both
  directions (`sandbox/d1/controller/time_sync_controller.py`).
- Found and documented the run-order pitfall (running `pingall` first stops the sync flow from being installed) and the
  controlled 50 ms delay experiment.
- D1 report, demo script and checklist (`sandbox/d1/docs/`, `sandbox/d1/D1_CHECKLIST.md`).

## Track B: dynamic SDN (<Teammate 2 name>)

- D2 adaptive controller (`controller/d2_adaptive_controller.py`): congestion detection on OpenFlow port 1 with
  hysteresis, proactive priority-200 sync flows, revert when load clears.
- OVS QoS path (`mininet/d2_qos.py`, `D2_QOS=on`): linux-htb queues and `set_queue:1` on sync flows.
- D2 topology (`mininet/d2_topology.py`).
- <Add or correct specifics.>

## Track C: robustness, evaluation, documentation (<Teammate 3 name>)

- Evaluation client and scenarios (`evaluation/code/robustness_eval.py`, `evaluation/ubuntu_runner/`): baseline, delay,
  load below and above capacity, load plus delay, server failure and recovery.
- Automated runner and PASS/FAIL checks (`run_d2.sh`, `evaluation/code/flow_assertions.py`, `tests/`).
- Result tables, report generation and replay page (`evaluation/code/fill_report.py`, `build_replay.py`,
  `docs/D2_REPORT.md`, `evaluation/RESULT_STATUS.md`).
- Software-clock sync loop and its checks (`docs/SYNC_LOOP.md`, `server_client/sync_loop.py`) <confirm who built this>.
- <Add or correct specifics.>

## Shared work

- Architecture and design decisions (`docs/ARCHITECTURE.md`), integration testing on the Ubuntu VM, demo preparation.
- Each member is expected to be able to explain the whole project in the viva, not only their own track.
