#!/usr/bin/env python3
"""One-command Track C Mininet/SDN execution.
Starts Ryu + Mininet, runs baseline/delay/load/load+delay/recovery tests,
and saves logs/CSV under track_c/results/actual_sdn_results.
"""
import csv, os, signal, subprocess, sys, time
from functools import partial
from pathlib import Path
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.topo import Topo
from mininet.link import TCLink, Link
from mininet.log import setLogLevel, info

ROOT=Path(__file__).resolve().parents[2]   # repo root
OUT=ROOT/'track_c'/'results'/'actual_sdn_results'; OUT.mkdir(parents=True, exist_ok=True)
RYU=ROOT/'controller'/'d2_adaptive_controller.py'
SERVER=ROOT/'server_client'/'time_server.py'
EVAL=ROOT/'track_c'/'code'/'track_c_robustness_eval.py'
LOAD=ROOT/'server_client'/'load_generator.py'

class TopoC(Topo):
    def build(self, shaped=True):
        s=self.addSwitch('s1', protocols='OpenFlow13')
        for i in range(1,5): self.addHost(f'h{i}', ip=f'10.0.0.{i}/24')
        for i in range(1,5):
            if shaped: self.addLink(f'h{i}', s, cls=TCLink, bw=20, delay='1ms')
            else:      self.addLink(f'h{i}', s)

def run(cmd, log=None, timeout=None):
    p=subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    if log: Path(log).write_text(p.stdout)
    return p.returncode, p.stdout

def netem_available():
    # tc netem needs the sch_netem kernel module; some VMs/containers lack it.
    rc,_=run('ip netns add _tcprobe && ip netns exec _tcprobe ip link add v0 type veth peer name v1 '
             '&& ip netns exec _tcprobe tc qdisc add dev v0 root netem delay 1ms; r=$?; ip netns del _tcprobe 2>/dev/null; exit $r')
    return rc==0

def kernel_datapath_available():
    # Open vSwitch kernel module present? If not, fall back to the userspace (netdev) datapath.
    rc,_=run('ovs-dpctl show')
    return rc==0

def start_proc(cmd, logfile):
    f=open(logfile,'w'); return subprocess.Popen(cmd, shell=True, stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid), f

def qdisc(host, delay_ms):
    host.cmd(f'tc qdisc replace dev {host.name}-eth0 root netem delay {delay_ms}ms')

def clear_qdisc(host): host.cmd(f'tc qdisc del dev {host.name}-eth0 root 2>/dev/null || true')

def evaluator(host, server_ip, name, test, expect_ok=True, note=''):
    """Run the Track C evaluator on a Mininet host and save its output.
    host.cmd() already executes the command on the host and returns stdout, so do NOT
    pass it back into run(). `test` is the required --test argument of the evaluator.
    Returns True if the result matches expectation (expect_ok=False for the server-down test)."""
    out=OUT/f'{name}.txt'; csvp=OUT/f'{name}.csv'
    cmd=f'python3 {EVAL} --test {test} --server {server_ip} --samples 20 --interval 0.1 --timeout 2 --skew-ms 100 --csv {csvp}'
    txt=host.cmd(cmd)
    out.write_text(txt)
    ran = 'TRACK C ROBUSTNESS EVALUATION' in txt
    ok_count = 0
    for line in txt.splitlines():
        if line.startswith('Successful'): ok_count=int(line.split(':')[1])
    good = ran and ((ok_count>0) if expect_ok else (ok_count==0))
    label = 'PASS' if good else 'FAIL'
    if good and note: label += f' ({note})'
    RESULTS.append((name, label, ok_count))
    if not good: info(f'*** WARNING: {name} did not behave as expected (see {out})\n')
    return good

RESULTS=[]

