#!/usr/bin/env python3
"""One-command Track C Mininet/SDN execution (Ryu + Mininet + Open vSwitch).

Topology: s1 with h1 (time server), h2 (sync client), h3 (spare), h4 (background load).
Every link is shaped with TCLink so a real bottleneck exists whether or not netem is available:
  - h1 <-> s1 : BOTTLENECK_MBPS (20 Mbps)  <- shared by sync replies/requests and the load
  - h2,h3,h4 <-> s1 : EDGE_MBPS (100 Mbps)
Background load goes h4 -> h1 (UDP 6000), i.e. through the SAME s1->h1 egress queue as the
sync requests (h2 -> h1, UDP 5000). Load that exceeds BOTTLENECK_MBPS builds a queue there.

Tests
  P1  baseline
  P2  controlled delay (netem 25 ms on h1 and h2 -> ~50 ms RTT)      [SKIPPED without netem]
  P3a control: load UNDER capacity (10 Mbps on a 20 Mbps link)       -> no queue expected
  P3b load OVER capacity (30 Mbps on a 20 Mbps link)                 -> queue expected
  P4  load OVER capacity + delay                                     [SKIPPED without netem]
  P5  server down (0 successes expected)
  P6  server restarted (recovery)

A loaded test is only labelled "CONGESTION ACHIEVED" if its average RTT is >= 2x the matching
unloaded baseline AND at least +1 ms above it; otherwise it is "NO CONGESTION ACHIEVED".
Exit status is non-zero if any test FAILED, did not reach its test condition, or was inconclusive.
Results go to track_c/results/actual_sdn_results/.
"""
import csv, gzip, os, re, shutil, signal, statistics, subprocess, sys, time
from functools import partial
from pathlib import Path
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.log import setLogLevel, info

ROOT = Path(__file__).resolve().parents[2]   # repo root
OUT = ROOT/'track_c'/'results'/'actual_sdn_results'
RYU_APP = ROOT/'controller'/'d2_adaptive_controller.py'
SERVER = ROOT/'server_client'/'time_server.py'
EVAL = ROOT/'track_c'/'code'/'track_c_robustness_eval.py'
LOADGEN = ROOT/'server_client'/'load_generator.py'   # fallback only, when iperf is missing
PY = sys.executable                                    # stdlib-only scripts run with this

BOTTLENECK_MBPS = 20
EDGE_MBPS = 100
UNDER_LOAD_MBPS = 10          # < BOTTLENECK  (control)
OVER_LOAD_MBPS = 30           # > BOTTLENECK
LOAD_PORT = 6000
LOAD_HEAD_START_S = 2         # load runs this long before the sync client starts sampling
LOAD_MAX_S = 40               # iperf -t (client is stopped as soon as the sampling ends)
SAMPLES, INTERVAL_S, TIMEOUT_S, SKEW_MS = 20, 0.1, 2, 100
CONGESTION_RATIO, CONGESTION_MIN_ADD_MS = 2.0, 1.0   # sanity check D
DELAY_MIN_ADD_MS = 30.0       # P2 must add at least this much RTT over baseline (expected ~50)
CTRL_PKT_WARN = 10            # table-miss packets during a test above this -> flag

RESULTS = []                  # dicts: name, status, ok, total, rtt, ratio, loss, err, note
STATS = {}


class TopoC(Topo):
    def build(self):
        s = self.addSwitch('s1', protocols='OpenFlow13')
        for i in range(1, 5):
            self.addHost(f'h{i}', ip=f'10.0.0.{i}/24')
        for i in range(1, 5):
            self.addLink(f'h{i}', s, cls=TCLink, bw=BOTTLENECK_MBPS if i == 1 else EDGE_MBPS)


def run(cmd, log=None, timeout=None):
    p = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if log:
        Path(log).write_text(p.stdout)
    return p.returncode, p.stdout


def netem_available():
    # tc netem needs the sch_netem kernel module; some VMs/containers lack it.
    rc, _ = run('ip netns add _tcprobe && ip netns exec _tcprobe ip link add v0 type veth peer name v1 '
                '&& ip netns exec _tcprobe tc qdisc add dev v0 root netem delay 1ms; r=$?; ip netns del _tcprobe 2>/dev/null; exit $r')
    return rc == 0


def kernel_datapath_available():
    rc, _ = run('ovs-dpctl show')   # fails if the OVS kernel module is not loaded
    return rc == 0


