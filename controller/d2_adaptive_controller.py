"""
Topic 23 - D2 Adaptive SDN Controller

OpenFlow 1.3 Ryu controller with:
- learning-switch forwarding
- high-priority synchronization flow
- background traffic classification
- congestion detection on OpenFlow port 1 (toward the time server h1) only,
  with hysteresis
- proactive priority-200 sync flows the moment congestion is detected, reverted
  when the load clears
- optional QoS: sync flows get set_queue:1 before output (D2_QOS=on)
- simple recovery when a learned path disappears

The controller is intentionally educational: it demonstrates dynamic SDN
behavior without pretending to be a production-grade routing controller.
"""

import os
import time

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

# Congestion detection: egress rate of the port toward h1 (OpenFlow port 1),
# where the load and the sync requests share the 20 Mbit link.
CONGESTION_PORT = 1
POLL_INTERVAL_S = 1
ENTER_MBPS = 15.0      # congested at or above this
EXIT_MBPS = 8.0        # clear at or below this ...
EXIT_POLLS = 2         # ... for this many polls in a row

# QoS queues on that port (see mininet/d2_qos.py). Queue 1 has a minimum rate.
QOS_DEFAULT_QUEUE = 0
QOS_SYNC_QUEUE = 1


def qos_enabled():
    return os.environ.get("D2_QOS", "off").strip().lower() in ("1", "on", "true", "yes")