def main():
    ryu=None; ryu_f=None; server=None; server_f=None; load=None; load_f=None
    net=None
    try:
        info('*** Starting Ryu controller\n')
        ryu,ryu_f=start_proc(f'ryu-manager {RYU}', OUT/'ryu_controller.log'); time.sleep(4)
        shaped=netem_available()
        dp='kernel' if kernel_datapath_available() else 'user'
        info(f'*** netem available: {shaped}; OVS datapath: {dp}\n')
        (OUT/'environment.txt').write_text(f'netem_available={shaped}\novs_datapath={dp}\n')
        net=Mininet(topo=TopoC(shaped=shaped), switch=partial(OVSSwitch, datapath=dp), controller=None, autoSetMacs=True, autoStaticArp=True, link=TCLink if shaped else Link)
        net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
        net.start(); time.sleep(3)
        s1=net['s1']; s1.cmd('ovs-vsctl set bridge s1 protocols=OpenFlow13')
        h1,h2,h3,h4=[net[f'h{i}'] for i in range(1,5)]
        if dp=='user':
            # OVS userspace (netdev) datapath: veth TX checksum offload leaves UDP checksums
            # unfinished, so receivers drop UDP (ICMP still works). Turn offload off on hosts.
            for h in net.hosts: h.cmd(f'ethtool -K {h.name}-eth0 tx off rx off 2>/dev/null')
        # NOTE: no pingAll here on purpose - it would install generic priority-10 flows that then
        # carry the UDP/5000 traffic, hiding the controller's priority-100/200 sync flow.
        info('*** Starting Track A server on h1\n')
        server,server_f=start_proc("mnexec -a %s python3 %s --host 10.0.0.1 --port 5000" % (h1.pid, SERVER), OUT/'server.log')
        time.sleep(2)
        info('*** P1 baseline\n'); evaluator(h2,'10.0.0.1','P1_baseline','baseline')
        info('*** P2 controlled 50 ms RTT (25 ms on h1 + h2)\n')
        if shaped:
            qdisc(h1,25); qdisc(h2,25); evaluator(h2,'10.0.0.1','P2_delay','delay'); clear_qdisc(h1); clear_qdisc(h2)
        else:
            info('*** P2 SKIPPED: tc netem not available in this kernel\n'); RESULTS.append(('P2_delay','SKIPPED (no netem)',0))
        info('*** P3 background UDP load\n')
        load,load_f=start_proc("mnexec -a %s python3 %s 10.0.0.3 --port 6000 --pps 2500 --duration 8 --size 1024" % (h4.pid, LOAD), OUT/'load.log')
        time.sleep(1); evaluator(h2,'10.0.0.1','P3_load','load'); load.wait(timeout=15); load_f.close(); load=None
        info('*** P4 load + delay\n')
        if shaped: qdisc(h1,25); qdisc(h2,25)
        load,load_f=start_proc("mnexec -a %s python3 %s 10.0.0.3 --port 6000 --pps 2500 --duration 8 --size 1024" % (h4.pid, LOAD), OUT/'load_delay.log')
        time.sleep(1); evaluator(h2,'10.0.0.1','P4_load_delay','load_delay', note='' if shaped else 'load only - delay skipped, no netem'); load.wait(timeout=15); load_f.close(); load=None
        if shaped: clear_qdisc(h1); clear_qdisc(h2)
        info('*** Recovery: stop server, verify failures, restart, verify recovery\n')
        os.killpg(os.getpgid(server.pid), signal.SIGTERM); server.wait(timeout=5); server_f.close(); server=None
        evaluator(h2,'10.0.0.1','P5_recovery_down','recovery',expect_ok=False)
        server,server_f=start_proc("mnexec -a %s python3 %s --host 10.0.0.1 --port 5000" % (h1.pid, SERVER), OUT/'server_restarted.log'); time.sleep(2)
        evaluator(h2,'10.0.0.1','P6_recovery_up','recovery')
        rc,flows=run('sudo ovs-ofctl -O OpenFlow13 dump-flows s1', OUT/'flows.txt')
        (OUT/'README.txt').write_text('These files are generated by the automated Ubuntu Mininet/SDN runner.\nP1 baseline, P2 delay, P3 load, P4 load+delay, P5 server-down recovery, P6 server-up recovery.\n')
        summary='\n'.join(f'{n:16s} {st:46s} successful_samples={c}' for n,st,c in RESULTS)
        (OUT/'SUMMARY.txt').write_text(summary+'\n')
        info('*** SUMMARY\n'+summary+'\n')
        info(f'*** DONE. Results saved to {OUT}\n')
        if any(st=='FAIL' for _,st,_ in RESULTS): sys.exit(1)
    finally:
        for p,f in [(load,load_f),(server,server_f),(ryu,ryu_f)]:
            if p:
                try: os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except Exception: pass
            if f:
                try: f.close()
                except Exception: pass
        if net:
            try: net.stop()
            except Exception: pass

if __name__=='__main__':
    setLogLevel('info'); main()
