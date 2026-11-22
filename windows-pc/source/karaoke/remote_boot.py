"""Start the existing LAN mobile remote with the Karaoke PC application.

Only hosts in RFC1918 private networks or loopback are advertised. Never use
an external relay or a cloud account for the local remote. QR guest access
remains protected by the rotating six-digit pairing code.
"""
from __future__ import annotations

import ipaddress
import logging
import socket

_PRIVATE_LANS = tuple(ipaddress.ip_network(value) for value in
                      ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def usable_remote_ip(value):
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return False
    return address.version == 4 and any(address in network for network in _PRIVATE_LANS)


def lan_address(wifi=None, route_probe=None, host_probe=None):
    """Use the verified WLAN IP, then a private routed/Ethernet IPv4 address.

    UDP connect() discovers the selected local interface without transmitting
    any datagram or requiring an actual internet connection. Both probes may
    be injected for deterministic Windows and offline regression tests.
    """
    if wifi is not None and getattr(wifi, 'ready', False):
        ip = getattr(wifi, 'address', '')
        if usable_remote_ip(ip):
            return str(ip)

    if route_probe is None:
        def route_probe():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(('192.0.2.1', 80))
                return probe.getsockname()[0]
    try:
        ip = route_probe()
        if usable_remote_ip(ip):
            return str(ip)
    except (OSError, ValueError):
        pass

    if host_probe is None:
        def host_probe():
            return socket.gethostbyname_ex(socket.gethostname())[2]
    try:
        for ip in host_probe():
            if usable_remote_ip(ip):
                return str(ip)
    except (OSError, ValueError):
        pass
    return ''


def start_local_remote(app):
    """Idempotent startup. Guest requests ON; owner control/audio OFF."""
    if getattr(app, 'remote', None):
        return app.remote
    if not app.settings.get('remote_auto_start', True):
        return None

    from .remote import RemoteServer
    from .remote_ui import initial_policy
    from .remote_requests import RequestBook
    if not getattr(app, 'remote_requests', None):
        app.remote_requests = RequestBook()
    try:
        preferred = int(app.settings.get('remote_port', 8080))
    except (ValueError, TypeError, OverflowError):
        preferred = 8080
    if not 1024 <= preferred <= 65535:
        preferred = 8080
    ports = tuple(dict.fromkeys((preferred, 8080, 8081, 8082, 8083)))
    server = None
    error = None
    for port in ports:
        try:
            server = RemoteServer(app.library, app.dispatch_remote,
                                  app.get_remote_snapshot, port=port)
            break
        except OSError as exc:
            error = exc
            logging.info('LOCAL_REMOTE port %s unavailable: %s', port, exc)
    if server is None:
        logging.warning('LOCAL_REMOTE cannot bind: %s', error)
        if getattr(app, 'remote_quick_var', None):
            app.remote_quick_var.set('รีโมท LAN: เปิดไม่ได้ · ตรวจ Firewall/พอร์ต')
        return None

    try:
        try:
            configured_clients = int(app.settings.get('remote_max_clients', 10))
        except (TypeError, ValueError, OverflowError):
            configured_clients = 10
        server.configure(**initial_policy(app.settings),
                         max_clients=max(1, min(100, configured_clients)))
        app.remote = server
        app.update_remote_snapshot()
        server.start()
    except Exception:
        app.remote = None
        server.server.server_close()
        logging.exception('LOCAL_REMOTE startup failed')
        return None

    # Do not replace an operator's explicit display preference.
    app.settings.setdefault('remote_show_stage', True)
    app.settings.setdefault('remote_idle_only', True)
    logging.info('LOCAL_REMOTE ready, guest PIN enabled on port %s', server.port)
    return server


def refresh_local_remote(app):
    """Update the invite after Wi-Fi/Ethernet changes, on Tk's main thread."""
    from .remote_ui import sync_wifi_invite
    sync_wifi_invite(app)
    label = getattr(app, 'remote_quick_var', None)
    if label is None:
        return
    remote = getattr(app, 'remote', None)
    compact = getattr(app, '_remote_compact', False)
    if not remote:
        label.set('📱 รีโมท QR' if compact else 'รีโมท LAN: ปิด')
    elif getattr(app, 'remote_invite', None):
        label.set('📱 รีโมทพร้อม' if compact else
                  'รีโมท LAN พร้อม · ' + app.remote_invite['url'].removeprefix('http://'))
    else:
        label.set('📱 รอ LAN' if compact else 'รีโมท LAN เปิดแล้ว · รอ IP วงใน')
