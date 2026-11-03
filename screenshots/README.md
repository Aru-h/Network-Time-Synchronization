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

## Terminal screenshots from a live run on the Ubuntu VM (2026-11-03)

D2 topology with the adaptive controller, QoS off. Server on h1, clients on h2 and h3.

| File | What it shows | Command |
|---|---|---|
| `10_controller_connected.png` | Controller log: app loaded, `D2 SWITCH CONNECTED dpid=1`, then the 1 s `DYNAMIC SDN` monitor lines (port 1 egress about 0 Mbit/s, policy 100) | `ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653` |
| `11_client_h2_sync.png` | Client h2, skew +100 ms: per-sample RTT, offset (about -99.8 ms) and error, plus the summary | `h2 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100` |
| `12_client_h3_sync.png` | Client h3, skew -50 ms: offset about +50.3 ms | same with `h3` and `--skew-ms -50` |
| `13_controller_sync_flow_log.png` | Controller log: `SOCKET-SDN D2 EVENT` and `DYNAMIC SYNC FLOW ... priority=100` for both directions of both clients (the 1 s monitor lines are filtered out of this view with `grep -v "DYNAMIC SDN"`) | controller terminal while the clients run |
| `14_dump_flows_priority100.png` | Switch flow table: priority-100 UDP/5000 flows (`idle_timeout=20`) above the priority-0 table-miss entry (cropped to the dump) | `sh ovs-ofctl -O OpenFlow13 dump-flows s1` |
| `15_delay_experiment.png` | Two runs of the h2 client stacked in one image (a composite of two screenshots; the yellow labels were added): baseline RTT 0.64 ms, error 0.04 ms; with 50 ms netem on h2 RTT 51.6 ms, error 25.5 ms | `h2 tc qdisc add dev h2-eth0 root netem delay 50ms`, rerun the client, then `h2 tc qdisc del dev h2-eth0 root` |
| `16_pingall.png` | `pingall`, 0% dropped (12/12), run after the sync flows existed | `pingall` |

The PASS/FAIL table of the automated run (`sudo ./run_d2.sh`) is not included as a screenshot; its results are in
`evaluation/RESULT_STATUS.md` and `docs/D2_REPORT.md`.
