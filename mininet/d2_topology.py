"""
D2 Mininet topology.

h1 = time server
h2/h3 = time synchronization clients
h4 = background traffic generator
s1 = Open vSwitch

h1 <-> s1 is the 20 Mbit bottleneck (OpenFlow port 1); the other links are
100 Mbit, matching the automated runner. With --qos on, an OVS linux-htb QoS
(default queue + sync queue with a minimum rate) is attached to s1-eth1; start
the controller with D2_QOS=on so sync flows use set_queue:1.

    sudo python3 mininet/d2_topology.py [--qos on|off]
"""

import argparse

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
from mininet.topo import Topo

import d2_qos


class D2Topo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        h3 = self.addHost("h3", ip="10.0.0.3/24")
        h4 = self.addHost("h4", ip="10.0.0.4/24")

        self.addLink(h1, s1, cls=TCLink, bw=20)
        self.addLink(h2, s1, cls=TCLink, bw=100)
        self.addLink(h3, s1, cls=TCLink, bw=100)
        self.addLink(h4, s1, cls=TCLink, bw=100)


def run(qos=False):
    net = Mininet(topo=D2Topo(), switch=OVSSwitch, controller=None,
                  autoSetMacs=True, autoStaticArp=True, link=TCLink)
    net.addController("c0", controller=RemoteController,
                      ip="127.0.0.1", port=6653)
    info("*** Starting D2 network\n")
    net.start()
    for sw in net.switches:
        sw.cmd("ovs-vsctl set bridge %s protocols=OpenFlow13" % sw.name)
    if qos:
        ok, msg = d2_qos.enable_qos()
        info("*** QoS %s: %s\n" % ("ON" if ok else "FAILED", msg))
    info("*** D2 network ready: h1 server, h2/h3 clients, h4 load\n")
    CLI(net)
    if qos:
        d2_qos.clear_qos()
    net.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--qos", choices=["on", "off"], default="off")
    setLogLevel("info")
    run(qos=ap.parse_args().qos == "on")
