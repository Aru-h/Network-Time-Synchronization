#!/usr/bin/env python3
"""Diagnostic: why did the iperf load send ~19.5 Mbit/s when 30M was requested?

Run on the Ubuntu VM (needs root and the system Python that has Mininet):
    sudo mn -c
    sudo python3 evaluation/ubuntu_runner/diagnose_load_rate.py

It builds the same shaped topology as the evaluation (h1 = 20 Mbps bottleneck, h2/h3/h4 = 100 Mbps) but uses a plain
OVS learning bridge (no Ryu), so the controller is out of the picture. It then runs iperf UDP sender tests and prints,
for each, what the SENDER achieved (datagrams x 1470 B / client duration), what the server received, and the qdisc
state. Nothing under results/ is written; the full text is printed and saved to /tmp/diagnose_load_rate.txt.

Cases (all h4 -> target, 5 s, -l 1470):
  A  h3, 10M    sender target well below every link rate        (reference)
  B  h3, 30M    path has NO bottleneck (100 Mbps links)         <- does the sender reach 30M with no queue?
  C  h1, 10M    path crosses the 20 Mbps bottleneck, below it   (same as P3a)
  D  h1, 30M    path crosses the 20 Mbps bottleneck, above it   (same as P3b)
  E  h3, 60M    sender target above the evaluation's request    (is there a general ~20 Mbit/s sender cap?)

How to read it (no conclusion is drawn by the script):
  - If B reaches ~30M but D stays ~19.5M, the sender slows down only when the path has a bottleneck.
  - If B also stays ~19.5M (and E too), the sender is limited independently of the bottleneck (iperf pacing / VM).
"""
import os, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mininet.net import Mininet
from mininet.node import OVSBridge
from mininet.log import setLogLevel
import run_mininet_tests as rt          # reuses TopoC / ShapedLink / datapath probe; importing has no side effects

DURATION_S = 5
PORT = 6000
CASES = [('A', 'h3', 10), ('B', 'h3', 30), ('C', 'h1', 10), ('D', 'h1', 30), ('E', 'h3', 60)]
OUTFILE = '/tmp/diagnose_load_rate.txt'
lines = []


def say(s=''):
    print(s, flush=True)
    lines.append(s)


def sh(cmd):
    return subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.strip()


def main():
    if os.geteuid() != 0:
        sys.exit('ERROR: run as root (sudo)')
    if not shutil.which('iperf'):
        sys.exit('ERROR: iperf not installed (sudo apt install -y iperf)')
    dp = 'kernel' if rt.kernel_datapath_available() else 'user'
    say('== environment ==')
    say('kernel      : ' + sh('uname -r'))
    say('python      : ' + sys.version.split()[0])
    say('iperf       : ' + sh('iperf --version 2>&1 | head -1'))
    say('ovs         : ' + sh('ovs-vsctl --version | head -1') + f' (datapath={dp})')
    say('cpus        : ' + str(os.cpu_count()))
    say(f'topology    : h1 link {rt.BOTTLENECK_MBPS} Mbps, h2/h3/h4 links {rt.EDGE_MBPS} Mbps, htb r2q {rt.HTB_R2Q}')
    say('switch      : OVSBridge (learning switch, no Ryu)')
    say()

    net = Mininet(topo=rt.TopoC(), switch=lambda name, **kw: OVSBridge(name, datapath=dp, **kw),
                  controller=None, autoSetMacs=True, autoStaticArp=True, link=rt.ShapedLink)
    try:
        net.start(); time.sleep(3)
        if dp == 'user':
            for h in net.hosts:
                h.cmd(f'ethtool -K {h.name}-eth0 tx off rx off 2>/dev/null')
        h4 = net['h4']
        say('== results (sender rate = datagrams x 1470 B x 8 / client duration) ==')
        say(f"{'case':4s} {'target':7s} {'req':>4s} {'sent':>6s} {'client_s':>8s} {'sender_Mbit/s':>13s} "
            f"{'server_rx_Mbit/s':>16s} {'lost/total':>12s}")
        details = []
        for case, tname, mbps in CASES:
            target = net[tname]
            tip = target.IP()
            srv = target.popen(['iperf', '-s', '-u', '-p', str(PORT), '-i', '1'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            time.sleep(1)
            cli = h4.cmd(f'iperf -c {tip} -u -p {PORT} -b {mbps}M -t {DURATION_S} -l 1470 -i 1')
            time.sleep(1.5)
            srv.terminate()
            try:
                sout = srv.communicate(timeout=5)[0]
            except subprocess.TimeoutExpired:
                srv.kill(); sout = srv.communicate()[0]
            m_sent = re.search(r'Sent (\d+) datagrams', cli)
            m_dur = re.findall(r'0\.0+-\s*([\d.]+) sec', cli)
            sent = int(m_sent.group(1)) if m_sent else None
            dur = float(m_dur[-1]) if m_dur else None
            sender = sent * 1470 * 8 / dur / 1e6 if sent and dur else None
            m_srv = re.findall(r'0\.0+-\s*[\d.]+ sec\s+[\d.]+ \w+\s+([\d.]+) Mbits/sec\s+[\d.]+ ms\s+(\d+)/\s*(\d+)', sout)
            srv_rx, lost, total = (float(m_srv[-1][0]), m_srv[-1][1], m_srv[-1][2]) if m_srv else (None, '?', '?')
            f = lambda v, fmt: '-' if v is None else fmt % v
            say(f"{case:4s} {tname + '(' + tip + ')':7s} {mbps:3d}M {f(sent, '%d'):>6s} {f(dur, '%.2f'):>8s} "
                f"{f(sender, '%.2f'):>13s} {f(srv_rx, '%.2f'):>16s} {lost + '/' + total:>12s}")
            details.append((case, tname, mbps, cli, sout,
                            h4.cmd('tc -s qdisc show dev h4-eth0'), net['s1'].cmd('tc -s qdisc show dev s1-eth%d' % (int(tname[1:])))))
        say()
        say('== raw iperf client output and qdisc counters per case ==')
        for case, tname, mbps, cli, sout, q4, qs in details:
            say(f'--- case {case}: h4 -> {tname} at {mbps}M ---')
            say('[client]'); say(cli.strip())
            say('[server]'); say(sout.strip())
            say('[tc -s qdisc h4-eth0]'); say(q4.strip())
            say(f'[tc -s qdisc s1-eth{tname[1:]}]'); say(qs.strip())
            say()
    finally:
        net.stop()
        Path(OUTFILE).write_text('\n'.join(lines) + '\n')
        print(f'(saved to {OUTFILE})')


if __name__ == '__main__':
    setLogLevel('warning')
    main()
