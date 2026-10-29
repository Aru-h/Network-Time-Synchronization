# Network Time Synchronization System — D1 Report

## 1. Problem Understanding

Distributed hosts may have different local clocks. This project develops a
UDP-based synchronization prototype in which a reference server acts as the
time source and multiple clients estimate their clock offset.

The socket application is deployed inside a controlled Mininet network.
A Ryu SDN controller manages the Open vSwitch forwarding behavior and
dynamically gives synchronization traffic a higher-priority flow rule.

## 2. Objectives

- Implement UDP client/server communication.
- Support multiple synchronization clients.
- Calculate round-trip delay.
- Estimate client-server clock offset.
- Build a reproducible Mininet topology.
- Connect Mininet to a functional Ryu SDN controller.
- Detect synchronization traffic using UDP port 5000.
- Dynamically install a higher-priority synchronization flow.
- Demonstrate end-to-end socket/SDN interaction.
- Test controlled delay and compare measurements.

## 3. System Architecture

```text
                  Ryu Controller
                       |
                   OpenFlow 1.3
                       |
                     s1
                   / | \
                  /  |  \
                h1   h2  h3
             server  c1  c2
             .1      .2  .3
```

## 4. Socket Protocol

Request:

```text
REQ|sequence|T1
```

Response:

```text
REP|sequence|T1|T2|T3
```

The client records T4 when the response arrives.

## 5. Synchronization Equations

```text
RTT = (T4 - T1) - (T3 - T2)

Offset = ((T2 - T1) + (T3 - T4)) / 2
```

## 6. Mininet + SDN

The network uses:

- Mininet
- Open vSwitch
- OpenFlow 1.3
- Ryu controller

The controller first installs a table-miss rule. It learns MAC addresses
and installs normal forwarding rules. When UDP destination port 5000 is
detected, the controller installs a priority-100 flow specifically for
synchronization traffic.

## 7. Socket–SDN Integration

The integration is demonstrated by sending the actual UDP time synchronization
packets through the Mininet switch. The controller receives the first packet
through Packet-In, identifies the UDP destination port, and installs the
synchronization flow. Subsequent packets can then follow the installed
OpenFlow rule.

Evidence to capture during D1 demo:

1. Ryu controller terminal showing `SOCKET-SDN EVENT`.
2. Ryu terminal showing `SYNC FLOW INSTALLED`.
3. Client output showing RTT and offset.
4. `ovs-ofctl -O OpenFlow13 dump-flows s1` showing the high-priority rule.

## 8. Initial Test Cases

### Test 1 — Normal synchronization

Client:

```bash
h2 python3 time_client.py --server 10.0.0.1 --port 5000 --samples 10 --skew-ms 100
```

Expected observation:
estimated offset is approximately -100 ms.

### Test 2 — Multiple clients

Run h2 and h3 with different simulated skew values.

### Test 3 — Controlled delay

Add:

```bash
h2 tc qdisc add dev h2-eth0 root netem delay 50ms
```

Run synchronization again and compare RTT.

Remove:

```bash
h2 tc qdisc del dev h2-eth0 root
```

## 9. Results Table

Fill this with actual values from your machine:

| Test | Delay | Client skew | Samples | Avg RTT | Avg offset | Mean error |
|---|---:|---:|---:|---:|---:|---:|
| Normal | 0 ms | +100 ms | 10 | ___ | ___ | ___ |
| Client 2 | 0 ms | -50 ms | 10 | ___ | ___ | ___ |
| Delayed | 50 ms | +100 ms | 10 | ___ | ___ | ___ |

## 10. D1 Deliverable Mapping

| Rubric item | Evidence |
|---|---|
| Problem Understanding & Architecture | This report + architecture diagram |
| TCP/UDP Socket Implementation | `time_server.py`, `time_client.py` |
| Mininet + SDN Implementation | `time_sync_topology.py`, Ryu controller |
| Socket–SDN Integration | Controller logs + OpenFlow flow table |
| Initial Testing & Demo | Test cases + client output |

## 11. Limitations

This is an educational synchronization prototype. It does not implement all
features of production NTP, authentication, clock discipline, or a full
distributed time service.

## 12. Conclusion

The D1 prototype demonstrates an end-to-end UDP time synchronization
application running over a Mininet SDN network, with dynamic controller
behavior for synchronization traffic.
