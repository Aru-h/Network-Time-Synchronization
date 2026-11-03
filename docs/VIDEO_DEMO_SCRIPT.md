# Video demo script (about 6 minutes)

Record the Ubuntu VM terminal (split into three panes: controller, Mininet, spare) with a screen recorder such as OBS or
`Ctrl+Alt+Shift+R` (GNOME). Upload as an unlisted YouTube video or add the file to a GitHub release, then put the link in
the README under "Video demo". Do not commit a large video file into the repository itself.

Say the quoted lines in your own words; the commands are exact. Run everything from the repository root.

| Time | What is on screen | Say |
|---|---|---|
| 0:00 | README architecture diagram | "Hosts have different clocks. A server and clients exchange four timestamps over UDP, in a Mininet network controlled by a Ryu SDN controller." |
| 0:30 | `docs/ARCHITECTURE.md`, the formulas | "RTT is (T4-T1)-(T3-T2). Offset is half the sum of the two one-way differences. It is exact only if both directions have equal delay." |
| 1:00 | Pane 1: `ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653` | "Controller first, so it is listening when the switch connects." |
| 1:20 | Pane 2: `sudo python3 mininet/d2_topology.py` | "h1 is the server on a 20 Mbit link, h2 and h3 are clients, h4 generates load." Show `SWITCH CONNECTED` in pane 1. |
| 1:45 | `mininet> h1 python3 server_client/time_server.py --host 10.0.0.1 --port 5000 &` | "Server in the background. Do not run pingall yet." |
| 2:00 | `mininet> h2 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100`, then the same on `h3` with `--skew-ms -50` | "h2's clock is 100 ms fast, so the measured offset is about minus 100 ms; h3 is the opposite sign. Error is sub-millisecond." |
| 2:45 | Pane 1: `SOCKET-SDN D2 EVENT` and `DYNAMIC SYNC FLOW` lines. Then, within about 20 s of the last client run (the sync flows have a 20 s idle timeout), `mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1` | "The controller recognised UDP port 5000 and installed priority-100 flows, one per direction per client." |
| 3:30 | `mininet> pingall` | "Only now pingall, so it cannot pre-empt the sync flow." |
| 3:45 | `mininet> h2 tc qdisc add dev h2-eth0 root netem delay 50ms`, rerun the h2 client command, then `mininet> h2 tc qdisc del dev h2-eth0 root` | "RTT rises by about 50 ms. One direction is slower, so the offset moves too." |
| 4:30 | In another terminal: `sudo ./run_d2.sh --out /tmp/d2demo` (show the end of the run, or play the finished table) | "The automated run asserts on the flow tables and queue counters." |
| 5:00 | `python3 evaluation/code/build_replay.py /tmp/d2demo` then open `/tmp/d2demo/replay.html` | "Load over capacity: QoS off, RTT about 42 ms and offset error about 21 ms. QoS on, both near zero." Show the priority 100 to 200 timeline and `set_queue:1` in the flow table. |
| 5:40 | `screenshots/01_summary_avg_rtt.png` | "Priority alone does not help, because it only orders flow lookups. The queue is what protects sync traffic." |
| 6:00 | README | "Contributions and limitations are in the repository." |

Before recording, run through it once without recording: the first run after boot is slower and the first client sample
is usually the largest RTT.

Exit cleanly afterwards: `mininet> exit`, then `sudo mn -c`.
