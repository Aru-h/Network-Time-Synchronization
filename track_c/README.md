# Track C - Robustness & Performance Evaluation

Evaluates the Track A time-sync system (UDP, four-timestamp RTT/offset) running over the Track B
dynamic SDN controller, under: baseline, +50 ms delay, background UDP load, load+delay, and server
failure/recovery.

| Path | What |
|---|---|
| `code/track_c_robustness_eval.py` | Client-side evaluator: RTT, offset, abs. error, timeouts -> CSV |
| `ubuntu_runner/run_track_c_mininet.sh` | One command: starts Ryu + Mininet, runs P1-P6, saves everything |
| `ubuntu_runner/track_c_mininet_automated.py` | The runner (exits non-zero if any test fails) |
| `docs/TRACK_C_COMMANDS.md` | Manual step-by-step Mininet commands (alternative to the runner) |
| `docs/INSTALL_UBUNTU.txt` | Prerequisites |
| `results/actual_sdn_results/` | Real Mininet+Ryu+OVS run (see `RESULT_STATUS.md` for its limits) |
| `results/local_socket_level/` | Earlier plain-socket results (no SDN) |
| `Track_C_Final_Report_With_Executed_Results.pdf` | Report for the plain-socket results |

Tests: P1 baseline, P2 controlled delay (25 ms on h1 + h2 = ~50 ms RTT), P3 background load,
P4 load + delay, P5 server down (expects 0 successes), P6 server restarted (expects recovery).

Run (from repo root, Ubuntu with Mininet, Open vSwitch and Ryu): `sudo ./track_c/ubuntu_runner/run_track_c_mininet.sh`
