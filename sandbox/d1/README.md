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

From the repository root, run the install script. It installs Mininet and Open vSwitch, and creates a virtual
environment `~/topic23-venv` with a pinned, working Ryu:

```bash
./scripts/install_ubuntu.sh
source ~/topic23-venv/bin/activate
```

A plain `pip install ryu` can fail on a recent pip or Python, which is why the script pins the versions. Run the
controller from this virtual environment, and run Mininet with `sudo` (check which Python each one uses if you see import
errors).

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
cd topic23_d2_network_time_synchronization
ryu-manager sandbox/d1/controller/time_sync_controller.py --ofp-tcp-listen-port 6653
```

You should see the Ryu controller start.

---

## 3. Start Mininet

Terminal 2:

```bash
cd topic23_d2_network_time_synchronization
sudo python3 sandbox/d1/mininet/time_sync_topology.py
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
mininet> h1 python3 server_client/time_server.py --host 10.0.0.1 --port 5000 &
```

The trailing `&` runs the server in the background so the Mininet prompt stays usable. The command is run from the
repository root (the directory Mininet was started from), so a relative path works.

---

## 5. Run client 1

In the Mininet CLI:

```bash
mininet> h2 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100
```

For each sample the client prints the sequence number, round-trip delay (RTT), estimated offset and absolute
synchronization error (all in ms). After the last sample it prints the number of successful samples, the average RTT, the
average offset and the mean absolute error. The four raw timestamps (T1 to T4) are used in the calculation but are not
printed.

The `--skew-ms` option simulates a client clock difference without changing
the real Linux system clock.

---

## 6. Run client 2

```bash
mininet> h3 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms -50
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
mininet> h2 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100
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

## 11. Layout inside `sandbox/d1/`

The D1 files were moved here when the repository became D2-only. Run every
command from the **repository root** (the Mininet/Ryu commands above already use
`sandbox/d1/...` paths). `server_client/time_server.py` is shared with D2 and
stays in the top-level `server_client/`.

```text
sandbox/d1/
├── controller/time_sync_controller.py
├── mininet/time_sync_topology.py
├── server_client/time_client.py
├── docs/D1_REPORT.md, D1_DEMO_SCRIPT.md
├── scripts/run_controller.sh, run_mininet.sh
├── results/local_socket_level/
└── D1_CHECKLIST.md
```

### What NOT to claim
This is an educational time synchronization system, not a full production NTP
implementation. It uses the four-timestamp offset/RTT method and a custom SDN
network.

