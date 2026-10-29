"""Sandbox test for flow_assertions.py on canned ovs-ofctl / tc output."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation" / "code"))
import flow_assertions as fa  # noqa: E402

FLOWS_ON = '''
 cookie=0x0, duration=3.2s, table=0, n_packets=10, n_bytes=1000, idle_timeout=20, priority=200,udp,in_port="s1-eth2",nw_dst=10.0.0.1,tp_dst=5000 actions=set_queue:1,output:"s1-eth1"
 cookie=0x0, duration=3.2s, table=0, n_packets=10, n_bytes=1000, idle_timeout=20, priority=200,udp,in_port="s1-eth1",nw_src=10.0.0.1,nw_dst=10.0.0.2,tp_src=5000 actions=output:"s1-eth2"
 cookie=0x0, duration=9.2s, table=0, n_packets=900, n_bytes=1000, idle_timeout=30, priority=10,udp,in_port="s1-eth4",nw_dst=10.0.0.1,tp_dst=6000 actions=set_queue:0,output:"s1-eth1"
 cookie=0x0, duration=90s, table=0, n_packets=3, n_bytes=100, priority=0 actions=CONTROLLER:65535
'''
FLOWS_OFF = FLOWS_ON.replace("set_queue:1,", "").replace("set_queue:0,", "")
FLOWS_100 = FLOWS_ON.replace("priority=200", "priority=100")

TC_ON = '''class htb 1:fffe root rate 20Mbit ceil 20Mbit burst 2500b cburst 2500b
 Sent 5000000 bytes 4000 pkt (dropped 0, overlimits 0 requeues 0)
class htb 1:1 parent 1:fffe prio 1 rate 8bit ceil 20Mbit burst 1b cburst 2500b
 Sent 4900000 bytes 3900 pkt (dropped 0, overlimits 5 requeues 0)
class htb 1:2 parent 1:fffe prio 0 rate 2Mbit ceil 20Mbit burst 2750b cburst 2500b
 Sent 3000 bytes 30 pkt (dropped 0, overlimits 0 requeues 0)
'''
TC_ZERO = TC_ON.replace("Sent 3000 bytes 30 pkt", "Sent 0 bytes 0 pkt")
TC_OFF = "class htb 1:1 root leaf 5: prio 0 rate 20Mbit ceil 20Mbit\n Sent 10 bytes 1 pkt\n"


def ok(res):
    return all(r[1] for r in res)


class T(unittest.TestCase):
    def test_flows_qos_on(self):
        self.assertTrue(ok(fa.check_flows(FLOWS_ON, True)))
        self.assertFalse(ok(fa.check_flows(FLOWS_OFF, True)))     # missing set_queue:1
        self.assertFalse(ok(fa.check_flows(FLOWS_100, True)))     # no priority=200

    def test_flows_qos_off(self):
        self.assertTrue(ok(fa.check_flows(FLOWS_OFF, False)))
        self.assertFalse(ok(fa.check_flows(FLOWS_ON, False)))     # set_queue present while off

    def test_tc(self):
        self.assertTrue(ok(fa.check_tc_classes(TC_ON, True)))
        self.assertFalse(ok(fa.check_tc_classes(TC_ZERO, True)))  # sync not in own class
        self.assertFalse(ok(fa.check_tc_classes(TC_OFF, True)))
        self.assertTrue(ok(fa.check_tc_classes(TC_OFF, False)))
        self.assertFalse(ok(fa.check_tc_classes(TC_ON, False)))


if __name__ == "__main__":
    unittest.main()
