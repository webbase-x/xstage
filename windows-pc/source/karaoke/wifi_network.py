"""Read connected Windows WLAN SSID and IPv4 from the same adapter, no shell parsing."""
import ctypes as C
import ipaddress
import os
import socket
import struct
from dataclasses import dataclass

DWORD=C.c_uint32
class GUID(C.Structure):
    _fields_=[('data',C.c_ubyte*16)]
class Interface(C.Structure):
    _fields_=[('guid',GUID),('description',C.c_uint16*256),('state',DWORD)]
class SSID(C.Structure):
    _fields_=[('length',DWORD),('data',C.c_ubyte*32)]
class ConnectionPrefix(C.Structure):
    _fields_=[('state',DWORD),('mode',DWORD),('profile',C.c_uint16*256),('ssid',SSID)]
class Association(C.Structure):
    _fields_=[('ssid',SSID),('bss_type',DWORD),('bssid',C.c_ubyte*6),('phy',DWORD),('phy_index',DWORD),('signal',DWORD),('rx',DWORD),('tx',DWORD)]
class Connection(C.Structure):
    _fields_=[('state',DWORD),('mode',DWORD),('profile',C.c_uint16*256),('association',Association)]
class IPRow(C.Structure):
    _fields_=[('address',DWORD),('index',DWORD),('mask',DWORD),('broadcast',DWORD),('reassembly',DWORD),('unused',C.c_uint16),('kind',C.c_uint16)]

@dataclass(frozen=True)
class WifiState:
    status: str
    ssid: str=''
    address: str=''
    message: str=''
    signal: int=0
    rx_mbps: float=0
    tx_mbps: float=0
    @property
    def ready(self):return self.status=='connected' and bool(self.ssid and self.address)


def usable_ipv4(value):
    try:
        ip=ipaddress.IPv4Address(value)
        return not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved)
    except ipaddress.AddressValueError:return False


def select_network(networks, addresses, denied=False):
    for network in networks:
        index,ssid=network[:2]
        metrics=network[2] if len(network)>2 else {}
        for address in addresses.get(index,[]):
            if ssid and usable_ipv4(address):
                return WifiState('connected',ssid,address,'ให้มือถือเชื่อมต่อ Wi-Fi: '+ssid,**metrics)
    if networks:return WifiState('no_ip',message='เชื่อมต่อ Wi-Fi แล้ว แต่ยังไม่มี IPv4 ที่ใช้งานได้ กรุณารอรับ IP หรือตรวจสอบเครือข่าย')
    if denied:return WifiState('denied',message='Windows ไม่อนุญาตให้อ่านชื่อ Wi-Fi กรุณาเปิดสิทธิ์ตำแหน่งที่ตั้งสำหรับแอปเดสก์ท็อป แล้วตรวจสอบอีกครั้ง')
    return WifiState('disconnected',message='เครื่องหลักยังไม่ได้เชื่อมต่อ Wi-Fi กรุณาเชื่อมต่อ Wi-Fi ก่อนเปิดรีโมท')


def _function(dll,name,args,result=DWORD):
    fn=getattr(dll,name);fn.argtypes=args;fn.restype=result;return fn


