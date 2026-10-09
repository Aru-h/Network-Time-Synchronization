# Network Time Synchronization System — D2 Report

## 1. D2 Scope

D2 extends D1 from a working socket/SDN prototype into a tested system with
dynamic SDN behavior, challenging conditions, performance measurements and
recovery testing.

## 2. Complete Application Functionality

The application supports:

- reference UDP time server
- multiple synchronization clients
- four timestamp exchange
- RTT calculation
- clock-offset estimation
- simulated client clock skew
- controlled network delay
- synchronization flow installation
- background UDP traffic
- controller monitoring
- dynamic synchronization-flow priority
- failure and recovery testing

## 3. Dynamic SDN Functionality

The D2 Ryu controller periodically requests OpenFlow port statistics.

It compares traffic volume with a threshold.

Policy:

```text
Normal traffic:
    sync priority = 100

High traffic:
    sync priority = 200
```

The controller also classifies background UDP traffic on port 6000 separately
from synchronization UDP traffic on port 5000.

Evidence:

```text
DYNAMIC SDN: ...
DYNAMIC SYNC FLOW: ... priority=200
BACKGROUND TRAFFIC: ...
```

This demonstrates controller behavior based on observed network conditions.

## 4. Challenging Scenarios

### A. Congestion
A background UDP generator sends high-rate traffic while synchronization runs.

### B. Added delay
Linux `netem` adds controlled delay to the client interface.

### C. Server failure and recovery
The time server is stopped, the client experiences timeouts, and the server
is restarted. Successful synchronization after restart demonstrates recovery.

## 5. Performance Evaluation

Collect:

- average RTT
- average estimated offset
- mean absolute offset error
- successful samples
- timeout/loss count

Run at least these conditions:

| Test | Condition | Skew | Samples | Avg RTT | Avg Offset | Error | Timeouts |
|---|---|---:|---:|---:|---:|---:|---:|
| P1 | Normal | +100 ms | 20 | | | | |
| P2 | 50 ms delay | +100 ms | 20 | | | | |
| P3 | Background load | +100 ms | 20 | | | | |
| P4 | Load + delay | +100 ms | 20 | | | | |

Use actual measurements from the Ubuntu/Mininet run.

## 6. Baseline vs SDN-Controlled Comparison

For a defensible comparison:

### Baseline
Run the same synchronization test before applying the SDN-specific
priority policy or with only normal forwarding.

### SDN-controlled
Run it with the D2 controller and verify the UDP/5000 priority flow.

Compare the measured RTT, error and timeouts under the same traffic condition.

Do not invent values; record the values produced by the experiments.

## 7. Reproducibility

Required:

- Ubuntu
- Mininet
- Open vSwitch
- Ryu
- project source
- controller command
- topology command
- experiment commands

## 8. D2 Rubric Mapping

| D2 item | Evidence |
|---|---|
| Complete Application Functionality (4) | Server/client + multi-client + calculations |
| Dynamic SDN Functionality (6) | Port monitoring + dynamic priority + traffic classification |
| Challenging Scenario / Robustness (4) | congestion + delay + failure/recovery |
| Performance Evaluation & Comparison (5) | controlled experiments + baseline comparison |
| Documentation, Final Demo & Viva (6) | D1/D2 reports + demo script + viva Q&A |

## 9. Limitations

This remains an educational prototype rather than production NTP. The dynamic
controller uses a simple traffic-volume threshold and does not claim to be a
complete enterprise routing/QoS system.
