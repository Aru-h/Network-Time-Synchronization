"""Sandbox test for the D2 controller policy (no Mininet, no OVS, no root).

Feeds synthetic port-1 byte counters to the controller with a fake datapath and
checks: hysteresis, proactive priority-200 push, revert on clear, set_queue
only when QoS is on and only toward port 1, and that other ports are ignored.

Run with a Python that has Ryu:  ~/topic23-venv/bin/python tests/test_controller_policy.py
"""
import os
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))

import d2_adaptive_controller as c  # noqa: E402
from ryu.ofproto import ofproto_v1_3, ofproto_v1_3_parser  # noqa: E402


class FakeDP:
    def __init__(self):
        self.id = 1
        self.ofproto = ofproto_v1_3
        self.ofproto_parser = ofproto_v1_3_parser
        self.sent = []

    def send_msg(self, msg):
        self.sent.append(msg)


def make(qos):
    os.environ["D2_QOS"] = "on" if qos else "off"
    app = c.AdaptiveTimeSyncController()
    dp = FakeDP()
    app.datapaths[dp.id] = dp
    return app, dp


def register_flows(app, dp):
    kw = dict(in_port=2, eth_type=0x0800, ip_proto=17, udp_dst=5000, ipv4_dst="10.0.0.1")
    app.sync_flows[(1, 2, tuple(sorted(kw.items())))] = (kw, 1)
    kw2 = dict(in_port=1, eth_type=0x0800, ip_proto=17, udp_src=5000,
               ipv4_src="10.0.0.1", ipv4_dst="10.0.0.2")
    app.sync_flows[(1, 1, tuple(sorted(kw2.items())))] = (kw2, 2)


def mods(dp):
    out = []
    for m in dp.sent:
        if isinstance(m, ofproto_v1_3_parser.OFPFlowMod):
            acts = [a for i in m.instructions for a in i.actions]
            out.append((m.command, m.priority, acts))
    return out


class PolicyTest(unittest.TestCase):
    def test_hysteresis_and_proactive_priority(self):
        app, dp = make(qos=False)
        register_flows(app, dp)
        app._update_policy(dp, 10.0)                  # between thresholds: stays normal
        self.assertFalse(app.congested.get(1, False))
        self.assertEqual(mods(dp), [])
        app._update_policy(dp, 19.5)                  # crosses ENTER
        self.assertTrue(app.congested[1])
        added = [m for m in mods(dp) if m[0] == dp.ofproto.OFPFC_ADD]
        self.assertEqual({m[1] for m in added}, {200})
        self.assertEqual(len(added), 2)
        dp.sent.clear()
        app._update_policy(dp, 12.0)                  # inside the band: stays congested
        app._update_policy(dp, 7.0)                   # one low poll is not enough
        self.assertTrue(app.congested[1])
        app._update_policy(dp, 12.0)                  # resets the low counter
        app._update_policy(dp, 7.0)
        self.assertTrue(app.congested[1])
        app._update_policy(dp, 6.0)                   # second consecutive low poll
        self.assertFalse(app.congested.get(1, False))
        mm = mods(dp)
        self.assertEqual({m[1] for m in mm if m[0] == dp.ofproto.OFPFC_ADD}, {100})
        self.assertEqual({m[1] for m in mm if m[0] == dp.ofproto.OFPFC_DELETE_STRICT}, {200})

    def test_set_queue_only_with_qos_and_toward_port1(self):
        for qos in (False, True):
            app, dp = make(qos)
            register_flows(app, dp)
            app._update_policy(dp, 20.0)
            queue_flows = [m for m in mods(dp) if m[0] == dp.ofproto.OFPFC_ADD
                           and any(isinstance(a, ofproto_v1_3_parser.OFPActionSetQueue) for a in m[2])]
            if qos:
                self.assertEqual(len(queue_flows), 1)       # only the request flow (out port 1)
                acts = queue_flows[0][2]
                self.assertIsInstance(acts[0], ofproto_v1_3_parser.OFPActionSetQueue)
                self.assertEqual(acts[0].queue_id, c.QOS_SYNC_QUEUE)
                self.assertIsInstance(acts[1], ofproto_v1_3_parser.OFPActionOutput)
            else:
                self.assertEqual(queue_flows, [])

    def test_only_port1_counts(self):
        app, dp = make(False)
        mk = lambda port, tx: types.SimpleNamespace(port_no=port, tx_bytes=tx, rx_bytes=0)
        ev = lambda body: types.SimpleNamespace(msg=types.SimpleNamespace(datapath=dp, body=body))
        app.port_stats_reply(ev([mk(2, 0), mk(1, 0)]))
        app.port_prev[1] = (app.port_prev[1][0] - 1.0, 0)   # pretend 1 s passed
        app.port_stats_reply(ev([mk(2, 900_000_000), mk(1, 100_000)]))  # port 2 is huge, port 1 tiny
        self.assertFalse(app.congested[1] if 1 in app.congested else False)
        app.port_prev[1] = (app.port_prev[1][0] - 1.0, 0)
        app.port_stats_reply(ev([mk(1, 2_500_000)]))        # 20 Mbit/s over 1 s
        self.assertTrue(app.congested[1])


if __name__ == "__main__":
    unittest.main()
