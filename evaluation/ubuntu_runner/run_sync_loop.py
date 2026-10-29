#!/usr/bin/env python3
"""Sync-loop legs on the existing Mininet/OVS/Ryu setup (topology, controller and QoS code are reused unchanged).

h2 runs server_client/sync_loop.py against the unchanged time server on h1, once per leg:
  S1_slew         skew 100 ms, --max-slew-ppm 5000 (DEMO setting), 120 s: no step, converges by slewing
  S2_step         skew 500 ms, default 500 ppm cap, 60 s: exactly one step, then slew only
  S3_drift        50 ppm oscillator drift, 60 s
  S3f_drift_freq  the same with --freq-compensate (report only)
  S6_idle_cpubusy skew 500 ms, 60 s, no network load, QoS off, with CPU-busy background processes (report only, optional):
                  tests only whether keeping the CPUs awake changes the idle accuracy; it does not name a cause
  S4_load_qosoff  30 Mbit load h4 -> h1 on the 20 Mbit link, QoS off, skew 500 ms, 90 s (report only)
  S5_load_qoson   the same with the OVS QoS queue and set_queue (controller restarted with D2_QOS=on)
Results go to --out (default evaluation/results/sync_loop); nothing is written under actual_sdn_results.
The verdicts and the table come from evaluation/code/sync_loop_check.py.

    sudo ./evaluation/ubuntu_runner/run_sync_loop.sh [--out DIR]
"""
import argparse
import atexit
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_mininet_tests as rt                      # noqa: E402  (TopoC, ShapedLink, start_ryu, check_environment, ...)
from mininet.net import Mininet                     # noqa: E402
from mininet.node import RemoteController, OVSSwitch   # noqa: E402
from mininet.log import setLogLevel, info           # noqa: E402

ROOT, PY, d2_qos = rt.ROOT, rt.PY, rt.d2_qos
SYNCLOOP = ROOT / 'server_client' / 'sync_loop.py'
LOAD_MBPS, LOAD_HEAD_START_S = rt.OVER_LOAD_MBPS, 2


def start_load(net, out, name, seconds, use_iperf):
    """Load h4 -> h1:6000 for `seconds`. Returns (server_proc, client_proc)."""
    h1, h4 = net['h1'], net['h4']
    slog, clog = out / f'{name}_iperf_server.log', out / f'{name}_load_client.log'
    if use_iperf:
        srv = h1.popen(['iperf', '-s', '-u', '-p', str(rt.LOAD_PORT), '-i', '1'], stdout=open(slog, 'w'), stderr=subprocess.STDOUT)
        time.sleep(1)
        cli = h4.popen(['iperf', '-c', '10.0.0.1', '-u', '-p', str(rt.LOAD_PORT), '-b', f'{LOAD_MBPS}M', '-t', str(seconds),
                        '-l', '1470', '-i', '1'], stdout=open(clog, 'w'), stderr=subprocess.STDOUT)
    else:
        pps = int(LOAD_MBPS * 1e6 / (1470 * 8))
        srv = None
        cli = h4.popen([PY, str(rt.LOADGEN), '10.0.0.1', '--port', str(rt.LOAD_PORT), '--pps', str(pps), '--duration', str(seconds),
                        '--size', '1470'], stdout=open(clog, 'w'), stderr=subprocess.STDOUT)
    return srv, cli


