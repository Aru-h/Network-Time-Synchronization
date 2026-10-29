# Experimental Results

Fill these values from your actual D1 demo.

| Test | Network condition | Skew | Samples | Avg RTT (ms) | Avg Offset (ms) | Mean Error (ms) |
|---|---|---:|---:|---:|---:|---:|
| T1 | No extra delay | +100 ms | 10 | | | |
| T2 | No extra delay | -50 ms | 10 | | | |
| T3 | 50 ms netem delay | +100 ms | 10 | | | |

## Evidence checklist

- [ ] Ryu controller running
- [ ] Mininet topology running
- [ ] pingall successful
- [ ] Server output captured
- [ ] Client output captured
- [ ] `SYNC FLOW INSTALLED` visible
- [ ] OpenFlow flow table captured
- [ ] Delay experiment captured