def netem_on(host, delay_ms):
    # Attach netem under Mininet's htb leaf (5:1) so the bandwidth shaping is preserved.
    host.cmd(f'tc qdisc replace dev {host.name}-eth0 parent 5:1 handle 10: netem delay {delay_ms}ms')
    return 'netem' in host.cmd(f'tc qdisc show dev {host.name}-eth0')


def netem_off(host):
    host.cmd(f'tc qdisc del dev {host.name}-eth0 parent 5:1 handle 10: 2>/dev/null || true')


def table_miss_pkts():
    _, txt = run('ovs-ofctl -O OpenFlow13 dump-flows s1')
    for line in txt.splitlines():
        if 'priority=0 ' in line or line.rstrip().endswith('priority=0 actions=CONTROLLER:65535'):
            m = re.search(r'n_packets=(\d+)', line)
            if m:
                return int(m.group(1))
    return 0


def evidence_dump(name):
    """Snapshot taken while the load is (hopefully) still running."""
    parts = []
    for title, cmd in [('ovs-ofctl dump-flows s1', 'ovs-ofctl -O OpenFlow13 dump-flows s1'),
                       ('ovs-ofctl dump-ports s1', 'ovs-ofctl -O OpenFlow13 dump-ports s1'),
                       ('tc -s qdisc show dev s1-eth1 (bottleneck egress toward h1)', 'tc -s qdisc show dev s1-eth1')]:
        parts.append(f'### {title}\n{run(cmd)[1]}')
    (OUT/f'evidence_{name}_during_load.txt').write_text('\n'.join(parts))


def csv_stats(csvp):
    rows = list(csv.DictReader(open(csvp))) if Path(csvp).exists() else []
    ok = [r for r in rows if r['status'] == 'OK']
    s = {'total': len(rows), 'ok': len(ok), 'rtt': None, 'rtt_max': None, 'err': None, 'offset': None}
    if ok:
        rtts = [float(r['rtt_ms']) for r in ok]
        s.update(rtt=statistics.mean(rtts), rtt_max=max(rtts),
                 err=statistics.mean(float(r['abs_error_ms']) for r in ok),
                 offset=statistics.mean(float(r['offset_ms']) for r in ok))
    return s


def iperf_server_summary(logpath):
    """Mean per-second received rate / loss from the iperf server log (1 s intervals only)."""
    rates, losses = [], []
    if not Path(logpath).exists():
        return None, None
    for line in Path(logpath).read_text().splitlines():
        m = re.search(r'\]\s+(\d+\.\d+)\s*-\s*(\d+\.\d+)\s+sec.*?(\d+\.?\d*)\s+Mbits/sec.*?\((\d+\.?\d*)%\)', line)
        if m and float(m.group(2)) - float(m.group(1)) <= 1.05:
            rates.append(float(m.group(3))); losses.append(float(m.group(4)))
    if not rates:
        return None, None
    return statistics.mean(rates), statistics.mean(losses)


def record(name, status, s=None, base=None, note=''):
    s = s or {}
    rtt = s.get('rtt')
    ratio = (rtt/base) if (rtt is not None and base) else None
    loss = (100.0*(s['total']-s['ok'])/s['total']) if s.get('total') else None
    RESULTS.append(dict(name=name, status=status, ok=s.get('ok', 0), total=s.get('total', 0),
                        rtt=rtt, ratio=ratio, loss=loss, err=s.get('err'), note=note))
    info(f'*** {name}: {status}\n')


def run_evaluator(host, name, test, samples=SAMPLES):
    csvp = OUT/f'{name}.csv'
    csvp.unlink(missing_ok=True)
    cmd = (f'{PY} {EVAL} --test {test} --server 10.0.0.1 --samples {samples} --interval {INTERVAL_S} '
           f'--timeout {TIMEOUT_S} --skew-ms {SKEW_MS} --csv {csvp}')
    txt = host.cmd(cmd)            # host.cmd() already executes the command and returns its stdout
    (OUT/f'{name}.txt').write_text(txt)
    return csv_stats(csvp)


