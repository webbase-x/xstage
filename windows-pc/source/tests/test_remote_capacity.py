import ctypes
import time
import unittest
from karaoke.remote_capacity import recommended_clients
from karaoke.wifi_network import WifiState, Association, Connection, select_network


class CapacityTests(unittest.TestCase):
    def test_windows_layout_and_metrics(self):
        self.assertEqual(ctypes.sizeof(Association),68)
        self.assertEqual(Connection.association.offset,520)
        self.assertEqual(Association.signal.offset,56)
        state=select_network([(1,'Stage',dict(signal=80,rx_mbps=144,tx_mbps=72))],{1:['192.168.1.2']})
        self.assertEqual((state.signal,state.rx_mbps,state.tx_mbps),(80,144,72))

    def test_estimate_conservative_with_audio_and_latency(self):
        good=WifiState('connected','Stage','192.168.1.2',signal=80,rx_mbps=72,tx_mbps=72)
        self.assertLess(recommended_clients(good,True),recommended_clients(good))
        self.assertLess(recommended_clients(good,False,600),recommended_clients(good))
        self.assertEqual(recommended_clients(WifiState('connected')),10)

    def test_foreground_poll_keeps_connection_and_absent_client_expires(self):
        from test_remote_mobile import RemoteMobileTests
        case=RemoteMobileTests();case.setUp()
        try:
            case.remote.configure(max_clients=1)
            token=case.login()
            status,result=case.call('/api/login',{'code':case.remote.request_key})
            self.assertEqual(status,503);self.assertTrue(result['full'])
            old=time.monotonic()-290
            case.remote.sessions[token]['active']=old
            self.assertEqual(case.call('/api/state',token=token)[0],200)
            self.assertEqual(case.remote.sessions[token]['active'],old)
            self.assertEqual(case.call('/api/activity',{'live':True,'latency_ms':45},token)[0],200)
            self.assertGreater(case.remote.sessions[token]['active'],old)
            # v0.9.38: a foreground GET counts as presence even without taps.
            case.remote.sessions[token]['active']=time.monotonic()-301
            self.assertEqual(case.call('/api/state',token=token)[0],200)
            # An offline/background client sends no requests: both clocks expire.
            case.remote.sessions[token]['seen']=time.monotonic()-301
            case.remote.sessions[token]['active']=time.monotonic()-301
            self.assertEqual(case.call('/api/state',token=token)[0],401)
            self.assertNotEqual(case.login(),token)
        finally:case.tearDown()

    def test_lower_limit_keeps_existing_users(self):
        from test_remote_mobile import RemoteMobileTests
        case=RemoteMobileTests();case.setUp()
        try:
            one=case.login();two=case.login();case.remote.configure(max_clients=1)
            self.assertEqual(case.call('/api/state',token=one)[0],200)
            self.assertEqual(case.call('/api/state',token=two)[0],200)
            self.assertEqual(case.remote.capacity_stats()[0],2)
        finally:case.tearDown()


if __name__=='__main__':unittest.main()
