import ctypes as C
import socket,struct,threading,unittest
from types import SimpleNamespace as NS
from karaoke.wifi_network import DWORD,Interface,ConnectionPrefix,IPRow,WifiState,WifiMonitor,select_network,usable_ipv4,_windows_wifi
from karaoke.remote_ui import sync_wifi_invite
class Fn:
    def __init__(self,fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)
def put(p,t,v):C.cast(p,C.POINTER(t))[0]=v
class NativeFixture:
    def __init__(self,state=1,error=0,count=1):
        self.freed=[];self.closed=[]
        table=C.create_string_buffer(8+C.sizeof(Interface));put(table,DWORD,count)
        Interface.from_buffer(table,8).state=state
        conn=ConnectionPrefix();conn.state=1;raw='เวที-Stage'.encode();conn.ssid.length=len(raw);conn.ssid.data[:len(raw)]=raw
        self.keep=[table,conn]
        def opening(v,r,n,h):put(h,C.c_void_p,123);return 0
        def enum(h,r,p):put(p,C.c_void_p,C.addressof(table));return 0
        def query(h,g,op,r,size,data,kind):
            self.opcode=op
            if error:return error
            put(size,DWORD,C.sizeof(conn));put(data,C.c_void_p,C.addressof(conn));return 0
        def luid(g,p):put(p,C.c_uint64,700);return 0
        def index(l,p):put(p,DWORD,7);return 0
        def ips(b,size,ordered):
            if not b:put(size,DWORD,4+2*C.sizeof(IPRow));return 122
            put(b,DWORD,2)
            for n,(idx,addr) in enumerate([(2,'10.10.0.2'),(7,'192.168.8.20')]):
                row=IPRow.from_buffer(b,4+n*C.sizeof(IPRow));row.index=idx;row.address=struct.unpack('=I',socket.inet_aton(addr))[0]
            return 0
        self.wlan=NS(WlanOpenHandle=Fn(opening),WlanCloseHandle=Fn(lambda h,r:self.closed.append(h.value) or 0),WlanEnumInterfaces=Fn(enum),WlanQueryInterface=Fn(query),WlanFreeMemory=Fn(lambda p:self.freed.append(p.value)))
        self.ip=NS(ConvertInterfaceGuidToLuid=Fn(luid),ConvertInterfaceLuidToIndex=Fn(index),GetIpAddrTable=Fn(ips))
class WifiTests(unittest.TestCase):
    def test_windows_layout(self):
        self.assertEqual(C.sizeof(Interface),532);self.assertEqual(ConnectionPrefix.ssid.offset,520)
        self.assertEqual(C.sizeof(ConnectionPrefix),556);self.assertEqual(C.sizeof(IPRow),24)
    def test_native_same_adapter_and_cleanup(self):
        f=NativeFixture();s=_windows_wifi(f.wlan,f.ip)
        self.assertTrue(s.ready);self.assertEqual(s.ssid,'เวที-Stage');self.assertEqual(s.address,'192.168.8.20')
        self.assertEqual(f.opcode,7);self.assertEqual(len(f.freed),2);self.assertEqual(f.closed,[123])
    def test_no_adapter(self):
        f=NativeFixture(count=0);self.assertEqual(_windows_wifi(f.wlan,f.ip).status,'no_adapter');self.assertEqual(f.closed,[123])
    def test_disconnected_not_lan(self):
        f=NativeFixture(state=4);self.assertEqual(_windows_wifi(f.wlan,f.ip).status,'disconnected')
    def test_permission_error(self):
        f=NativeFixture(error=5);s=_windows_wifi(f.wlan,f.ip)
        self.assertEqual(s.status,'denied');self.assertIn('ตำแหน่ง',s.message);self.assertEqual(f.closed,[123])
    def test_no_ip_no_other_adapter_fallback(self):
        self.assertEqual(select_network([(7,'Stage')],{2:['192.168.0.5']}).status,'no_ip')
    def test_bad_ips(self):
        for a in ['127.0.0.1','169.254.1.2','0.0.0.0','224.0.0.1','bad']:self.assertFalse(usable_ipv4(a))
        self.assertEqual(select_network([(7,'Stage')],{7:['169.254.1.1','192.168.1.7']}).address,'192.168.1.7')
    def test_second_wifi_usable(self):
        self.assertEqual(select_network([(3,'First'),(7,'Second')],{7:['10.0.0.7']}).ssid,'Second')
    def test_monitor_background_and_close(self):
        event=threading.Event();ids=[]
        def reader():ids.append(threading.get_ident());event.set();return WifiState('connected','Stage','10.0.0.2')
        m=WifiMonitor(reader);self.assertTrue(event.wait(1));m.close();m.thread.join(1)
        self.assertNotEqual(ids[0],threading.get_ident());self.assertFalse(m.thread.is_alive());self.assertTrue(m.snapshot().ready)
    def test_invite_disconnect_and_change_even_when_window_closed(self):
        state=[WifiState('connected','Stage','192.168.1.20')]
        app=NS(_wifi_monitor=NS(snapshot=lambda:state[0]),remote=NS(port=8080,request_key='123456',policy={},capacity_stats=lambda:(0,0),configure=lambda **kw:None),settings={},remote_invite=None)
        sync_wifi_invite(app);old=app.remote_invite;self.assertEqual(old['wifi'],'Stage')
        sync_wifi_invite(app);self.assertIs(app.remote_invite,old)
        state[0]=WifiState('disconnected');sync_wifi_invite(app);self.assertIsNone(app.remote_invite)
        state[0]=WifiState('connected','New','192.168.2.30');sync_wifi_invite(app)
        self.assertEqual(app.remote_invite['wifi'],'New');self.assertIn('192.168.2.30',app.remote_invite['url'])
    def test_no_server_no_invite(self):
        app=NS(_wifi_monitor=NS(snapshot=lambda:WifiState('connected','Stage','10.0.0.2')),remote=None,remote_invite={'old':1})
        sync_wifi_invite(app);self.assertIsNone(app.remote_invite)
    def test_query_failure_cleanup(self):
        f=NativeFixture(error=5023);self.assertFalse(_windows_wifi(f.wlan,f.ip).ready)
        self.assertEqual(len(f.freed),1);self.assertEqual(f.closed,[123])
