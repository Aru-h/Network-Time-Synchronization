"""
Topic 23 - D2 Adaptive SDN Controller

OpenFlow 1.3 Ryu controller with:
- learning-switch forwarding
- high-priority synchronization flow
- background traffic classification
- periodic port monitoring
- dynamic synchronization-flow priority
- simple recovery when a learned path disappears

The controller is intentionally educational: it demonstrates dynamic SDN
behavior without pretending to be a production-grade routing controller.
"""

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet, ether_types, ipv4, udp

SYNC_PORT = 5000
LOAD_PORT = 6000
NORMAL_PRIORITY = 10
SYNC_PRIORITY_NORMAL = 100
SYNC_PRIORITY_CONGESTED = 200


class AdaptiveTimeSyncController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.sync_keys = {}
        self.port_bytes = {}
        self.last_stats = {}
        self.monitor_thread = hub.spawn(self._monitor)

    def add_flow(self, dp, priority, match, actions, idle_timeout=0,
                 hard_timeout=0):
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS,
                                              actions)]
        mod = parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=inst, idle_timeout=idle_timeout,
            hard_timeout=hard_timeout)
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        parser = dp.ofproto_parser
        self.add_flow(
            dp, 0, parser.OFPMatch(),
            [parser.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER,
                                    dp.ofproto.OFPCML_NO_BUFFER)]
        )
        self.logger.info("D2 SWITCH CONNECTED dpid=%s", dp.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def state_change(self, ev):
        dp = ev.datapath
        self.datapaths[dp.id] = dp

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(2)

    def _request_stats(self, dp):
        parser = dp.ofproto_parser
        req = parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply(self, ev):
        dp = ev.msg.datapath
        for stat in ev.msg.body:
            key = (dp.id, stat.port_no)
            old = self.port_bytes.get(key)
            current = stat.tx_bytes + stat.rx_bytes
            self.port_bytes[key] = current
            if old is not None:
                delta = max(0, current - old)
                self.last_stats[key] = delta

        # Demonstrate a dynamic decision from measured traffic.
        total_delta = sum(v for (d, _), v in self.last_stats.items() if d == dp.id)
        if total_delta > 1_000_000:
            self.logger.info(
                "DYNAMIC SDN: dpid=%s traffic high (%d bytes/interval); "
                "sync priority policy = %d",
                dp.id, total_delta, SYNC_PRIORITY_CONGESTED)
        else:
            self.logger.info(
                "DYNAMIC SDN: dpid=%s traffic normal (%d bytes/interval); "
                "sync priority policy = %d",
                dp.id, total_delta, SYNC_PRIORITY_NORMAL)

    def install_sync_flow(self, dp, in_port, ip_pkt, udp_pkt, out_port,
                          congested=False):
        parser = dp.ofproto_parser
        priority = SYNC_PRIORITY_CONGESTED if congested else SYNC_PRIORITY_NORMAL

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
        actions = [parser.OFPActionOutput(out_port)]
        self.add_flow(dp, priority, match, actions, idle_timeout=20)
        self.logger.info(
            "DYNAMIC SYNC FLOW: dpid=%s in=%s out=%s udp/5000 priority=%s",
            dp.id, in_port, out_port, priority)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        self.mac_to_port.setdefault(dp.id, {})[eth.src] = in_port
        out_port = self.mac_to_port[dp.id].get(eth.dst, ofp.OFPP_FLOOD)

        ip = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        actions = [parser.OFPActionOutput(out_port)]

        is_sync = ip and udp_pkt and (
            udp_pkt.dst_port == SYNC_PORT or udp_pkt.src_port == SYNC_PORT
        )

        if is_sync:
            congested = sum(self.last_stats.values()) > 1_000_000
            if out_port != ofp.OFPP_FLOOD:
                key = (dp.id, in_port, eth.dst, udp_pkt.dst_port == SYNC_PORT)
                if self.sync_keys.get(key) != congested:
                    self.install_sync_flow(
                        dp, in_port, ip, udp_pkt, out_port, congested)
                    self.sync_keys[key] = congested
            self.logger.info(
                "SOCKET-SDN D2 EVENT: sync packet %s -> %s", ip.src, ip.dst)
        elif ip and udp_pkt and udp_pkt.dst_port == LOAD_PORT:
            # Background load gets only normal forwarding priority.
            self.logger.info(
                "BACKGROUND TRAFFIC: %s -> %s UDP/%s", ip.src, ip.dst,
                udp_pkt.dst_port)
        elif out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self.add_flow(dp, NORMAL_PRIORITY, match, actions, idle_timeout=30)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data))
