import unittest
from karaoke.remote_setup import RemoteSetup, validate_setup, network_actions


class RemoteSetupTests(unittest.TestCase):
    def test_only_relevant_network_actions_are_visible(self):
        self.assertEqual(network_actions('denied',False),
                         dict(permission=True,connect=False,refresh=True))
        self.assertEqual(network_actions('disconnected',False),
                         dict(permission=False,connect=True,refresh=True))
        for status,ready,repairing in [('connected',True,False),
                                      ('checking',False,False),
                                      ('denied',False,True)]:
            with self.subTest(status=status):
                self.assertFalse(any(network_actions(status,ready,repairing).values()))

    def test_network_and_permission_are_required(self):
        flow = RemoteSetup()
        self.assertFalse(flow.next(False))
        self.assertFalse(flow.next(True, repairing=True))
        self.assertEqual(flow.step, 0)
        self.assertTrue(flow.next(True))
        self.assertEqual(flow.step, 1)

    def test_cannot_finish_until_server_starts(self):
        flow = RemoteSetup()
        flow.next(True)
        self.assertFalse(flow.next(True))
        self.assertEqual(flow.step, 1)
        flow.started()
        self.assertEqual(flow.step, 2)

    def test_back_stop_and_reopen(self):
        flow = RemoteSetup(running=True)
        self.assertEqual(flow.step, 2)
        flow.back(); self.assertEqual(flow.step, 1)
        flow.back(); flow.back(); self.assertEqual(flow.step, 0)
        flow.started(); flow.stopped(); self.assertEqual(flow.step, 0)

    def test_network_loss_returns_to_connection_before_start(self):
        flow = RemoteSetup()
        flow.next(True)
        flow.network_changed(False, False)
        self.assertEqual(flow.step, 0)
        flow.started(); flow.network_changed(False, True)
        self.assertEqual(flow.step, 2)

    def test_validation_rejects_invalid_values(self):
        for ready, repairing, port, limit in [
            (False, False, 8080, 3), (True, True, 8080, 3),
            (True, False, '', 3), (True, False, 1023, 3),
            (True, False, 65536, 3), (True, False, 8080, 0),
            (True, False, 8080, 21), (True, False, 8080, 'x'),
        ]:
            with self.subTest(values=(ready, repairing, port, limit)):
                with self.assertRaises(ValueError): validate_setup(ready, repairing, port, limit)

    def test_validation_accepts_bounds(self):
        self.assertEqual(validate_setup(True, False, '1024', '1'), (1024, 1))
        self.assertEqual(validate_setup(True, False, 65535, 20), (65535, 20))


if __name__ == '__main__': unittest.main()
