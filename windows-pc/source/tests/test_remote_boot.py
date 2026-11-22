"""LAN remote must be usable at PC startup, even on wired Windows PCs."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from karaoke.remote_boot import (
    lan_address, usable_remote_ip, refresh_local_remote, start_local_remote,
)
from karaoke.remote_ui import sync_wifi_invite


class RemoteBootTests(unittest.TestCase):
    def app(self, **settings):
        return NS(remote=None, remote_invite=None, settings=settings,
                  library=object(), dispatch_remote=Mock(), get_remote_snapshot=Mock(),
                  update_remote_snapshot=Mock(), remote_requests=object(),
                  remote_quick_var=NS(set=Mock()))

    def test_only_private_lan_addresses_are_advertised(self):
        for address in ('192.168.1.6', '172.16.0.1', '172.31.255.250', '10.0.0.9'):
            self.assertTrue(usable_remote_ip(address), address)
        for address in ('127.0.0.1', '169.254.1.8', '8.8.8.8',
                        '172.32.1.2', '0.0.0.0', '::1', 'bad', ''):
            self.assertFalse(usable_remote_ip(address), address)

    def test_wlan_has_priority_over_ethernet_route(self):
        wifi=NS(ready=True, address='192.168.2.12')
        self.assertEqual(lan_address(wifi, lambda: '10.0.0.3',
                                     lambda: ['172.16.3.2']), '192.168.2.12')

    def test_ethernet_fallback_when_wifi_permission_denied(self):
        wifi=NS(ready=False, address='')
        self.assertEqual(lan_address(wifi, lambda: '192.168.50.8',
                                     lambda: []), '192.168.50.8')

    def test_host_adapter_fallback_when_no_default_route(self):
        def unavailable():
            raise OSError('no default route')
        self.assertEqual(lan_address(None, unavailable, lambda: [
            '127.0.0.1', '8.8.8.8', '10.5.1.14']), '10.5.1.14')
        self.assertEqual(lan_address(None, unavailable, lambda: ['127.0.0.1']), '')

    def test_auto_start_guest_only_is_idempotent(self):
        app=self.app()
        server=NS(port=8080, policy={}, configure=Mock(), start=Mock(),
                  server=NS(server_close=Mock()))
        with patch('karaoke.remote.RemoteServer', return_value=server) as create:
            first=start_local_remote(app)
            second=start_local_remote(app)
        self.assertIs(first, server)
        self.assertIs(second, server)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(server.start.call_count, 1)
        values=server.configure.call_args.kwargs
        self.assertTrue(values['accepting'])
        self.assertFalse(values['operator'])
        self.assertFalse(values['audio'])
        self.assertEqual(values['max_clients'], 10)
        self.assertTrue(app.settings['remote_show_stage'])
        self.assertTrue(app.settings['remote_idle_only'])
        self.assertEqual(app.update_remote_snapshot.call_count, 1)

    def test_explicit_stop_preference_prevents_auto_start(self):
        app=self.app(remote_auto_start=False)
        with patch('karaoke.remote.RemoteServer') as create:
            self.assertIsNone(start_local_remote(app))
        create.assert_not_called()

    def test_bind_conflict_tries_alternate_port_without_crashing(self):
        app=self.app(remote_port=8080)
        server=NS(port=8081, configure=Mock(), start=Mock(),
                  server=NS(server_close=Mock()))
        with patch('karaoke.remote.RemoteServer',
                   side_effect=[OSError('address in use'),server]) as create:
            self.assertIs(start_local_remote(app), server)
        self.assertEqual([c.kwargs['port'] for c in create.call_args_list],
                         [8080, 8081])
        server.start.assert_called_once()

    def test_bad_persisted_client_limit_does_not_prevent_startup(self):
        app=self.app(remote_max_clients='not-a-number', remote_port='bad')
        server=NS(port=8080, configure=Mock(), start=Mock(),
                  server=NS(server_close=Mock()))
        with patch('karaoke.remote.RemoteServer', return_value=server) as create:
            self.assertIs(start_local_remote(app),server)
        self.assertEqual(create.call_args.kwargs['port'],8080)
        self.assertEqual(server.configure.call_args.kwargs['max_clients'],10)

    def test_wired_ethernet_qr_invite_and_compact_toolbar(self):
        app=self.app(remote_capacity_auto=False)
        app.remote=NS(port=8080, request_key='123456')
        app._remote_compact=True
        app._wifi_monitor=NS(snapshot=lambda:NS(
            ready=False, address='', status='denied', ssid=''))
        with patch('karaoke.remote_boot.lan_address',
                   return_value='192.168.50.8'):
            with patch('karaoke.remote_ui.make_invite', side_effect=lambda ip,port,code,wifi:
                {'url':f'http://{ip}:{port}/','code':code,'wifi':wifi}) as qr:
                sync_wifi_invite(app)
                refresh_local_remote(app)
        self.assertEqual(app.remote_invite['url'],'http://192.168.50.8:8080/')
        self.assertEqual(app.remote_invite['code'],'123456')
        self.assertEqual(qr.call_count,1,'An unchanged IP+PIN must reuse the QR')
        app.remote_quick_var.set.assert_called_with('📱 รีโมทพร้อม')


if __name__ == '__main__':
    unittest.main()
