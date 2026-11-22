"""Optional same-LAN WebSocket live state updates for the X-Stage PC remote.

The HTTP /api/command path remains authoritative. No websocket command,
file transfer, Google token or remote code execution is accepted here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import select
import socket
import struct
import time
from urllib.parse import urlparse

_MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11B9'
MAX_FRAME = 1024


def accept_key(value):
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 16:
            return ''
        return base64.b64encode(hashlib.sha1((value + _MAGIC).encode('ascii')).digest()).decode('ascii')
    except (ValueError, UnicodeEncodeError):
        return ''


def read_frame(stream):
    """Read a single masked, unfragmented browser control frame."""
    header = stream.read(2)
    if not header:
        return None
    if len(header) < 2:
        raise ValueError('incomplete websocket header')
    first, second = header
    if not first & 0x80 or first & 0x70:
        raise ValueError('websocket fragments/extensions not supported')
    opcode = first & 0x0f
    if opcode not in (1, 8, 9, 10):
        raise ValueError('unsupported websocket opcode')
    if not second & 0x80:
        raise ValueError('websocket clients must mask frames')
    length = second & 127
    if length == 126:
        raw = stream.read(2)
        if len(raw) != 2:
            raise ValueError('incomplete length')
        length = struct.unpack('!H', raw)[0]
    elif length == 127:
        raise ValueError('oversized websocket frame')
    if length > MAX_FRAME:
        raise ValueError('oversized websocket frame')
    mask = stream.read(4)
    data = stream.read(length)
    if len(mask) != 4 or len(data) != length:
        raise ValueError('incomplete websocket frame')
    payload = bytes(char ^ mask[i % 4] for i, char in enumerate(data))
    if opcode in (8, 9, 10):
        return opcode, payload
    return opcode, payload.decode('utf-8')


def frame_text(value):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    length = len(data)
    if length < 126:
        header = bytes((0x81, length))
    elif length <= 65535:
        header = b'\x81\x7e' + struct.pack('!H', length)
    else:
        header = b'\x81\x7f' + struct.pack('!Q', length)
    return header + data


def serve_live(handler, owner):
    """Upgrade one same-origin client, then push verified state every 500ms."""
    host = handler.headers.get('Host', '')
    origin = handler.headers.get('Origin', '')
    parsed = urlparse(origin)
    if (not origin or parsed.scheme != 'http' or parsed.netloc != host
            or handler.headers.get('Upgrade', '').lower() != 'websocket'
            or 'upgrade' not in handler.headers.get('Connection', '').lower()
            or handler.headers.get('Sec-WebSocket-Version') != '13'):
        return handler.response(403, {'error': 'WebSocket ต้องมาจากรีโมทใน LAN เท่านั้น'})
    key = handler.headers.get('Sec-WebSocket-Key', '')
    accepted = accept_key(key)
    if not accepted:
        return handler.response(400, {'error': 'WebSocket key ไม่ถูกต้อง'})
    handler.send_response(101, 'Switching Protocols')
    handler.send_header('Upgrade', 'websocket')
    handler.send_header('Connection', 'Upgrade')
    handler.send_header('Sec-WebSocket-Accept', accepted)
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    token = ''
    try:
        handler.connection.settimeout(5)
        hello = read_frame(handler.rfile)
        if not hello or hello[0] != 1:
            return
        data = json.loads(hello[1])
        token = data.get('token', '') if isinstance(data, dict) else ''
        if not isinstance(token, str) or len(token) > 256:
            return
        with owner.lock:
            owner.expire_sessions()
            if token not in owner.sessions:
                return
            owner.sessions[token]['seen'] = time.monotonic()
        # Avoid read timeouts on socket.makefile(): a timed-out BufferedReader
        # may become permanently unusable. Read only when select says data
        # exists, and terminate on an incomplete or deliberately stalled frame.
        handler.connection.settimeout(3)
        while True:
            with owner.lock:
                owner.expire_sessions()
                current = owner.sessions.get(token)
                if not current:
                    return
                session = dict(current)
            payload = {'type': 'state', 'data': handler.state_for(session)}
            handler.connection.sendall(frame_text(payload))
            readable, _, _ = select.select([handler.connection], [], [], .5)
            if not readable:
                continue
            frame = read_frame(handler.rfile)
            if frame is None or frame[0] == 8:
                return
            if frame[0] == 9:
                continue  # Browsers do not send application-level WS ping frames.
            if frame[0] != 1:
                continue
            try:
                body = json.loads(frame[1])
            except (ValueError, TypeError):
                return
            if not isinstance(body, dict) or body.get('type') != 'ping':
                return
            # Only active foreground browsers keep their guest session alive.
            with owner.lock:
                if token in owner.sessions:
                    owner.sessions[token]['seen'] = time.monotonic()
    except (ConnectionError, OSError, ValueError, TypeError, UnicodeError):
        return
    except Exception:
        logging.exception('LOCAL_REMOTE live status failed')