def start_load(net, name, rate_mbps, use_iperf):
    """Start load h4 -> h1:6000. Returns (server_proc, client_proc, server_log_path)."""
    h1, h4 = net['h1'], net['h4']
    slog = OUT/f'{name}_iperf_server.log'
    clog = OUT/f'{name}_load_client.log'
    if use_iperf:
        srv = h1.popen(['iperf', '-s', '-u', '-p', str(LOAD_PORT), '-i', '1'], stdout=open(slog, 'w'), stderr=subprocess.STDOUT)
        time.sleep(1)
        cli = h4.popen(['iperf', '-c', '10.0.0.1', '-u', '-p', str(LOAD_PORT), '-b', f'{rate_mbps}M',
                        '-t', str(LOAD_MAX_S), '-l', '1470', '-i', '1'], stdout=open(clog, 'w'), stderr=subprocess.STDOUT)
    else:
        srv = None
        pps = int(rate_mbps*1e6/(1470*8))
        cli = h4.popen([PY, str(LOADGEN), '10.0.0.1', '--port', str(LOAD_PORT), '--pps', str(pps),
                        '--duration', str(LOAD_MAX_S), '--size', '1470'], stdout=open(clog, 'w'), stderr=subprocess.STDOUT)
    return srv, cli, slog


def stop_load(srv, cli):
    for p in (cli, srv):
        if p and p.poll() is None:
            try:
                p.send_signal(signal.SIGINT)   # iperf flushes its log and prints a summary on SIGINT
                p.wait(timeout=5)
            except Exception:
                p.kill()


def loaded_test(net, ryu_log, name, rate_mbps, use_iperf, base_rtt, base_label, delay=False):
    h2 = net['h2']
    srv, cli, slog = start_load(net, name, rate_mbps, use_iperf)
    time.sleep(LOAD_HEAD_START_S)
    off0 = ryu_log.stat().st_size
    miss0 = table_miss_pkts()
    s = run_evaluator(h2, name, 'load_delay' if delay else 'load')
    still_running = cli.poll() is None
    evidence_dump(name)
    miss = table_miss_pkts() - miss0
    off1 = ryu_log.stat().st_size
    stop_load(srv, cli)
    time.sleep(1)
    rx, lossp = iperf_server_summary(slog) if use_iperf else (None, None)
    with open(ryu_log, 'rb') as f:
        f.seek(off0); sliced = f.read(off1-off0).decode(errors='replace')
    keep = [l for l in sliced.splitlines() if re.search(r'sync priority policy|SYNC FLOW|SWITCH CONNECTED', l)]
    (OUT/f'policy_{name}.txt').write_text('\n'.join(keep)+'\n')
    note = (f'load={rate_mbps}M offered, server_rx={rx:.1f}Mbps loss={lossp:.1f}%' if rx is not None else f'load={rate_mbps}M offered')
    note += f', load_still_running_at_dump={still_running}, controller_pkts={miss}'
    if miss > CTRL_PKT_WARN:
        note += ' (WARNING: traffic took the controller path)'
    if not still_running:
        note += ' (WARNING: load ended before sampling finished)'
    return s, note


def judge_loaded(name, s, base, base_label, note, expect_congestion):
    if s['ok'] == 0 or not base:
        record(name, 'INCONCLUSIVE (no samples or no baseline)', s, base, note)
        return
    ratio = s['rtt']/base
    congested = s['rtt'] >= CONGESTION_RATIO*base and (s['rtt']-base) >= CONGESTION_MIN_ADD_MS
    desc = f'avg RTT {s["rtt"]:.2f} ms = {ratio:.1f}x {base_label} ({base:.2f} ms)'
    if expect_congestion:
        record(name, ('CONGESTION ACHIEVED' if congested else 'NO CONGESTION ACHIEVED')+f' [{desc}]', s, base, note)
    else:
        record(name, ('CONTROL OK - no congestion, as expected' if not congested
                      else 'CONTROL UNEXPECTED - congestion at under-capacity load')+f' [{desc}]', s, base, note)


def write_summary(env_lines):
    lines = []
    for r in RESULTS:
        f = lambda v, fmt: ('-' if v is None else fmt % v)
        lines.append(f"{r['name']:16s} {r['status']}\n    samples_ok={r['ok']}/{r['total']}  loss%={f(r['loss'], '%.0f')}  "
                     f"avg_rtt_ms={f(r['rtt'], '%.3f')}  rtt_x_baseline={f(r['ratio'], '%.1f')}  mean_abs_offset_err_ms={f(r['err'], '%.3f')}"
                     + (f"\n    {r['note']}" if r['note'] else ''))
    text = '\n'.join(lines)+'\n\n'+'\n'.join(env_lines)+'\n'
    (OUT/'SUMMARY.txt').write_text(text)
    return text


