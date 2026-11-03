# Screenshots and result figures

## Included (generated from the committed measurements)

| File | What it shows | How it was made |
|---|---|---|
| `01_summary_avg_rtt.png` | Mean sync RTT for every test (baseline, delay, load, load + delay, recovery), QoS off vs on | `python3 evaluation/code/make_figures.py` from `evaluation/results/actual_sdn_results/*.csv` |
| `02_summary_offset_error.png` | Mean absolute offset error for the same tests | same script |
| `03_replay_P3b_load_over_capacity_qos_on.png` | Replay page, over-capacity load: per-sample RTT and offset error, controller policy timeline (priority 100 to 200), flow table with `set_queue:1`, assertions | `python3 evaluation/code/build_replay.py`, opened in a browser |
| `04_replay_P3b_flow_table_qos_off.png` | Same page with the QoS-off flow table (priority 200, no `set_queue`) | same |
| `05_replay_P4_load_plus_delay.png` | Replay page, load plus 50 ms delay | same |

These are plots and renderings of the real result files, not photographs of a terminal. Regenerate them any time with the
commands above.

## Still to capture on the Ubuntu VM (real terminal screenshots)

Take these during a live run and save them here with these names. They are the usual evidence a reviewer looks for.

| File to add | What to capture | Command |
|---|---|---|
| `10_controller_connected.png` | Controller log showing the switch connected | `ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653` |
| `11_client_h2_sync.png` | Client output: per-sample RTT, offset, error and the summary, skew +100 ms | `h2 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100` |
| `12_client_h3_sync.png` | Second client, skew -50 ms | same with `h3` and `--skew-ms -50` |
| `13_controller_sync_flow_log.png` | Controller log lines `SOCKET-SDN D2 EVENT` and `DYNAMIC SYNC FLOW ... priority=100` | controller terminal while a client runs |
| `14_dump_flows_priority100.png` | Priority-100 UDP/5000 flows on the switch | `sh ovs-ofctl -O OpenFlow13 dump-flows s1` (within about 20 s of a client run) |
| `15_delay_experiment.png` | RTT with and without 50 ms netem | `h2 tc qdisc add dev h2-eth0 root netem delay 50ms`, rerun client, then `h2 tc qdisc del dev h2-eth0 root` |
| `16_pingall.png` | `pingall` with 0% dropped (run after the sync flows exist) | `pingall` |
| `17_run_d2_pass_table.png` | The PASS/FAIL table from the automated run | `sudo ./run_d2.sh --out /tmp/d2demo` |
| `18_dump_flows_congested.png` | Priority-200 sync flows with `set_queue:1` during a QoS-on overload | `sh ovs-ofctl -O OpenFlow13 dump-flows s1` while the load runs |

Tip: crop to the terminal and keep the command line visible in the shot so the evidence is self-explaining. Do not run
`pingall` before the client (see `docs/ARCHITECTURE.md`, Section 6).
