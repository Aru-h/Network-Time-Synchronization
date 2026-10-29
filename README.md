# Network Time Synchronization over SDN (Topic 23, D2)

A UDP reference time server, NTP-style clients (four timestamps), and a Ryu
OpenFlow 1.3 controller that watches the network and protects the sync traffic
when a background load congests the path. Everything runs in Mininet with
Open vSwitch on Ubuntu. The D1 prototype lives in [`sandbox/d1/`](sandbox/d1/).

## Architecture

```text
                 Ryu controller (controller/d2_adaptive_controller.py)
                        |  OpenFlow 1.3: port stats, flow-mods
                  +-----------+
 h1 server  ------|    s1     |------ h2 client (skew +100 ms)
 10.0.0.1   20M   |    OVS    |------ h3 client (second skew)
 UDP 5000         +-----------+------ h4 load generator -> h1 UDP 6000
```

- **h1** runs `server_client/time_server.py` on `10.0.0.1:5000`. Its link to
  s1 is the 20 Mbit bottleneck that sync replies and the load share.
- **h2 / h3** are sync clients. `--skew-ms` simulates a wrong local clock
  without changing the OS clock.
- **h4** sends background UDP (port 6000) toward h1.
- **Controller** learns MACs, installs a UDP/5000 sync flow (priority 100,
  raised to 200 under congestion) and classifies UDP/6000 as background.

Four timestamps, one request/reply:

```text
Client                      Server
T1 ---- REQ|seq|T1 ------->  T2
T4 <--- REP|seq|T1|T2|T3 --  T3

RTT    = (T4 - T1) - (T3 - T2)
Offset = ((T2 - T1) + (T3 - T4)) / 2
```

Estimated offset and RTT are reported; the system clock is never changed.

## Layout

| Path | What |
|---|---|
| `controller/d2_adaptive_controller.py` | Ryu D2 controller |
| `mininet/d2_topology.py` | Interactive D2 topology (h1..h4, s1) |
| `server_client/` | `time_server.py`, `load_generator.py` |
| `evaluation/` | Evaluator, automated runner, results, result status |
| `docs/D2_REPORT.md` | Report |
| `scripts/install_ubuntu.sh` | Installs Mininet, OVS, a pinned Ryu venv |
| `sandbox/d1/` | The D1 project, moved aside |

## Install

```bash
./scripts/install_ubuntu.sh        # Mininet, Open vSwitch, iperf, Ryu in ~/topic23-venv
```

## Run the evaluation

```bash
sudo env EVAL_CHECK_ONLY=1 ./evaluation/ubuntu_runner/run_evaluation.sh   # probe only
sudo ./evaluation/ubuntu_runner/run_evaluation.sh                         # full run
```

Results go to `evaluation/results/actual_sdn_results/` (start with
`SUMMARY.txt`); `evaluation/RESULT_STATUS.md` says what they do and do not
show. Set `EVAL_RYU_MANAGER=~/topic23-venv/bin/ryu-manager` if `ryu-manager` is
not found.

## Manual demo

1. `ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653`
2. `sudo python3 mininet/d2_topology.py`
3. `mininet> h1 python3 server_client/time_server.py &`
4. Clients: `h2 python3 evaluation/code/robustness_eval.py --test baseline --server 10.0.0.1 --skew-ms 100 --csv /tmp/h2.csv`
5. Load from h4 and watch the Ryu log and `sh ovs-ofctl -O OpenFlow13 dump-flows s1`.

Full command list: `evaluation/docs/EVALUATION_COMMANDS.md`.

## Limitations

Educational prototype, not production NTP. The controller uses a simple
traffic-volume threshold.
