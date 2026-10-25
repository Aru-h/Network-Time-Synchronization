# Track C — Exact Ubuntu/Mininet Commands

## Terminal 1 — Ryu Track B controller

From the repository root:

```bash
ryu-manager controller/d2_adaptive_controller.py --ofp-tcp-listen-port 6653
```

Leave this terminal open.

## Terminal 2 — Mininet

```bash
sudo python3 mininet/d2_topology.py
```

Inside Mininet:

```text
mininet> pingall
```

Expected: all hosts should reach each other.

## Start Track A server

The Track A server must already be available on h1. From the project root,
use the absolute path shown by `pwd`.

```text
mininet> h1 python3 /ABSOLUTE/PATH/server_client/time_server.py --host 10.0.0.1 --port 5000
```

Leave it running.

## Put Track C evaluator on the Mininet hosts

If the Track C file is stored in the project root:

```text
mininet> h2 cp /ABSOLUTE/PATH/track_c/code/track_c_robustness_eval.py /tmp/track_c_robustness_eval.py
mininet> h3 cp /ABSOLUTE/PATH/track_c/code/track_c_robustness_eval.py /tmp/track_c_robustness_eval.py
```

Then use `/tmp/track_c_robustness_eval.py` in the following commands.

## TEST 1 — Baseline

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test baseline --server 10.0.0.1 --samples 20 --skew-ms 100 --csv /tmp/baseline.csv
```

Record:
- successful samples
- timeout/errors
- average RTT
- average offset
- mean absolute error

## TEST 2 — Multiple clients

Open two Mininet commands (or run one after the other):

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test baseline --server 10.0.0.1 --samples 10 --skew-ms 100 --csv /tmp/client1.csv
```

```text
mininet> h3 python3 /tmp/track_c_robustness_eval.py --test baseline --server 10.0.0.1 --samples 10 --skew-ms -50 --csv /tmp/client2.csv
```

## TEST 3 — 50 ms network delay

Add delay:

```text
mininet> h2 tc qdisc add dev h2-eth0 root netem delay 50ms
```

Run:

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test delay --server 10.0.0.1 --samples 20 --skew-ms 100 --csv /tmp/delay.csv
```

Remove delay:

```text
mininet> h2 tc qdisc del dev h2-eth0 root
```

## TEST 4 — Background load / congestion

Start load from h4:

```text
mininet> h4 python3 /ABSOLUTE/PATH/server_client/load_generator.py 10.0.0.1 --port 6000 --pps 3000 --duration 15 --size 1024
```

While it runs, execute:

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test load --server 10.0.0.1 --samples 20 --skew-ms 100 --csv /tmp/load.csv
```

Watch the Ryu terminal for messages such as:

```text
DYNAMIC SDN:
BACKGROUND TRAFFIC:
DYNAMIC SYNC FLOW:
```

## TEST 5 — Load + delay

Add delay:

```text
mininet> h2 tc qdisc add dev h2-eth0 root netem delay 50ms
```

Start load:

```text
mininet> h4 python3 /ABSOLUTE/PATH/server_client/load_generator.py 10.0.0.1 --port 6000 --pps 3000 --duration 15 --size 1024
```

During the load:

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test load_delay --server 10.0.0.1 --samples 20 --skew-ms 100 --csv /tmp/load_delay.csv
```

Remove delay:

```text
mininet> h2 tc qdisc del dev h2-eth0 root
```

## TEST 6 — Failure and recovery

Stop the h1 server with Ctrl+C in its terminal.

Then run:

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test recovery --server 10.0.0.1 --samples 5 --skew-ms 100 --csv /tmp/failure.csv
```

You should see timeout/errors.

Restart the server:

```text
mininet> h1 python3 /ABSOLUTE/PATH/server_client/time_server.py --host 10.0.0.1 --port 5000
```

Then run again:

```text
mininet> h2 python3 /tmp/track_c_robustness_eval.py --test recovery --server 10.0.0.1 --samples 10 --skew-ms 100 --csv /tmp/recovery.csv
```

You should see successful synchronization.

## TEST 7 — SDN evidence

Inside Mininet:

```text
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

Capture a screenshot showing the UDP/5000 synchronization rule and its priority.

## Clean up

```text
mininet> exit
```

Then:

```bash
sudo mn -c
```

## What to submit

For Track C, keep:
1. `track_c_robustness_eval.py`
2. Track C PDF
3. actual result CSVs/screenshots
4. the commands/results used in the demo

Do not invent performance values. Fill the final report from the actual output.