def _windows_wifi(wlan,ip):
    ptr=C.c_void_p
    open_client=_function(wlan,'WlanOpenHandle',[DWORD,ptr,C.POINTER(DWORD),C.POINTER(ptr)])
    close_client=_function(wlan,'WlanCloseHandle',[ptr,ptr])
    enum=_function(wlan,'WlanEnumInterfaces',[ptr,ptr,C.POINTER(ptr)])
    query=_function(wlan,'WlanQueryInterface',[ptr,C.POINTER(GUID),C.c_int,ptr,C.POINTER(DWORD),C.POINTER(ptr),C.POINTER(C.c_int)])
    free=_function(wlan,'WlanFreeMemory',[ptr],None)
    to_luid=_function(ip,'ConvertInterfaceGuidToLuid',[C.POINTER(GUID),C.POINTER(C.c_uint64)])
    to_index=_function(ip,'ConvertInterfaceLuidToIndex',[C.POINTER(C.c_uint64),C.POINTER(DWORD)])
    get_ips=_function(ip,'GetIpAddrTable',[ptr,C.POINTER(DWORD),C.c_int])
    handle=ptr();version=DWORD();listed=ptr()
    error=open_client(2,None,C.byref(version),C.byref(handle))
    if error:
        if error==1062:return WifiState('service_off',message='บริการ Wi-Fi ของ Windows ยังไม่ทำงาน กรุณาเปิด Wi-Fi และเชื่อมต่อเครือข่าย')
        if error==5:return select_network([],{},True)
        raise OSError(error,'WlanOpenHandle')
    try:
        error=enum(handle,None,C.byref(listed))
        if error==5:return select_network([],{},True)
        if error:raise OSError(error,'WlanEnumInterfaces')
        count=C.cast(listed,C.POINTER(DWORD))[0]
        if not count:return WifiState('no_adapter',message='ไม่พบอะแดปเตอร์ Wi-Fi กรุณาติดตั้ง/เปิดใช้งาน Wi-Fi แล้วเชื่อมต่อเครือข่าย')
        networks=[];denied=False;query_failed=False
        for n in range(min(count,64)):
            info=Interface.from_address(listed.value+8+n*C.sizeof(Interface))
            if info.state!=1:continue
            data=ptr();size=DWORD();kind=C.c_int()
            try:
                error=query(handle,C.byref(info.guid),7,None,C.byref(size),C.byref(data),C.byref(kind))
                if error==5:denied=True;continue
                if error:query_failed=True;continue
                if not data.value or size.value<C.sizeof(ConnectionPrefix):continue
                connection=C.cast(data,C.POINTER(ConnectionPrefix)).contents
                if connection.state!=1 or not 0<connection.ssid.length<=32:continue
                raw=bytes(connection.ssid.data[:connection.ssid.length])
                try:ssid=raw.decode('utf-8')
                except UnicodeDecodeError:ssid=raw.decode('cp874',errors='replace')
                luid=C.c_uint64();index=DWORD()
                if to_luid(C.byref(info.guid),C.byref(luid)) or to_index(C.byref(luid),C.byref(index)):
                    query_failed=True;continue
                metrics={}
                if size.value>=C.sizeof(Connection):
                    association=C.cast(data,C.POINTER(Connection)).contents.association
                    metrics=dict(signal=min(100,association.signal),rx_mbps=association.rx/1000,tx_mbps=association.tx/1000)
                networks.append((index.value,ssid,metrics))
            finally:
                if data.value:free(data)
        size=DWORD();error=get_ips(None,C.byref(size),False)
        addresses={}
        if error in (0,122) and size.value:
            for _ in range(3):
                buffer=C.create_string_buffer(size.value)
                error=get_ips(buffer,C.byref(size),False)
                if error==122:continue
                if error:break
                count=C.cast(buffer,C.POINTER(DWORD))[0]
                if 4+count*C.sizeof(IPRow)>len(buffer):break
                for n in range(count):
                    row=IPRow.from_buffer(buffer,4+n*C.sizeof(IPRow))
                    if row.kind & 0x48:continue
                    addresses.setdefault(row.index,[]).append(socket.inet_ntoa(struct.pack('=I',row.address)))
                break
        if query_failed and not networks and not denied:
            return WifiState('error',message='อ่านข้อมูล Wi-Fi ไม่สำเร็จ กรุณาตรวจสอบเครือข่ายแล้วลองใหม่')
        return select_network(networks,addresses,denied)
    finally:
        if listed.value:free(listed)
        close_client(handle,None)


def detect_wifi():
    if os.name!='nt':return WifiState('unsupported',message='การตรวจชื่อ Wi-Fi อัตโนมัติรองรับบน Windows กรุณาเปิดโปรแกรมบน Windows')
    try:return _windows_wifi(C.WinDLL('wlanapi'),C.WinDLL('iphlpapi'))
    except (OSError,AttributeError,ValueError) as e:
        return WifiState('error',message='ตรวจสอบ Wi-Fi ไม่สำเร็จ กรุณาตรวจการเชื่อมต่อแล้วลองใหม่ (รหัส '+str(getattr(e,'errno',None) or 'API')+')')


class WifiMonitor:
    """One background reader; Tk only reads immutable results. No playback blocking."""
    def __init__(self,reader=detect_wifi):
        import threading
        self.reader=reader;self.state=WifiState('checking',message='กำลังตรวจสอบ Wi-Fi ของเครื่องหลัก…')
        self.lock=threading.Lock();self.stop_event=threading.Event();self.wake_event=threading.Event()
        self.thread=threading.Thread(target=self._run,daemon=True,name='wifi-monitor')
        self.thread.start()
    def _run(self):
        while not self.stop_event.is_set():
            try:state=self.reader()
            except Exception:state=WifiState('error',message='ตรวจสอบ Wi-Fi ไม่สำเร็จ กรุณาลองใหม่')
            with self.lock:self.state=state
            self.wake_event.wait(5);self.wake_event.clear()
    def snapshot(self):
        with self.lock:return self.state
    def refresh(self):self.wake_event.set()
    def close(self):self.stop_event.set();self.wake_event.set()
