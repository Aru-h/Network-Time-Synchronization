"""
Topic 23 - D1 Mininet topology.

h1 = reference time server
h2 = synchronization client 1
h3 = synchronization client 2
s1 = Open vSwitch

The controller is external (Ryu) on 127.0.0.1:6653.
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
from mininet.topo import Topo


class TimeSyncTopo(Topo):
    def build(self):
        s1 = self.addSwitch("s1", protocols="OpenFlow13")

        h1 = self.addHost("h1", ip="10.0.0.1/24")
        h2 = self.addHost("h2", ip="10.0.0.2/24")
        h3 = self.addHost("h3", ip="10.0.0.3/24")

        self.addLink(h1, s1, cls=TCLink, bw=100)
        self.addLink(h2, s1, cls=TCLink, bw=100)
        self.addLink(h3, s1, cls=TCLink, bw=100)


def run():
    topo = TimeSyncTopo()

    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=None,
        autoSetMacs=True,
        autoStaticArp=True,
        link=TCLink
    )

    c0 = net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6653
    )

    info("*** Starting network\n")
    net.start()

    info("*** Setting OpenFlow 1.3\n")
    for sw in net.switches:
        sw.cmd("ovs-vsctl set bridge %s protocols=OpenFlow13" % sw.name)

    info("*** Network is ready\n")
    info("*** h1 = time server 10.0.0.1\n")
    info("*** h2 = client 1     10.0.0.2\n")
    info("*** h3 = client 2     10.0.0.3\n")
    info("*** Run 'pingall' before the socket demo.\n")

    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    run()
