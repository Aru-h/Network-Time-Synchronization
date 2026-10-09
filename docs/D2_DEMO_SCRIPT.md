# D2 Final Demo Script

## 1. Show architecture
Explain h1/h2/h3/h4, s1, OVS, Ryu and UDP ports 5000/6000.

## 2. Show normal synchronization
Run a client and show RTT, offset and error.

## 3. Show multiple clients
Run h2 and h3 with different simulated skew.

## 4. Show dynamic SDN
Start background traffic from h4.

Point to the Ryu terminal and explain:
- controller receives port statistics
- traffic crosses the threshold
- synchronization policy changes
- high-priority UDP/5000 flow is installed

Then show:

```bash
sh ovs-ofctl -O OpenFlow13 dump-flows s1
```

## 5. Challenging scenario
Add 50 ms netem delay and repeat synchronization.

## 6. Failure and recovery
Stop server, show client timeouts, restart server and show successful
synchronization.

## 7. Performance
Show the results table with actual measured numbers and explain the
difference between normal, delay, load and load+delay conditions.

## 8. Final statement
"Our D2 extends D1 with dynamic SDN monitoring and prioritization, challenging
network conditions, recovery testing, and quantitative performance evaluation."
