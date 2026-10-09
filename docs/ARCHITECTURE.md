# Architecture

## Components

### 1. Reference Time Server
A UDP server on `10.0.0.1:5000`.

### 2. Synchronization Clients
Clients on `10.0.0.2` and `10.0.0.3`.

### 3. Open vSwitch
Mininet creates switch `s1` and uses OpenFlow 1.3.

### 4. Ryu Controller
The controller learns MAC addresses and installs forwarding rules.

### 5. Socket–SDN integration
The controller detects UDP packets whose destination port is `5000`.
It dynamically installs a higher-priority rule:

```text
priority 100
IPv4
UDP
destination port 5000
destination IP 10.0.0.1
```

Normal forwarding rules use priority 10.

## Four timestamps

```text
Client                         Server

T1  ---- synchronization ---->  T2
    <--------- response ------  T3
T4
```

### RTT

```text
RTT = (T4 - T1) - (T3 - T2)
```

### Clock offset

```text
Offset = ((T2 - T1) + (T3 - T4)) / 2
```

The project reports the estimated offset and RTT without changing the actual
Linux system clock.
