# Evaluation - commands

Two ways to run the evaluation. Use the automated one for results; the manual one is for a step-by-step demo.

## Automated (all results come from this)

From the repository root:

```bash
sudo ./run_d2.sh                      # sandbox tests + Mininet run + PASS/FAIL table (exit 0 only if nothing failed)
sudo ./run_d2.sh --out /tmp/d2run     # same, results into /tmp/d2run (a full run otherwise replaces
                                      #   evaluation/results/actual_sdn_results/)
./run_d2.sh --sandbox-only            # no root: loopback and unit tests only
sudo env EVAL_CHECK_ONLY=1 ./evaluation/ubuntu_runner/run_evaluation.sh   # probe the environment, touch nothing
```

`EVAL_RYU_MANAGER=~/topic23-venv/bin/ryu-manager` and `EVAL_PYTHON` override tool discovery.

Then, from the results folder:

```bash
python3 evaluation/code/error_reduction.py          # mean vs min-RTT-filtered error table
python3 evaluation/code/build_replay.py             # evaluation/results/actual_sdn_results/replay.html (offline page)
python3 evaluation/code/fill_report.py              # fill the generated tables in docs/D2_REPORT.md
```

## Manual (interactive demo)

Terminal 1, the controller (add `D2_QOS=on` for the QoS-on case):

```bash
ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653
```

Terminal 2, the topology (links are shaped: h1 at 20 Mbit, others 100 Mbit; `--qos on` attaches the queues):

```bash
sudo python3 mininet/d2_topology.py [--qos on]
```

Inside Mininet (use absolute paths, from `pwd`):

```text
mininet> h1 python3 /ABS/server_client/time_server.py &
mininet> h2 python3 /ABS/evaluation/code/robustness_eval.py --test baseline --server 10.0.0.1 --samples 20 --skew-ms 100 --csv /tmp/h2.csv
mininet> h3 python3 /ABS/evaluation/code/robustness_eval.py --test baseline --server 10.0.0.1 --samples 20 --skew-ms -50 --csv /tmp/h3.csv
```

Load, while h2 samples (needs `iperf`):

```text
mininet> h1 iperf -s -u -p 6000 &
mininet> h4 iperf -c 10.0.0.1 -u -p 6000 -b 30M -t 30 &
mininet> h2 python3 /ABS/evaluation/code/robustness_eval.py --test load --server 10.0.0.1 --samples 20 --skew-ms 100 --csv /tmp/load.csv
```

Evidence while the load runs:

```text
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1        # priority=200 UDP/5000; set_queue:1 with QoS on
mininet> sh tc -s class show dev s1-eth1                 # with QoS on: sync packets in class 1:2
```

Delay on the host side (keeps the shaping; adds netem under Mininet's htb leaf):

```text
mininet> h2 tc qdisc replace dev h2-eth0 parent 5:1 handle 10: netem delay 25ms
mininet> h1 tc qdisc replace dev h1-eth0 parent 5:1 handle 10: netem delay 25ms
```

Remove it with `tc qdisc del dev <host>-eth0 parent 5:1 handle 10:`. Failure and recovery: stop the server (Ctrl+C), run a client
(timeouts), restart it, run again. Clean up with `exit`, then `sudo mn -c`.
