"""
OVS linux-htb QoS for the D2 bottleneck port.

The time server h1 hangs off s1-eth1 (OpenFlow port 1), a 20 Mbit link. This
module attaches an OVS QoS to that switch port with two queues:

    queue 0  default  (background load)   min 0,      max 20 Mbit, priority 1
    queue 1  sync     (UDP/5000)          min 2 Mbit, max 20 Mbit, priority 0

The total stays 20 Mbit (QoS max-rate). OVS replaces the root qdisc on the
switch-side port, which Mininet's TCLink had shaped; the host-side shaping on
h1-eth0 and the netem qdiscs under it are untouched, so netem still works.

Sync flows reach queue 1 through the controller's set_queue action. A smaller
OVS priority value receives spare bandwidth first.
"""

import subprocess

QOS_PORT = "s1-eth1"
QOS_OFPORT = 1
TOTAL_BPS = 20_000_000
SYNC_MIN_BPS = 2_000_000
SYNC_QUEUE = 1
DEFAULT_QUEUE = 0


def _sh(cmd):
    p = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    return p.returncode, p.stdout


def qos_command(port=QOS_PORT, total_bps=TOTAL_BPS, sync_min_bps=SYNC_MIN_BPS):
    """One ovs-vsctl transaction that creates the QoS and both queues."""
    return (
        f"ovs-vsctl -- set port {port} qos=@qos "
        f"-- --id=@qos create qos type=linux-htb other-config:max-rate={total_bps} "
        f"queues:{DEFAULT_QUEUE}=@qd queues:{SYNC_QUEUE}=@qs "
        f"-- --id=@qd create queue other-config:min-rate=1 "
        f"other-config:max-rate={total_bps} other-config:priority=1 "
        f"-- --id=@qs create queue other-config:min-rate={sync_min_bps} "
        f"other-config:max-rate={total_bps} other-config:priority=0"
    )


def ofport(port=QOS_PORT):
    rc, out = _sh(f"ovs-vsctl get Interface {port} ofport")
    return int(out.strip()) if rc == 0 and out.strip().lstrip("-").isdigit() else None


def enable_qos(port=QOS_PORT, total_bps=TOTAL_BPS, sync_min_bps=SYNC_MIN_BPS):
    """Attach the QoS. Returns (ok, message)."""
    clear_qos(port)
    if ofport(port) != QOS_OFPORT:
        return False, (f"{port} is OpenFlow port {ofport(port)}, expected "
                       f"{QOS_OFPORT}; the controller reads port {QOS_OFPORT}")
    rc, out = _sh(qos_command(port, total_bps, sync_min_bps))
    if rc != 0:
        return False, out.strip()
    return True, "qos linux-htb on %s: default q%d, sync q%d min %d bps, total %d bps" % (
        port, DEFAULT_QUEUE, SYNC_QUEUE, sync_min_bps, total_bps)


def clear_qos(port=QOS_PORT):
    """Remove the QoS from the port and delete the QoS/Queue rows."""
    _sh(f"ovs-vsctl clear port {port} qos")
    _sh("ovs-vsctl --all destroy qos")
    _sh("ovs-vsctl --all destroy queue")


def show(port=QOS_PORT):
    """Evidence text: OVS QoS rows and the kernel classes on the port."""
    parts = []
    for title, cmd in (("ovs-vsctl list qos", "ovs-vsctl list qos"),
                       ("ovs-vsctl list queue", "ovs-vsctl list queue"),
                       (f"tc -s class show dev {port}", f"tc -s class show dev {port}")):
        parts.append(f"### {title}\n{_sh(cmd)[1]}")
    return "\n".join(parts)
