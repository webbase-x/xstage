"""Real local TCP/WebSocket regression using only Python standard library."""
import base64
import io
import json
import os
import socket
import struct
import unittest
from types import SimpleNamespace as NS

from karaoke.remote import RemoteServer
from karaoke.remote_socket import accept_key, frame_text, read_frame


def exactly(sock, size):
    data=bytearray()
    while len(data)<size:
        part=sock.recv(size-len(data))
        if not part:
            raise EOFError('Socket closed before complete frame')
        data.extend(part)
    return bytes(data)


def masked_text(value):
    data=json.dumps(value,separators=(',', ':')).encode('utf-8')
    mask=os.urandom(4)
    if len(data)<126:
        header=bytes([0x81,0x80|len(data)])
    elif len(data)<65536:
        header=b'\x81\xfe'+struct.pack('!H',len(data))
    else:
        raise ValueError('test payload too large')
    return header+mask+bytes(x^mask[i%4] for i,x in enumerate(data))


def read_server_message(sock):
    first,second=exactly(sock,2)
    assert first==0x81 and not second&0x80, 'server must send unmasked UTF-8 text'
    size=second&127
    if size==126:size=struct.unpack('!H',exactly(sock,2))[0]
    elif size==127:size=struct.unpack('!Q',exactly(sock,8))[0]
    if size>200000:
        raise AssertionError('Unexpected oversized server payload')
    return json.loads(exactly(sock,size))


class LiveSocketTests(unittest.TestCase):
    def setUp(self):
        self.remote=RemoteServer(
            NS(search=lambda query,limit:[]),
            lambda command:{'ok':True},
            lambda:dict(title='เพลงทดสอบ',playing=True,requests=[],queue=[]),
            host='127.0.0.1',port=0)
        self.remote.start()

    def tearDown(self):
        self.remote.close()

    def pair(self):
        import http.client
        connection=http.client.HTTPConnection('127.0.0.1',self.remote.port,timeout=3)
        connection.request('POST','/api/login',body=json.dumps({
            'code':self.remote.request_key
        }),headers={'Content-Type':'application/json'})
        reply=connection.getresponse()
        data=json.loads(reply.read())
        connection.close()
        self.assertEqual(reply.status,200)
        return data['token']

    def websocket(self, origin=None, key=None):
        sock=socket.create_connection(('127.0.0.1',self.remote.port),timeout=4)
        sock.settimeout(4)
        key=key or base64.b64encode(os.urandom(16)).decode('ascii')
        host=f'127.0.0.1:{self.remote.port}'
        origin=origin if origin is not None else 'http://'+host
        request=(
            'GET /api/live HTTP/1.1\r\n'
            f'Host: {host}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Version: 13\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            f'Origin: {origin}\r\n\r\n'
        ).encode('ascii')
        sock.sendall(request)
        data=bytearray()
        while b'\r\n\r\n' not in data:
            data.extend(exactly(sock,1))
            if len(data)>4096:
                raise AssertionError('Unexpected HTTP handshake')
        return sock,data.decode('latin1'),key

    def test_real_handshake_and_authorized_stage_updates(self):
        token=self.pair()
        sock,headers,key=self.websocket()
        try:
            self.assertIn('101 Switching Protocols',headers)
            self.assertIn('Sec-WebSocket-Accept: '+accept_key(key),headers)
            sock.sendall(masked_text({'token':token}))
            result=read_server_message(sock)
            self.assertEqual(result['type'],'state')
            self.assertEqual(result['data']['title'],'เพลงทดสอบ')
            self.assertEqual(result['data']['queue'],[])
            self.assertNotIn('requests',result['data'])
            self.assertFalse(result['data']['operator'])
            self.assertEqual(result['data']['mine'],[])
            sock.sendall(masked_text({'type':'ping'}))
            self.assertEqual(read_server_message(sock)['type'],'state')
        finally:
            sock.close()

    def test_rotation_invalidates_live_connection(self):
        token=self.pair()
        sock,headers,_=self.websocket()
        try:
            self.assertIn('101',headers)
            sock.sendall(masked_text({'token':token}))
            self.assertEqual(read_server_message(sock)['type'],'state')
            self.remote.rotate_codes()
            # The server must not stream another authenticated snapshot.
            self.assertEqual(sock.recv(1),b'')
        finally:
            sock.close()

    def test_cross_site_websocket_origin_rejected(self):
        sock,headers,_=self.websocket(origin='https://evil.example')
        try:self.assertIn('403',headers)
        finally:sock.close()

    def test_masked_browser_frames_only(self):
        self.assertTrue(accept_key(base64.b64encode(os.urandom(16)).decode('ascii')))
        self.assertEqual(accept_key('bad'), '')
        with self.assertRaisesRegex(ValueError,'mask'):
            read_frame(io.BytesIO(b'\x81\x02hi'))
        self.assertEqual(read_frame(io.BytesIO(masked_text({'type':'ping'})))[0],1)
        self.assertEqual(frame_text({'ok':True})[:1],b'\x81')

    def test_dns_rebinding_host_rejected(self):
        import http.client
        connection=http.client.HTTPConnection('127.0.0.1',self.remote.port,timeout=3)
        connection.putrequest('GET','/',skip_host=True)
        connection.putheader('Host',f'evil.example:{self.remote.port}')
        connection.endheaders()
        reply=connection.getresponse()
        self.assertEqual(reply.status,403)
        reply.read()
        connection.close()


if __name__=='__main__':
    unittest.main()
