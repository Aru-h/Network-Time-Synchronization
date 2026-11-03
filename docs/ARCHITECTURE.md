# Architecture and design

Topic 23, Network Time Synchronization over SDN. This page explains how the pieces fit together and why they are built
the way they are. For measured results see [D2_REPORT.md](D2_REPORT.md); for the optional client-side correction loop see
[SYNC_LOOP.md](SYNC_LOOP.md).

## 1. Problem and objectives

Hosts have different local clocks. A client needs to estimate how far its clock is from a reference, and that estimate is
only as good as the network path the timestamps travel over. The project therefore combines three layers:

| Layer | Objective |
|---|---|
| Application (UDP sockets) | A reference server and clients exchange four timestamps and compute round-trip delay and clock offset. |
| Network (Mininet + Open vSwitch) | A reproducible virtual network with a controllable bottleneck, delay and load. |
| Control (Ryu, OpenFlow 1.3) | The controller recognises sync traffic by its UDP port, gives it a dedicated high-priority flow, reacts to congestion, and (with QoS on) puts it in a protected queue. |

D1 delivered the socket, topology and controller prototype (`sandbox/d1/`). D2 added measured behaviour under delay,
congestion and failure, a congestion-aware controller, and an OpenFlow-to-queue (QoS) path.

## 2. Components

```text
                 Ryu controller  controller/d2_adaptive_controller.py
                        |  OpenFlow 1.3 over TCP 6653: packet-in, flow-mod, packet-out, port stats
                  +-----------+
 h1 time server --|           |-- h2 sync client (simulated skew +100 ms)
 10.0.0.1, 20M    |  s1 (OVS) |-- h3 sync client (simulated skew -50 ms)
 UDP 5000         |           |-- h4 load generator -> h1 UDP 6000
                  +-----------+
```

| Component | File | Role |
|---|---|---|
| Time server | `server_client/time_server.py`, `ktime.py` | UDP server on `10.0.0.1:5000`. Replies `REP|seq|T1|T2|T3`. T2 is a kernel receive timestamp (`SO_TIMESTAMPNS`), with every fallback to user-space time counted and printed. |
| D1 client | `sandbox/d1/server_client/time_client.py` | Sends requests, records T4, prints per-sample RTT, offset and error, then a summary. `--skew-ms` simulates a wrong clock without touching the OS clock. |
| Evaluation client | `evaluation/code/robustness_eval.py` | The D2 client used by the automated runner. Writes one CSV per test. |
| Sync loop (optional) | `server_client/sync_loop.py`, `softclock.py`, `agefilter.py` | A client that keeps a software clock and corrects it by step or slew. Not part of `run_d2.sh`. |
| Load generator | `iperf` (UDP, h4 to h1:6000); `server_client/load_generator.py` as fallback | Saturates the 20 Mbit link to h1. |
| Topology | `mininet/d2_topology.py` | One switch, four hosts. h1 link 20 Mbit, others 100 Mbit. |
| QoS | `mininet/d2_qos.py` | OVS linux-htb on `s1-eth1`: queue 0 default, queue 1 for sync (2 Mbit minimum, 20 Mbit total). |
| Controller (D2) | `controller/d2_adaptive_controller.py` | Learning switch, sync-flow installation, congestion detection, priority escalation, optional `set_queue`. |
| Controller (D1) | `sandbox/d1/controller/time_sync_controller.py` | Learning switch plus a priority-100 sync flow. |
| Runner / checks | `run_d2.sh`, `evaluation/ubuntu_runner/`, `evaluation/code/` | Run every scenario, assert on flow tables and `tc` counters, write the PASS/FAIL table and report tables. |

## 3. Time-sync protocol

```text
Client                         Server
T1  --- REQ|seq|T1 ---------->  T2
T4  <-- REP|seq|T1|T2|T3 -----  T3
```

T1 and T4 are on the client clock; T2 and T3 are on the server clock. With theta = server clock minus client clock,
d1 the forward delay and d2 the reverse delay:

```text
T2 - T1 = d1 + theta          T3 - T4 = theta - d2

RTT    = (T4 - T1) - (T3 - T2)            = d1 + d2            (exact, needs no assumption)
Offset = ((T2 - T1) + (T3 - T4)) / 2      = theta + (d1 - d2)/2
```

The offset error is `(d1 - d2)/2` and is bounded by RTT/2, so **the estimate is only exact when the two directions have
equal delay**. This is the reason the project matters: congestion that delays one direction more than the other turns
directly into offset error (see Section 7).

Design choices:

- **UDP, not TCP.** One datagram per message, no handshake or retransmission. A lost sample is skipped rather than
  retransmitted with a misleading timestamp. Message boundaries are preserved (one send is one receive).
- **Matching.** Replies echo `seq` and `T1`; the client discards a reply that does not match the current request.
- **Stateless server.** A single loop answers whichever client sent the datagram, using the source address from
  `recvfrom`. Malformed packets are ignored and the client sees a timeout.
- **Kernel receive timestamps** for T2 and T4 (D2) so queueing inside the host does not hide in the measurement.
- **Skew is simulated.** The client adds `--skew-ms` to its own clock readings; the expected measured offset is
  `-skew`, which gives a ground truth to compute the error against.

