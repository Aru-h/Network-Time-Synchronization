# Evaluation - Robustness & Performance

Evaluates the Track A time-sync system (UDP, four-timestamp RTT/offset) over the Track B dynamic SDN controller
under: baseline, +50 ms delay, load below and above link capacity, load + delay, and server failure/recovery.
**`RESULT_STATUS.md` is the place for what the committed results show and do not show**; this file describes the test
design and how to run it.

## Test design
Topology: s1 with h1 (time server, **20 Mbps link = bottleneck**), h2 (sync client), h3 (spare), h4 (load source);
h2/h3/h4 links are 100 Mbps. Every link is shaped, whether or not netem exists.
Load is iperf UDP **h4 -> h1:6000**, so it queues in the same s1 -> h1 egress queue as the h2 -> h1 sync requests
(UDP 5000), and starts 2 s before the sync client samples. The runner stops the load when sampling ends.

| Test | What | Condition the runner verifies |
|---|---|---|
| P1 baseline | unloaded | samples return |
| P2 delay | netem 25 ms on h1 **and** h2 (~50 ms RTT, symmetric) | RTT >= baseline + 30 ms, else "DELAY NOT ACHIEVED" (SKIPPED without netem) |
| P3a control | iperf requested at 10M on the 20 Mbps link | must NOT congest ("CONTROL OK") |
| P3b overload | iperf requested at 30M (`-b 30M`) on the 20 Mbps link | avg RTT >= 2x baseline and >= +1 ms, else "NO CONGESTION ACHIEVED" |
| P4 load + delay | P3b load with P2 delay | same 2x / +1 ms check against the P2 delay-only RTT (SKIPPED without netem) |
| P5 / P6 | server down (0 successes expected) / restarted | recovery |

A test is not reported as passing just because samples came back; the exit status is non-zero if any test failed,
did not reach its condition, or was inconclusive.

### Things to know when reading the numbers
- **Requested vs measured load.** `-b 30M` is the *requested* rate. In the committed VM run the iperf client log shows the
  sender actually sent about 19.5 Mbit/s (nominal 30M, measured ~19.5 Mbit/s): enough to saturate the 20 Mbps bottleneck
  and build a queue, with no loss (0 of 8,179 datagrams in P3b). Report it as queueing delay, not packet loss. The cause
  of the lower rate is not verified (see `RESULT_STATUS.md`).
- **Offset error depends on asymmetry, not on RTT.** Offset error = half of (request delay - reply delay). P2 delays both
  directions equally, so offset error stays near 0.24 ms although RTT is ~52 ms. The load queue exists only on the request
  direction (s1 -> h1), so the offset error is about RTT/2 (P3b: 20.6 ms of a 41.5 ms RTT).
- **The 2x congestion rule is harsh on P4.** P4 is compared with the 52 ms delay-only run, so it needs ~104 ms; it measured
  96.8 ms (1.9x) and is flagged "NO CONGESTION ACHIEVED", although ~45 ms of queueing was added (similar to P3b's ~41 ms).
  The threshold has not been changed.
- **Priority gives no protection here.** Sync flows (priority 100) and the load flow (priority 10) output to the same port
  and the same FIFO queue; the controller installs no set-queue action, meter or DSCP. The priority-200 policy is
  logged but no priority-200 flow was seen installed. Observed: no protection (there is no run without the rule to compare).

## Run (on the Ubuntu VM, from the repository root)
```
sudo ./evaluation/ubuntu_runner/run_evaluation.sh
```
The launcher finds `ryu-manager` and a Python with Mininet even though sudo resets PATH (it looks at PATH,
`~/topic23-venv`, pyenv). Check the environment first, without running anything:
`sudo env EVAL_CHECK_ONLY=1 ./evaluation/ubuntu_runner/run_evaluation.sh` (checks ryu-manager, OVS tools and daemon, netem and
datapath; it never touches `results/`). Overrides: `EVAL_RYU_MANAGER`, `EVAL_PYTHON`.
It needs `iperf` (`sudo apt install -y iperf`; without it a weaker Python generator is used and the run says so).
The run takes a few minutes (P5 alone waits ~40 s for its timeouts) and rewrites `results/actual_sdn_results/`
(the previous contents of that folder are replaced, but only after all environment checks have passed; a failed check leaves
the old results in place).

## Layout
| Path | What |
|---|---|
| `code/robustness_eval.py` | Client-side evaluator: RTT, offset, abs. error, timeouts -> CSV |
| `ubuntu_runner/run_evaluation.sh` | Launcher (environment discovery, then the runner) |
| `ubuntu_runner/run_mininet_tests.py` | The runner |
| `results/actual_sdn_results/` | Ubuntu VM run: `SUMMARY.txt`, per-test CSV/TXT, `evidence_*_during_load.txt` (flows, port counters, `tc -s` of the bottleneck), `policy_*.txt`, iperf server/client logs, Ryu log, `environment.txt` |
| `results/local_socket_level/` + the PDF | Earlier plain-socket results (no SDN), a different experiment |
| `docs/` | Manual Mininet commands (no bottleneck: plain interactive topology), install notes |
| `RESULT_STATUS.md` | What the results show, what they do not, what was not verified |