def main():
    ryu_cmd = os.environ.get('TRACKC_RYU_MANAGER') or shutil.which('ryu-manager')
    if not ryu_cmd:
        sys.exit('ERROR: ryu-manager not found (set TRACKC_RYU_MANAGER=/path/to/ryu-manager)')
    if OUT.exists():
        shutil.rmtree(OUT)          # results folder is regenerated on every run (CSV writer appends)
    OUT.mkdir(parents=True)

    shaped_delay = netem_available()
    dp = 'kernel' if kernel_datapath_available() else 'user'
    iperf = shutil.which('iperf')
    ovs_ver = run('ovs-vsctl --version | head -1')[1].strip()
    env_lines = [f'netem_available={shaped_delay}', f'ovs_datapath={dp}', f'ovs={ovs_ver}',
                 f'load_tool={"iperf" if iperf else "python load_generator.py (iperf not found: rate may not reach target)"}',
                 f'bottleneck_mbps(h1 link)={BOTTLENECK_MBPS}', f'edge_mbps(h2,h3,h4 links)={EDGE_MBPS}',
                 f'under_load_mbps={UNDER_LOAD_MBPS}', f'over_load_mbps={OVER_LOAD_MBPS}',
                 f'python={sys.version.split()[0]}', f'ryu_manager={ryu_cmd}']
    (OUT/'environment.txt').write_text('\n'.join(env_lines)+'\n')
    info('*** '+'; '.join(env_lines[:4])+'\n')

    ryu = server = net = None
    ryu_f = server_f = None
    ryu_log = OUT/'ryu_controller.log'
    try:
        info('*** Starting Ryu controller\n')
        ryu_f = open(ryu_log, 'w')
        ryu = subprocess.Popen([ryu_cmd, str(RYU_APP)], stdout=ryu_f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        time.sleep(4)
        net = Mininet(topo=TopoC(), switch=partial(OVSSwitch, datapath=dp), controller=None,
                      autoSetMacs=True, autoStaticArp=True, link=TCLink)
        net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
        net.start(); time.sleep(3)
        h1, h2 = net['h1'], net['h2']
        if dp == 'user':
            # OVS userspace (netdev) datapath: veth TX checksum offload leaves UDP checksums
            # unfinished, so receivers drop UDP (ICMP still works). Turn offload off on hosts.
            for h in net.hosts:
                h.cmd(f'ethtool -K {h.name}-eth0 tx off rx off 2>/dev/null')
        # No pingAll here on purpose: it would install generic priority-10 L2 flows that then
        # carry the UDP/5000 traffic and hide the controller's priority-100/200 sync flow.

        info('*** Starting Track A server on h1\n')
        server_f = open(OUT/'server.log', 'w')
        server = h1.popen([PY, '-u', str(SERVER), '--host', '10.0.0.1', '--port', '5000'], stdout=server_f, stderr=subprocess.STDOUT)
        time.sleep(2)

        # ---- P1 baseline
        info('*** P1 baseline\n')
        s = run_evaluator(h2, 'P1_baseline', 'baseline')
        STATS['P1'] = s
        base = s['rtt']
        record('P1_baseline', 'PASS' if s['ok'] > 0 else 'FAIL (no samples)', s)

        # ---- P2 delay
        delay_base = None
        if shaped_delay:
            info('*** P2 controlled delay: 25 ms on h1 + h2 (~50 ms RTT)\n')
            applied = netem_on(h1, 25) and netem_on(h2, 25)
            s = run_evaluator(h2, 'P2_delay', 'delay'); netem_off(h1); netem_off(h2)
            delay_base = s['rtt']
            if not applied:
                record('P2_delay', 'FAIL (netem not applied)', s)
            elif s['ok'] == 0 or base is None:
                record('P2_delay', 'INCONCLUSIVE (no samples)', s, base)
            elif s['rtt'] - base >= DELAY_MIN_ADD_MS:
                record('P2_delay', f'DELAY ACHIEVED [avg RTT {s["rtt"]:.2f} ms vs baseline {base:.2f} ms]', s, base)
            else:
                record('P2_delay', f'FAIL - DELAY NOT ACHIEVED [avg RTT {s["rtt"]:.2f} ms vs baseline {base:.2f} ms]', s, base)
        else:
            info('*** P2 SKIPPED: tc netem not available in this kernel\n')
            record('P2_delay', 'SKIPPED (no netem kernel module)', None, None, 'delay tests need netem; run on a machine that has it')

        # ---- P3a control: load under capacity
        info(f'*** P3a control: {UNDER_LOAD_MBPS} Mbps load on a {BOTTLENECK_MBPS} Mbps link\n')
        s, note = loaded_test(net, ryu_log, 'P3a_load_under', UNDER_LOAD_MBPS, bool(iperf), base, 'P1 baseline')
        judge_loaded('P3a_load_under', s, base, 'P1 baseline', note, expect_congestion=False)

        # ---- P3b load over capacity
        info(f'*** P3b: {OVER_LOAD_MBPS} Mbps load on a {BOTTLENECK_MBPS} Mbps link\n')
        s, note = loaded_test(net, ryu_log, 'P3b_load_over', OVER_LOAD_MBPS, bool(iperf), base, 'P1 baseline')
        judge_loaded('P3b_load_over', s, base, 'P1 baseline', note, expect_congestion=True)
        STATS['P3b'] = s

        # ---- P4 load over capacity + delay
        if shaped_delay:
            info('*** P4: over-capacity load + delay\n')
            applied = netem_on(h1, 25) and netem_on(h2, 25)
            s, note = loaded_test(net, ryu_log, 'P4_load_delay', OVER_LOAD_MBPS, bool(iperf), delay_base, 'P2 delay-only baseline', delay=True)
            netem_off(h1); netem_off(h2)
            if not applied:
                record('P4_load_delay', 'FAIL (netem not applied)', s, delay_base, note)
            else:
                judge_loaded('P4_load_delay', s, delay_base, 'P2 delay-only baseline', note, expect_congestion=True)
        else:
            info('*** P4 SKIPPED: tc netem not available in this kernel\n')
            record('P4_load_delay', 'SKIPPED (no netem kernel module)', None, None, 'load+delay test needs netem')

        # ---- P5 / P6 recovery (unchanged logic)
        info('*** Recovery: stop server, verify failures, restart, verify recovery\n')
        server.terminate(); server.wait(timeout=5); server_f.close()
        s = run_evaluator(h2, 'P5_recovery_down', 'recovery', samples=SAMPLES)
        record('P5_recovery_down', 'PASS' if s['total'] > 0 and s['ok'] == 0 else 'FAIL (expected 0 successes)', s)
        server_f = open(OUT/'server_restarted.log', 'w')
        server = h1.popen([PY, '-u', str(SERVER), '--host', '10.0.0.1', '--port', '5000'], stdout=server_f, stderr=subprocess.STDOUT)
        time.sleep(2)
        s = run_evaluator(h2, 'P6_recovery_up', 'recovery')
        record('P6_recovery_up', 'PASS' if s['ok'] > 0 else 'FAIL (no samples)', s)
        run('ovs-ofctl -O OpenFlow13 dump-flows s1', OUT/'flows_final.txt')

        text = write_summary(env_lines)
        info('*** SUMMARY\n'+text)
        info(f'*** DONE. Results saved to {OUT}\n')
    finally:
        for p in (server, ryu):
            if p and p.poll() is None:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM) if p is ryu else p.terminate()
                except Exception:
                    pass
        for f in (ryu_f, server_f):
            try:
                f and f.close()
            except Exception:
                pass
        if net:
            try:
                net.stop()
            except Exception:
                pass
    # evidence: policy lines for the whole run, and the full Ryu log (gzip if large)
    try:
        txt = ryu_log.read_text(errors='replace')
        (OUT/'policy_lines_all.txt').write_text(
            '\n'.join(l for l in txt.splitlines() if re.search(r'sync priority policy|SYNC FLOW|SWITCH CONNECTED', l))+'\n')
        if ryu_log.stat().st_size > 200_000:
            with gzip.open(str(ryu_log)+'.gz', 'wt') as g:
                g.write(txt)
            ryu_log.unlink()
    except Exception as e:
        info(f'*** could not post-process Ryu log: {e}\n')
    bad = [r for r in RESULTS if re.match(r'(FAIL|NO CONGESTION|INCONCLUSIVE|CONTROL UNEXPECTED)', r['status'])]
    if bad:
        info('*** NOT ALL TEST CONDITIONS WERE MET: '+', '.join(r['name'] for r in bad)+'\n')
        sys.exit(1)


if __name__ == '__main__':
    setLogLevel('info')
    main()
