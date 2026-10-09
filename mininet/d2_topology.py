"""
D2 Mininet topology.

h1 = time server
h2/h3 = time synchronization clients
h4 = background traffic generator
s1 = Open vSwitch
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
from mininet.topo import Topo


class D2Topo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")
        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        h3 = self.addHost("h3", ip="10.0.0.3/24")
        h4 = self.addHost("h4", ip="10.0.0.4/24")

        self.addLink(h1, s1, cls=TCLink, bw=20, delay="1ms")
        self.addLink(h2, s1, cls=TCLink, bw=20, delay="1ms")
        self.addLink(h3, s1, cls=TCLink, bw=20, delay="1ms")
        self.addLink(h4, s1, cls=TCLink, bw=20, delay="1ms")


def run():
    net = Mininet(topo=D2Topo(), switch=OVSSwitch, controller=None,
                  autoSetMacs=True, autoStaticArp=True, link=TCLink)
    net.addController("c0", controller=RemoteController,
                      ip="127.0.0.1", port=6653)
    info("*** Starting D2 network\n")
    net.start()
    for sw in net.switches:
        sw.cmd("ovs-vsctl set bridge %s protocols=OpenFlow13" % sw.name)
    info("*** D2 network ready: h1 server, h2/h3 clients, h4 load\n")
    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
