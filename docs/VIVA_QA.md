# D1 Viva Questions and Answers

### 1. Why did you use UDP?
UDP avoids TCP connection setup and is suitable for small request/response
messages where low overhead is useful.

### 2. Why not change the real system clock?
Changing the OS clock requires privileged access and can disturb the machine.
We simulate skew and calculate the correction instead.

### 3. What are T1, T2, T3, T4?
T1 = client request send time.
T2 = server request receive time.
T3 = server response send time.
T4 = client response receive time.

### 4. Formula for RTT?
`RTT = (T4-T1) - (T3-T2)`.

### 5. Formula for clock offset?
`Offset = ((T2-T1) + (T3-T4))/2`.

### 6. What is Mininet?
Mininet creates lightweight virtual hosts, switches and links so a network
can be tested on one Linux machine.

### 7. What is SDN?
Software-Defined Networking separates network control logic from forwarding
and allows a controller to program switch behavior.

### 8. What is Ryu?
Ryu is a Python SDN controller framework that can communicate with OpenFlow
switches.

### 9. What is OpenFlow?
OpenFlow is a protocol used by an SDN controller to communicate forwarding
rules to compatible switches.

### 10. How does your controller recognize time synchronization traffic?
It matches IPv4 UDP packets whose destination port is 5000.

### 11. Why is the synchronization flow priority 100?
Normal learned forwarding uses priority 10. A higher priority makes the
specific synchronization rule selected first.

### 12. How did you demonstrate socket-SDN integration?
The actual UDP time synchronization packets travel through the Mininet OVS
switch, and the Ryu controller detects them and installs the synchronization
flow.

### 13. What happens when delay is increased?
The measured RTT generally increases. Timestamp-based offset estimation is
still calculated from the four timestamps.

### 14. Does this implement full NTP?
No. It implements the core four-timestamp synchronization calculation for an
educational SDN/socket project.

### 15. What happens if the server is down?
The client times out and reports failed synchronization samples.