## 4. Control plane design

### 4.1 Flow table

| Priority | Match | Action | Idle timeout | Installed when |
|---|---|---|---|---|
| 0 | any | send to controller | none | switch connects (table-miss) |
| 10 | `in_port`, `eth_dst` | output | 30 s | non-sync packet-in with a known destination |
| 10 | UDP, `in_port`, `ipv4_dst`, `udp_dst=6000` | output (`set_queue:0` when QoS on) | 30 s | background load packet-in |
| 100 | UDP, `in_port`, `ipv4_dst`, `udp_dst=5000` (request) | output (`set_queue:1` toward h1 when QoS on) | 20 s | first sync packet-in |
| 100 | UDP, `in_port`, `ipv4_src`, `ipv4_dst`, `udp_src=5000` (reply) | output | 20 s | first sync reply packet-in |
| 200 | same matches as the priority-100 sync flows | same actions | 20 s | congestion detected |

Two clients give four sync flows: one request flow and one reply flow per client. The reply flow also matches
`ipv4_dst` because its output port depends on which client the reply is for. A sync packet whose destination MAC is not
yet known is flooded and installs nothing.

### 4.2 Packet-in handling

1. Ignore LLDP; learn `mac_to_port[dpid][eth.src] = in_port`.
2. Classify: sync if it is IPv4/UDP with source or destination port 5000; background if destination port 6000.
3. Sync with a known out port: install the sync flow (priority 100, or 200 when congested). There is deliberately no
   "already installed" cache: a packet-in means no flow matched, and a cache goes stale when the idle timeout removes
   the flow. The controller reinstalls every time (idempotent).
4. Always send a packet-out for the packet that triggered the packet-in.

### 4.3 Congestion detection and priority escalation

The controller polls OpenFlow port statistics for **port 1 only** (toward h1, the shared bottleneck) every second.

- Enter *congested* when egress is at or above **15 Mbit/s**.
- Leave after **2 consecutive polls at or below 8 Mbit/s** (hysteresis, so the state does not flap).
- On a transition it moves every known sync flow to priority 200 (or back to 100) **proactively**: it installs the new
  flow first and then deletes the old one, so a sync packet always matches something.

Each transition logs a machine-readable `POLICY ... state=CONGESTED|CLEAR` line that the replay page and the checks read.

## 5. Why QoS is needed

OpenFlow priority only decides **which flow entry matches**. It does not change how packets wait in the egress queue.
Sync requests and the load both leave through `s1-eth1`, so with a single FIFO queue a request waits behind the load no
matter how high its flow priority is. The D2 evidence shows exactly that: with QoS off the priority-200 flows are
installed and the RTT still rises by about 42 ms.

With QoS on, the path is: controller emits `set_queue:1` on sync flows toward port 1, and OVS linux-htb gives queue 1 a
2 Mbit guaranteed minimum and higher priority than the default queue. Sync packets then skip the load's backlog.

## 6. Run order matters

The sync flow is installed **reactively** on a packet-in. If `pingall` runs first, it installs generic priority-10
link-layer flows (match on destination MAC) that already forward the later UDP sync packets, so the controller never sees
a packet-in for them and the sync flow is never installed. Correct order: controller, Mininet, server (background),
clients, `dump-flows`, and only then `pingall`. Installing sync flows proactively at switch-connect time would remove this
limitation; it is not done here.

## 7. What the results show

(From `evaluation/results/actual_sdn_results/`, 20 samples per test, one VM run. Full detail in
[D2_REPORT.md](D2_REPORT.md) and [../evaluation/RESULT_STATUS.md](../evaluation/RESULT_STATUS.md).)

| Test | Mean RTT | Mean absolute offset error |
|---|---:|---:|
| P1 baseline | 0.22 ms | 0.045 ms |
| P2 50 ms delay (25 ms on h1 and h2) | 51.87 ms | 0.540 ms |
| P3b overload, QoS off | 42.38 ms | 21.18 ms |
| P3b overload, QoS on | 0.03 ms | 0.006 ms |
| P4 load + delay, QoS off | 95.96 ms | 22.90 ms |
| P4 load + delay, QoS on | 50.10 ms | 0.011 ms |

Reading the table: symmetric delay (P2) raises RTT but barely moves the offset. Congestion on one path (P3b/P4 with QoS
off) raises RTT and also causes an offset error of about half the added delay, which is the `(d1 - d2)/2` term. QoS
removes the congestion part. The load was nominally 30M but measured about 19.5 Mbit/s at the sender, and no packets were
lost, so the "overload" is queueing delay, not loss.

## 8. Limitations

- Educational prototype, not NTP: one server, plain averaging in the D1 client, no peer selection or authentication.
- The controller classifies sync traffic by UDP port 5000 only, so other traffic on that port would be treated as sync.
- Congestion detection is a simple volume threshold on one port.
- All Mininet hosts share one kernel clock, so the "true error" used for checking would not exist on separate machines.
- Results are from a single VM run; the load generator did not reach its nominal rate (documented in `RESULT_STATUS.md`).
