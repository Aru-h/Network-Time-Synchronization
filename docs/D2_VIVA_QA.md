# D2 Viva Questions

### What makes your SDN functionality dynamic?
The controller periodically requests port statistics and changes the
synchronization priority policy based on measured traffic volume.

### How do you identify synchronization traffic?
UDP destination port 5000.

### How do you identify background traffic?
The experiment uses UDP destination port 6000.

### What happens during congestion?
The controller detects increased traffic and can install the synchronization
flow with priority 200 instead of the normal priority 100.

### Why use OpenFlow priorities?
A higher matching priority lets the synchronization-specific rule take
precedence over generic forwarding rules.

### How did you test robustness?
We tested added delay, background traffic, and server stop/restart.

### What performance metrics did you measure?
RTT, estimated offset, mean absolute offset error and timeouts.

### What is the baseline?
The same synchronization workload under normal forwarding without the
D2-specific adaptive priority policy.

### Does priority alone guarantee bandwidth?
No. OpenFlow priority controls rule selection; it is not by itself a
guaranteed bandwidth reservation. Production QoS would require queues,
metering or other mechanisms.

### Is this full NTP?
No. It is a simplified educational four-timestamp synchronization system.
