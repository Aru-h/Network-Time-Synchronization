#!/bin/bash
# Run from the project root after starting the Ryu D2 controller and Mininet.
# This script prints the commands to run because Mininet's CLI controls hosts.

cat <<'EOF'
D2 TEST PLAN

1) NORMAL BASELINE
mininet> h2 python3 server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 20 --skew-ms 100

2) MULTIPLE CLIENTS
mininet> h2 python3 server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100
mininet> h3 python3 server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms -50

3) CONGESTION / CHALLENGING SCENARIO
mininet> h4 python3 server_client/load_generator.py 10.0.0.1 --port 6000 --pps 3000 --duration 15 --size 1024
mininet> h2 python3 server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 20 --skew-ms 100

4) DELAY
mininet> h2 tc qdisc add dev h2-eth0 root netem delay 50ms
mininet> h2 python3 server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 20 --skew-ms 100
mininet> h2 tc qdisc del dev h2-eth0 root

5) SDN EVIDENCE
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1

6) SERVER FAILURE / RECOVERY
Stop the h1 server with Ctrl+C in its terminal.
Run a client and observe timeout.
Restart the server and repeat synchronization to demonstrate recovery.

7) CONTROLLER EVIDENCE
Look for:
DYNAMIC SDN:
DYNAMIC SYNC FLOW:
SOCKET-SDN D2 EVENT:
BACKGROUND TRAFFIC:
