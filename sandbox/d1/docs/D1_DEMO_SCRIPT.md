# D1 Demo Script — What to Say

## Step 1 — Problem
"Different hosts can have different local clock values. Our system uses a
reference server and UDP timestamp exchange to estimate clock offset."

## Step 2 — Architecture
"This is our Mininet topology. h1 is the reference server, h2 and h3 are
clients, s1 is an Open vSwitch, and Ryu is the SDN controller."

## Step 3 — Socket
"The client sends T1, the server records T2 and T3, and the client records T4.
We calculate RTT and clock offset from these four timestamps."

## Step 4 — SDN
"The Ryu controller uses OpenFlow 1.3. It learns the network and installs
forwarding rules."

## Step 5 — Integration
"When the controller sees UDP destination port 5000, it recognizes it as
synchronization traffic and dynamically installs a higher-priority rule."

## Step 6 — Demonstration

IMPORTANT — order matters here. Run the server and client FIRST, before
`pingall`. If `pingall` runs first, its ICMP traffic installs a generic
learning-switch flow (matches on destination MAC only) that silently
forwards the later UDP sync traffic too — the controller never sees a
new packet-in for it, so the priority-100 sync flow never installs and
the SYNC FLOW INSTALLED / SOCKET-SDN EVENT log lines never appear. Verified
by actually running both orders.

Run the server, then the client:

```text
mininet> h1 python3 server_client/time_server.py --host 10.0.0.1 --port 5000 &
mininet> h2 python3 sandbox/d1/server_client/time_client.py --server 10.0.0.1 --port 5000 --samples 10
```

Show, in the controller terminal:

```text
SOCKET-SDN EVENT
SYNC FLOW INSTALLED
```

Then run:

```text
ovs-ofctl -O OpenFlow13 dump-flows s1
```

Point to the UDP/5000 rule with priority 100.

Only now run `pingall` (as a general connectivity sanity check) — the
sync flow is already installed by this point, so it isn't affected.

```text
pingall
```

## Step 7 — Delay experiment
"Now we add 50 ms network delay and repeat synchronization. RTT should increase,
while the offset estimate can still be observed."

## Step 8 — Close
"This completes our D1 requirements: socket implementation, Mininet and SDN,
socket-SDN integration, and initial testing."