class WaitingRemote(RemoteController):
    """RemoteController whose start-up check is a plain socket connect that waits for the controller. Mininet's own check
    runs `telnet` and decodes its output strictly as UTF-8; once (run 3) that raised UnicodeDecodeError while Ryu was still
    starting. The source of the byte was not established and the crash was not reproduced on demand. Same endpoint, no telnet,
    nothing read from the port. (evaluation/ubuntu_runner/run_mininet_tests.py has the same class on d2-tracks.)"""
    def checkListening(self):
        end = time.time() + 30
        while time.time() < end:
            try:
                socket.create_connection((self.ip, self.port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError(f'controller not listening on {self.ip}:{self.port}')


def start_busy(net, n):
    """n CPU-bound background processes at low priority (nice 10) on h4: they keep the cores from idling but yield to
    the sync loop, the server and the switch. No network traffic."""
    return [net['h4'].popen(['nice', '-n', '10', PY, '-c', 'while True: pass'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL) for _ in range(n)]


def leg(net, out, name, skew_ms, duration_s, drift_ppm=0.0, max_slew=500, extra=(), load=False, use_iperf=True):
    cmd = (f'{PY} {SYNCLOOP} --server 10.0.0.1 --skew-ms {skew_ms} --drift-ppm {drift_ppm} --max-slew-ppm {max_slew} '
           f'--duration {duration_s} --csv {out / (name + ".csv")} ' + ' '.join(extra))
    srv = cli = None
    note = ''
    if load:
        srv, cli = start_load(net, out, name, duration_s + 30, use_iperf)
        time.sleep(LOAD_HEAD_START_S)
    txt = net['h2'].cmd(cmd)
    if cli is not None:
        note = f'\nload {LOAD_MBPS}M offered, still running at end of leg: {cli.poll() is None}\n'
        rt.stop_load(srv, cli)
        rx, loss = rt.iperf_server_summary(out / f'{name}_iperf_server.log') if use_iperf else (None, None)
        if rx is not None:
            note += f'iperf server received {rx:.1f} Mbit/s, loss {loss:.1f}%\n'
    (out / f'{name}.txt').write_text(txt + note)
    info(f'*** {name}: ' + next((l for l in reversed(txt.splitlines()) if l.startswith('polls')), 'no summary line') + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'evaluation' / 'results' / 'sync_loop'))
    args = ap.parse_args()
    out = Path(args.out).resolve()
    ryu_cmd, _netem, dp, iperf, env_lines = rt.check_environment()      # root, ryu, ovs tools; read-only
    if os.environ.get('EVAL_CHECK_ONLY') == '1':
        print('\n'.join(env_lines)); print(f'check-only: environment OK; {out} was not touched')
        return
    if 'actual_sdn_results' in out.parts:
        sys.exit('refusing to write under actual_sdn_results')
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / 'environment.txt').write_text('\n'.join(env_lines) + '\n')

    def hand_back():                                                    # the runner is root: give the results back to the sudo user
        uid, gid = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
        if uid and gid:
            for dp_, _d, fs in os.walk(out):
                for p in [dp_] + [os.path.join(dp_, f) for f in fs]:
                    try:
                        os.chown(p, int(uid), int(gid), follow_symlinks=False)
                    except OSError:
                        pass
    atexit.register(hand_back)

    ryu = ryu_f = server = server_f = net = None
    ryu_log = out / 'ryu_controller.log'
    try:
        d2_qos.clear_qos()
        ryu, ryu_f = rt.start_ryu(ryu_cmd, ryu_log, qos_on=False)
        time.sleep(4)
        net = Mininet(topo=rt.TopoC(), switch=partial(OVSSwitch, datapath=dp), controller=None, autoSetMacs=True,
                      autoStaticArp=True, link=rt.ShapedLink)
        net.addController('c0', controller=WaitingRemote, ip='127.0.0.1', port=6653)
        net.start(); time.sleep(3)
        if dp == 'user':
            for h in net.hosts:
                h.cmd(f'ethtool -K {h.name}-eth0 tx off rx off 2>/dev/null')
        server_f = open(out / 'server.log', 'w')
        server = net['h1'].popen([PY, '-u', str(rt.SERVER), '--host', '10.0.0.1', '--port', '5000'], stdout=server_f, stderr=subprocess.STDOUT)
        time.sleep(2)

        info('*** S1 slew: skew 100 ms, 5000 ppm DEMO cap\n')
        leg(net, out, 'S1_slew', 100, 120, max_slew=5000)
        info('*** S2 step: skew 500 ms\n')
        leg(net, out, 'S2_step', 500, 60)
        info('*** S3 drift: 50 ppm\n')
        leg(net, out, 'S3_drift', 0, 60, drift_ppm=50)
        info('*** S3f drift with frequency compensation\n')
        leg(net, out, 'S3f_drift_freq', 0, 60, drift_ppm=50, extra=('--freq-compensate',))
        info('*** S6 idle leg with CPU-busy background processes (%d)\n' % (os.cpu_count() or 1))
        busy = start_busy(net, os.cpu_count() or 1)
        try:
            leg(net, out, 'S6_idle_cpubusy', 500, 60)
        finally:
            for b in busy:
                b.terminate()
            for b in busy:
                try:
                    b.wait(timeout=5)
                except Exception:
                    b.kill()
        info('*** S4 load, QoS off\n')
        leg(net, out, 'S4_load_qosoff', 500, 90, load=True, use_iperf=bool(iperf))

        info('*** QoS phase: OVS linux-htb queues on s1-eth1, controller restarted with D2_QOS=on\n')
        ok_q, msg_q = d2_qos.enable_qos()
        (out / 'qos_setup.txt').write_text(msg_q + '\n\n' + d2_qos.show())
        if not ok_q:
            info(f'*** QoS setup failed: {msg_q}\n')
        else:
            rt.stop_ryu(ryu, ryu_f)
            rt.run('ovs-ofctl -O OpenFlow13 del-flows s1')
            ryu, ryu_f = rt.start_ryu(ryu_cmd, ryu_log, qos_on=True, append=True)
            if not rt.wait_switch():
                info('*** switch did not reconnect to the controller\n')
            else:
                time.sleep(2)
                net['h2'].cmd(f'{PY} {SYNCLOOP} --server 10.0.0.1 --duration 3 --csv {out / "warmup.csv"}')   # lets the new controller learn h1/h2
                (out / 'warmup.csv').unlink(missing_ok=True)
                info('*** S5 load, QoS on\n')
                leg(net, out, 'S5_load_qoson', 500, 90, load=True, use_iperf=bool(iperf))
                rt.run('ovs-ofctl -O OpenFlow13 dump-flows s1', out / 'flows_after_S5.txt')
    finally:
        for p in (server,):
            if p and p.poll() is None:
                p.terminate()
        if ryu:
            rt.stop_ryu(ryu, ryu_f)
        for f in (server_f,):
            try:
                f and f.close()
            except Exception:
                pass
        if net:
            try:
                net.stop()
            except Exception:
                pass
        d2_qos.clear_qos()


if __name__ == '__main__':
    setLogLevel('info')
    main()
