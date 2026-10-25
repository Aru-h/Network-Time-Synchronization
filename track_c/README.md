# Track C - Robustness & Performance Evaluation

Evaluates the Track A time-sync system (UDP, four-timestamp RTT/offset) over the Track B dynamic SDN controller
under: baseline, +50 ms delay, load below and above link capacity, load + delay, and server failure/recovery.
See `RESULT_STATUS.md` for what the committed results do and do not show.

## Test design
Topology: s1 with h1 (time server, **20 Mbps link = bottleneck**), h2 (sync client), h3 (spare), h4 (load source);
h2/h3/h4 links are 100 Mbps. Every link is shaped, whether or not netem exists.
Load is iperf UDP **h4 -> h1:6000**, so it queues in the same s1->h1 egress queue as the h2 -> h1 sync requests (UDP 5000),
and starts 2 s before the sync client samples.

| Test | What | Condition the runner verifies |
|---|---|---|
| P1 baseline | unloaded | samples return |
| P2 delay | netem 25 ms on h1 + h2 (~50 ms RTT) | RTT >= baseline + 30 ms, else "DELAY NOT ACHIEVED" (SKIPPED without netem) |
| P3a control | 10 Mbps load on the 20 Mbps link | must NOT congest ("CONTROL OK") |
| P3b overload | 30 Mbps load on the 20 Mbps link | avg RTT >= 2x baseline and >= +1 ms, else "NO CONGESTION ACHIEVED" |
| P4 load + delay | P3b load with P2 delay | same check against the P2 delay-only RTT (SKIPPED without netem) |
| P5 / P6 | server down (0 successes expected) / restarted | recovery |

A test is not reported as passing just because samples came back; the exit status is non-zero if any test failed,
did not reach its condition, or was inconclusive. Predictions before measuring: under overload RTT rises sharply and
requests are lost; only the request direction queues, so offset error ~ RTT/2; priority 100/200 does not protect sync
traffic (same output port, same FIFO, no set-queue/meter/DSCP).

## Run (on the Ubuntu VM, from the repository root)
```
sudo ./track_c/ubuntu_runner/run_track_c_mininet.sh
```
The launcher finds `ryu-manager` and a Python with Mininet even though sudo resets PATH (it looks at PATH,
`~/topic23-venv`, pyenv). Check the environment first, without running anything:
`sudo env TRACKC_CHECK_ONLY=1 ./track_c/ubuntu_runner/run_track_c_mininet.sh`. Overrides: `TRACKC_RYU_MANAGER`, `TRACKC_PYTHON`.
It needs `iperf` (`sudo apt install -y iperf`; without it a weaker Python generator is used and the run says so).
The run takes a few minutes (P5 alone waits ~40 s for its timeouts) and wipes and rewrites `results/actual_sdn_results/`.

## Layout
| Path | What |
|---|---|
| `code/track_c_robustness_eval.py` | Client-side evaluator: RTT, offset, abs. error, timeouts -> CSV |
| `ubuntu_runner/run_track_c_mininet.sh` | Launcher (environment discovery, then the runner) |
| `ubuntu_runner/track_c_mininet_automated.py` | The runner |
| `results/actual_sdn_results/` | `SUMMARY.txt`, per-test CSV/TXT, `evidence_*_during_load.txt` (flows, port counters, `tc -s` of the bottleneck), `policy_*.txt`, `iperf_server.log`s, Ryu log, `environment.txt` |
| `results/local_socket_level/` + the PDF | Earlier plain-socket results (no SDN) |
| `docs/` | Manual Mininet commands (no bottleneck: plain interactive topology), install notes |
