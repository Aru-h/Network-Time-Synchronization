# Topic 23 — Network Time Synchronization System
## D1 Complete Project: Mininet + SDN + UDP Socket Integration

### What this project demonstrates
This D1 implementation satisfies the five D1 deliverables:

1. Problem Understanding & Architecture
2. UDP Socket Implementation
3. Mininet + SDN Implementation
4. Socket–SDN Integration
5. Initial Testing & Demo

### Project idea
A reference UDP time server provides a common time source. Multiple clients send
four-timestamp synchronization requests. An SDN controller manages a Mininet
Open vSwitch network and dynamically installs a high-priority flow for the
synchronization UDP traffic.

### Architecture

```text
                    RYU SDN CONTROLLER
                           |
                      OpenFlow 1.3
                           |
                    +-------------+
                    |     s1      |
                    |  OVS switch |
                    +-------------+
                     /     |      \
                    /      |       \
                  h1       h2       h3
                Server   Client1  Client2
              10.0.0.1 10.0.0.2 10.0.0.3
                 UDP        \      /
                 5000         \    /
                         Sync traffic
```

### Important note
This project is designed to run on an Ubuntu/Linux machine or VM with Mininet
and Ryu. Windows CMD alone is not sufficient for the Mininet/SDN portion.

---

## 1. Install dependencies on Ubuntu

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-pip python3-venv git
python3 -m pip install --upgrade pip
python3 -m pip install ryu
```

If the system Python blocks pip installation, use a virtual environment:

```bash
python3 -m venv ~/topic23-venv
source ~/topic23-venv/bin/activate
pip install --upgrade pip
pip install ryu
```

Check:

```bash
mn --version
ovs-vsctl --version
ryu-manager --version
```

---

## 2. Run the controller

Terminal 1:

```bash
cd Topic23_D1_Network_Time_Synchronization
ryu-manager controller/time_sync_controller.py --ofp-tcp-listen-port 6653
```

You should see the Ryu controller start.

---

## 3. Start Mininet

Terminal 2:

```bash
cd Topic23_D1_Network_Time_Synchronization
sudo python3 mininet/time_sync_topology.py
```

The topology contains:

- h1 = time server
- h2 = client 1
- h3 = client 2
- s1 = Open vSwitch
- controller = Ryu

IMPORTANT — do not run `pingall` yet. Static ARP is already configured
(`autoStaticArp=True`), so hosts can reach each other without it. Running
`pingall` here installs a generic learning-switch flow between h1 and the
clients before the sync traffic ever runs. That flow matches on destination
MAC only, so it silently forwards the later UDP sync packets too — the
controller never gets a fresh packet-in for them, the priority-100 sync
flow never installs, and the SYNC FLOW INSTALLED / SOCKET-SDN EVENT log
lines (your main integration evidence) never appear. Confirmed by running
both orders end-to-end. Run `pingall` only at step 7, after the sync flow
is already installed.

---

## 4. Start the time server

Inside Mininet:

```bash
mininet> h1 python3 /absolute/path/to/server_client/time_server.py --host 10.0.0.1 --port 5000
```

Replace `/absolute/path/to` with the actual project path.

For convenience, from the project directory:

```bash
pwd
```

Then use the displayed absolute path.

---

## 5. Run client 1

In the Mininet CLI:

```bash
mininet> h2 python3 /absolute/path/to/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100
```

The client prints:

- T1
- T2
- T3
- T4
- RTT
- Offset
- synchronization error

The `--skew-ms` option simulates a client clock difference without changing
the real Linux system clock.

---

## 6. Run client 2

```bash
mininet> h3 python3 /absolute/path/to/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms -50
```

This demonstrates multiple clients.

---

## 7. Verify SDN flow installation

While clients are running:

```bash
mininet> sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

Look for a high-priority UDP/5000 flow.

The controller dynamically recognizes synchronization packets and installs
a priority-100 flow for UDP destination port 5000.

This is the main Socket–SDN integration evidence.

Now that the sync flow is installed, it's safe to run `pingall` as a
general connectivity sanity check — it won't displace the priority-100
flow already in the table:

```bash
mininet> pingall
```

---

## 8. Demonstrate controlled network delay

The topology supports Linux `tc` delay on an interface.

Inside Mininet:

```bash
mininet> h2 tc qdisc add dev h2-eth0 root netem delay 50ms
```

Run the client again:

```bash
mininet> h2 python3 /absolute/path/to/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100
```

Compare RTT with and without the delay.

Remove it:

```bash
mininet> h2 tc qdisc del dev h2-eth0 root
```

---

## 9. D1 demo checklist

### Part A — Architecture
Explain:

- reference server
- multiple clients
- UDP sockets
- four timestamps
- Mininet
- Open vSwitch
- Ryu controller
- OpenFlow
- SDN-controlled synchronization flow

### Part B — Socket implementation
Show:

```text
Client -> UDP request -> Server
Client <- UDP response <- Server
```

### Part C — Mininet + SDN
Show the topology is up and the switch is connected to the controller
(do NOT run `pingall` yet — see the warning in step 3 above; it must come
after Part D or it preempts the sync flow):

```bash
sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

### Part D — Integration
Start the client and immediately show the controller terminal.
Point out the log:

```text
SYNC FLOW INSTALLED
UDP destination port 5000
priority=100
```

### Part E — Initial testing
Perform:

1. normal synchronization
2. multiple clients
3. `pingall` (safe now — the sync flow is already installed)
4. 50 ms controlled delay
5. flow-table verification

---

## 10. Clean up

Exit Mininet:

```text
mininet> exit
```

Then:

```bash
sudo mn -c
```

---

## 11. Suggested GitHub structure

```text
Topic23_D1_Network_Time_Synchronization/
├── controller/
│   └── time_sync_controller.py
├── mininet/
│   └── time_sync_topology.py
├── server_client/
│   ├── time_server.py
│   ├── time_client.py
│   └── load_generator.py
├── docs/
│   ├── D1_REPORT.md
│   ├── D1_DEMO_SCRIPT.md
│   ├── VIVA_QA.md
│   └── ARCHITECTURE.md
├── scripts/
│   ├── install_ubuntu.sh
│   └── run_controller.sh
├── results/
│   └── RESULT_TABLE_TEMPLATE.md
├── requirements.txt
└── README.md
```

### What NOT to claim
This is an educational time synchronization system, not a full production NTP
implementation. It uses the four-timestamp offset/RTT method and a custom SDN
network.

