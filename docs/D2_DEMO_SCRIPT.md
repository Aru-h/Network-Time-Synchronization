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
- high-priority UDP/5000 flow is installed (only when the sync flow is
  (re)installed: leave the clients idle for more than 20 s before the load so
  the priority-100 sync flows expire; a flow that is still alive keeps
  priority 100)

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
"Our D2 extends D1 with dynamic SDN monitoring and a traffic-dependent
flow-priority policy, challenging network conditions, recovery testing, and
quantitative performance evaluation."

Do not claim that the priority-200 policy reduces synchronization delay under
congestion: sync and load traffic share one FIFO queue, and the measured P3b
RTT still rose by about 42 ms.
