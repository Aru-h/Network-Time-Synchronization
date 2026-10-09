"""
Topic 23 - D1
Ryu SDN controller for the Network Time Synchronization System.

OpenFlow 1.3 controller:
- Learns MAC addresses.
- Installs normal forwarding flows.
- Detects UDP synchronization traffic on port 5000.
- Installs a higher-priority flow for synchronization packets.
- Logs the socket-SDN integration event.

Run:
    ryu-manager controller/time_sync_controller.py --ofp-tcp-listen-port 6653
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, udp


SYNC_PORT = 5000
SYNC_PRIORITY = 100
NORMAL_PRIORITY = 10


class TimeSyncController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(TimeSyncController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Table-miss: send unknown packets to controller.
        match = parser.OFPMatch()
        actions = [
            parser.OFPActionOutput(
                ofproto.OFPP_CONTROLLER,
                ofproto.OFPCML_NO_BUFFER
            )
        ]
        self.add_flow(datapath, 0, match, actions)

        self.logger.info(
            "SWITCH CONNECTED: dpid=%s, OpenFlow=%s",
            datapath.id, ofproto.OFP_VERSION
        )

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0,
                 hard_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        instructions = [
            parser.OFPInstructionActions(
                ofproto.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout
        )
        datapath.send_msg(mod)

    def install_sync_flow(self, datapath, in_port, ip_pkt, udp_pkt,
                          out_port):
        parser = datapath.ofproto_parser

        # Match whichever direction this packet is: request (dst port 5000)
        # or reply (src port 5000), so both legs of the round trip get the
        # high-priority treatment, not just the client-to-server leg.
        match_kwargs = dict(
            in_port=in_port,
            eth_type=ether_types.ETH_TYPE_IP,
            ip_proto=17
        )
        if udp_pkt.dst_port == SYNC_PORT:
            match_kwargs["udp_dst"] = SYNC_PORT
            match_kwargs["ipv4_dst"] = ip_pkt.dst
        else:
            match_kwargs["udp_src"] = SYNC_PORT
            match_kwargs["ipv4_src"] = ip_pkt.src

        match = parser.OFPMatch(**match_kwargs)

        actions = [
            parser.OFPActionOutput(out_port)
        ]

        self.add_flow(
            datapath,
            SYNC_PRIORITY,
            match,
            actions,
            idle_timeout=30
        )

        self.logger.info(
            "SYNC FLOW INSTALLED: dpid=%s in_port=%s out_port=%s "
            "udp_dst=%s priority=%s",
            datapath.id, in_port, out_port, SYNC_PORT, SYNC_PRIORITY
        )

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][eth.src] = in_port

        # ARP and non-IP traffic are forwarded by the learning switch logic.
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        is_sync = ip_pkt and udp_pkt and (
            udp_pkt.dst_port == SYNC_PORT or udp_pkt.src_port == SYNC_PORT
        )

        if is_sync:
            # The destination MAC should already be learned after pingall.
            out_port = self.mac_to_port[dpid].get(eth.dst, ofproto.OFPP_FLOOD)

            if out_port != ofproto.OFPP_FLOOD:
                # No controller-side "already installed" cache: a packet-in
                # for sync traffic means the switch has no matching flow
                # (never installed, or expired via idle_timeout), so always
                # (re)install. Re-sending an identical flow-mod is idempotent.
                self.install_sync_flow(
                    datapath,
                    in_port,
                    ip_pkt,
                    udp_pkt,
                    out_port
                )

                # Send this first packet onward immediately.
                actions = [parser.OFPActionOutput(out_port)]
            else:
                actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]

            self.logger.info(
                "SOCKET-SDN EVENT: UDP sync packet %s:%s -> %s:%s",
                ip_pkt.src, udp_pkt.src_port, ip_pkt.dst, udp_pkt.dst_port
            )
        else:
            out_port = self.mac_to_port[dpid].get(eth.dst, ofproto.OFPP_FLOOD)
            actions = [parser.OFPActionOutput(out_port)]

            # Once destination is known, install a normal forwarding rule.
            if out_port != ofproto.OFPP_FLOOD:
                match = parser.OFPMatch(
                    in_port=in_port,
                    eth_dst=eth.dst
                )
                self.add_flow(
                    datapath,
                    NORMAL_PRIORITY,
                    match,
                    actions,
                    idle_timeout=60
                )

        # Packet-out for the packet that caused the Packet-In.
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )
        datapath.send_msg(out)