class AdaptiveTimeSyncController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.qos = qos_enabled()
        self.port_prev = {}     # dpid -> (monotonic time, tx_bytes) of CONGESTION_PORT
        self.congested = {}     # dpid -> bool
        self.below = {}         # dpid -> consecutive polls at or below EXIT_MBPS
        self.sync_flows = {}    # (dpid, in_port, match items) -> (match kwargs, out_port)
        self.logger.info("D2 QOS: %s (set_queue:%d on sync flows toward port %d)",
                         "ON" if self.qos else "OFF", QOS_SYNC_QUEUE, CONGESTION_PORT)
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

    def del_flow(self, dp, priority, match):
        parser = dp.ofproto_parser
        ofp = dp.ofproto
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, command=ofp.OFPFC_DELETE_STRICT, priority=priority,
            match=match, out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY))

    def out_actions(self, dp, out_port, queue=None):
        """Output action, preceded by set_queue when QoS is on and the packet
        leaves through the QoS port. Port 1 is the only port with queues."""
        parser = dp.ofproto_parser
        actions = []
        if self.qos and queue is not None and out_port == CONGESTION_PORT:
            actions.append(parser.OFPActionSetQueue(queue))
        actions.append(parser.OFPActionOutput(out_port))
        return actions

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features(self, ev):
        dp = ev.msg.datapath
        self.datapaths[dp.id] = dp
        # A fresh connection has an empty flow table: forget what we pushed.
        self.congested[dp.id] = False
        self.port_prev.pop(dp.id, None)
        for key in [k for k in self.sync_flows if k[0] == dp.id]:
            del self.sync_flows[key]
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
        # During the handshake (CONFIG_DISPATCHER) dp.id is still None; storing
        # it would register the same switch twice and make the monitor poll it
        # twice per cycle (the second reply is a 0-byte delta).
        if dp is None or dp.id is None:
            return
        self.datapaths[dp.id] = dp

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                self._request_stats(dp)
            hub.sleep(POLL_INTERVAL_S)

    def _request_stats(self, dp):
        parser = dp.ofproto_parser
        req = parser.OFPPortStatsRequest(dp, 0, CONGESTION_PORT)
        dp.send_msg(req)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply(self, ev):
        dp = ev.msg.datapath
        now = time.monotonic()
        for stat in ev.msg.body:
            if stat.port_no != CONGESTION_PORT:
                continue
            prev = self.port_prev.get(dp.id)
            self.port_prev[dp.id] = (now, stat.tx_bytes)
            if prev is None or now <= prev[0]:
                continue
            mbps = max(0, stat.tx_bytes - prev[1]) * 8 / (now - prev[0]) / 1e6
            self._update_policy(dp, mbps)

    def _update_policy(self, dp, mbps):
        was = self.congested.get(dp.id, False)
        if not was and mbps >= ENTER_MBPS:
            self.congested[dp.id] = True
            self.below[dp.id] = 0
            self._log_policy(dp, "CONGESTED", mbps)
            self._set_sync_priority(dp, SYNC_PRIORITY_CONGESTED)
        elif was:
            if mbps <= EXIT_MBPS:
                self.below[dp.id] = self.below.get(dp.id, 0) + 1
                if self.below[dp.id] >= EXIT_POLLS:
                    self.congested[dp.id] = False
                    self._log_policy(dp, "CLEAR", mbps)
                    self._set_sync_priority(dp, SYNC_PRIORITY_NORMAL)
            else:
                self.below[dp.id] = 0
        priority = (SYNC_PRIORITY_CONGESTED if self.congested.get(dp.id)
                    else SYNC_PRIORITY_NORMAL)
        self.logger.info(
            "DYNAMIC SDN: t=%.3f dpid=%s port %d egress %.2f Mbit/s (%s); "
            "sync priority policy = %d",
            time.time(), dp.id, CONGESTION_PORT, mbps,
            "congested" if self.congested.get(dp.id) else "normal", priority)

    def _log_policy(self, dp, state, mbps):
        # Machine-readable transition line (epoch seconds) for the replay UI.
        self.logger.info("POLICY t=%.3f dpid=%s state=%s rate_mbps=%.2f qos=%s",
                         time.time(), dp.id, state, mbps,
                         "on" if self.qos else "off")

    def _set_sync_priority(self, dp, priority):
        """Proactively move every known sync flow to `priority`: install the new
        flow first, then delete the old one, so a sync packet always matches."""
        old = (SYNC_PRIORITY_NORMAL if priority == SYNC_PRIORITY_CONGESTED
               else SYNC_PRIORITY_CONGESTED)
        for (dpid, _in_port, _items), (kwargs, out_port) in list(self.sync_flows.items()):
            if dpid != dp.id:
                continue
            parser = dp.ofproto_parser
            self.add_flow(dp, priority, parser.OFPMatch(**kwargs),
                          self.out_actions(dp, out_port, QOS_SYNC_QUEUE),
                          idle_timeout=20)
            self.del_flow(dp, old, parser.OFPMatch(**kwargs))
            self.logger.info(
                "DYNAMIC SYNC FLOW: dpid=%s in=%s out=%s udp/5000 priority=%s (proactive)",
                dp.id, kwargs["in_port"], out_port, priority)

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
            # Reply flows must also be scoped to the destination client:
            # the output port depends on WHICH client the reply is for.
            match_kwargs["ipv4_dst"] = ip_pkt.dst

        match = parser.OFPMatch(**match_kwargs)
        actions = self.out_actions(dp, out_port, QOS_SYNC_QUEUE)
        self.add_flow(dp, priority, match, actions, idle_timeout=20)
        self.sync_flows[(dp.id, in_port, tuple(sorted(match_kwargs.items())))] = (
            match_kwargs, out_port)
        self.logger.info(
            "DYNAMIC SYNC FLOW: dpid=%s in=%s out=%s udp/5000 priority=%s%s",
            dp.id, in_port, out_port, priority,
            " set_queue=%d" % QOS_SYNC_QUEUE
            if self.qos and out_port == CONGESTION_PORT else "")

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
            congested = self.congested.get(dp.id, False)
            if out_port != ofp.OFPP_FLOOD:
                # A packet-in means no flow matched, so (re)install every time.
                # An "already installed" cache goes stale when the flow's idle
                # timeout removes it, and then every sync packet stays on the
                # slow controller path.
                self.install_sync_flow(
                    dp, in_port, ip, udp_pkt, out_port, congested)
            self.logger.info(
                "SOCKET-SDN D2 EVENT: sync packet %s -> %s", ip.src, ip.dst)
        elif ip and udp_pkt and udp_pkt.dst_port == LOAD_PORT:
            # Background load gets only normal forwarding priority.
            self.logger.info(
                "BACKGROUND TRAFFIC: %s -> %s UDP/%s", ip.src, ip.dst,
                udp_pkt.dst_port)
            if out_port != ofp.OFPP_FLOOD:
                # Forward in the data plane at NORMAL priority. Without a flow
                # every background packet is a packet-in handled by the
                # controller (table-miss), so it never competes with sync
                # traffic on the switch's egress queue.
                match = parser.OFPMatch(
                    in_port=in_port, eth_type=ether_types.ETH_TYPE_IP,
                    ip_proto=17, ipv4_dst=ip.dst, udp_dst=LOAD_PORT)
                self.add_flow(dp, NORMAL_PRIORITY, match,
                              self.out_actions(dp, out_port, QOS_DEFAULT_QUEUE),
                              idle_timeout=30)
        elif out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=eth.dst)
            self.add_flow(dp, NORMAL_PRIORITY, match, actions, idle_timeout=30)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(parser.OFPPacketOut(
            datapath=dp, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data))
