import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.legacy import dbf_records, import_catalog, parse_ncn_lyrics, safe_code
from karaoke.library import SongLibrary
from karaoke.smf import parse_midi
from karaoke.emk import unpack_emk, parse_emk, LEGACY_MASK
from karaoke.remote import RemoteServer
from karaoke.stage import lyric_progress
from karaoke.lyrics import parse_lrc
from tools.make_demo import meta, vlq


def midi_fixture():
    track = b'\0' + meta(0x51,(500000).to_bytes(3,'big')) + b'\0\x90\x3c\x40' + vlq(480) + meta(0x51,(1000000).to_bytes(3,'big')) + vlq(480) + b'\x80\x3c\0\0' + meta(0x2f,b'')
    return b'MThd'+struct.pack('>IHHH',6,0,1,480)+b'MTrk'+struct.pack('>I',len(track))+track


def dbf_fixture():
    fields = [('CODE',8),('TYPE',8),('SUB_TYPE',8),('TITLE',40),('ARTIST',30),('FILE_NAME',20)]
    header_length = 33+len(fields)*32
    record_length = 1+sum(width for _,width in fields)
    header = bytearray(32)
    header[0] = 3
    struct.pack_into('<IHH',header,4,2,header_length,record_length)
    descriptors=bytearray()
    for name,width in fields:
        descriptor=bytearray(32)
        descriptor[:len(name)]=name.encode()
        descriptor[11]=ord('C')
        descriptor[16]=width
        descriptors+=descriptor
    values=['A1','MIDI','NCN','ทดสอบภาษาไทย','คนร้อง','A1.mid']
    record=b' '+b''.join(value.encode('cp874').ljust(width,b' ') for value,(_,width) in zip(values,fields))
    return bytes(header)+descriptors+b'\r'+record+b'*'+record[1:]+b'\x1a'


def archive_fixture(masked=True, assets=None):
    assets=assets or {'MIDI_DATA':midi_fixture(),'LYRIC_DATA':'เพลง\r\nคน\r\nC\r\n.\r\nกข\r\n'.encode('cp874'),'CURSOR_DATA':struct.pack('<4H',0,0,24,65535)}
    body=bytearray(64)
    body[:5]=b'.SFDS'
    entries=[]
    def number(value):
        return b'\x04'+struct.pack('<I',value)
    for tag,payload in assets.items():
        start=len(body)
        body+=zlib.compress(payload)
        encoded=tag.encode()
        entries.append(b'SFDS\x06'+bytes([len(encoded)])+encoded+b''.join(number(v) for v in (len(payload),0,start,len(body),1,0))+hashlib.md5(payload).digest()+b'\x06\0\x02\0')
    start=len(body)
    body+=b''.join(entries)
    struct.pack_into('<QQ',body,0x22,start,len(body))
    return bytes(value^LEGACY_MASK[i%8] for i,value in enumerate(body)) if masked else bytes(body)


class FormatTests(unittest.TestCase):
    def test_dbf_stream_encoding_and_deleted_record(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'songs.dbf'
            file.write_bytes(dbf_fixture())
            records=list(dbf_records(file))
            self.assertEqual(len(records),1)
            self.assertEqual(records[0]['TITLE'],'ทดสอบภาษาไทย')

    def test_dbf_truncated_record_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'songs.dbf'
            file.write_bytes(dbf_fixture()[:-80])
            with self.assertRaises(ValueError):
                list(dbf_records(file))

    def test_catalog_paths_and_user_edits_survive_reindex(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'Data').mkdir()
            (root/'Data'/'SONG.DBF').write_bytes(dbf_fixture())
            media=root/'Songs/MIDI/NCN/Song/A/A1.mid'
            media.parent.mkdir(parents=True)
            media.write_bytes(midi_fixture())
            library=SongLibrary(root/'new.sqlite3')
            self.assertEqual(import_catalog(root,library),(1,0,0))
            song=library.search('ทดสอบ')[0]
            self.assertTrue(song['path'].endswith(str(Path('NCN')/'Song'/'A'/'A1.mid').lower()) if sys.platform=='win32' else song['path'].endswith('NCN/Song/A/A1.mid'))
            library.edit(song['id'],'X','ชื่อที่แก้เอง','ศิลปินใหม่')
            import_catalog(root,library)
            self.assertEqual(library.search('ชื่อที่แก้เอง')[0]['id'],song['id'])
            self.assertEqual(library.get(song['id'])['title'],'ชื่อที่แก้เอง')

    def test_catalog_code_traversal_rejected(self):
        for code in ('../song',r'..\song','C:secret',''):
            with self.assertRaises(ValueError):
                safe_code(code)

    def test_tempo_map_converts_cursor_in_musical_time(self):
        song=parse_midi(midi_fixture())
        lyrics=parse_ncn_lyrics('เพลง\nคน\nC\n.\nกข\n'.encode('cp874'),struct.pack('<4H',0,0,48,65535),song)
        self.assertEqual(lyrics.lines[0].text,'กข')
        self.assertAlmostEqual(lyrics.lines[0].words[-1][0],1.5)
        self.assertAlmostEqual(song.seconds_tick(1.5),960)

    def test_thai_marks_share_glyph_time_without_losing_cursor(self):
        song=parse_midi(midi_fixture())
        lyrics=parse_ncn_lyrics('a\nb\nC\n.\nกิข\n'.encode('cp874'),struct.pack('<5H',0,0,12,24,65535),song)
        self.assertEqual(lyrics.lines[0].words[0],(0.,'กิ'))
        self.assertEqual(lyrics.lines[0].words[1],(.5,'ข'))

    def test_short_cursor_rejected_instead_of_inventing_timestamps(self):
        with self.assertRaises(ValueError):
            parse_ncn_lyrics(b'a\nb\nc\n.\nABCD',b'\0\0',parse_midi(midi_fixture()))

    def test_untimed_nick_footer_does_not_hide_the_song(self):
        song=parse_midi(midi_fixture())
        for footer in ('นิค_คาราโอเกะ','Nick_Karaoke Professional','Nick Karaoke'):
            raw=('เพลง\r\nศิลปิน\r\nC\r\n.\r\nกข\r\n'+footer+'\r\n\r\n').encode('cp874')
            lyrics=parse_ncn_lyrics(raw,struct.pack('<3H',0,0,24),song)
            self.assertEqual([line.text for line in lyrics.lines],['กข'])
            self.assertAlmostEqual(lyrics.lines[0].words[1][0],.5)
            self.assertGreater(lyrics.removed_footer_lines,0)

    def test_partial_cursor_retains_known_timed_text(self):
        lyrics=parse_ncn_lyrics(b'a\nb\nC\n.\nABCD',struct.pack('<3H',0,0,24),parse_midi(midi_fixture()))
        self.assertEqual(lyrics.lines[0].text,'AB')
        self.assertEqual(lyrics.lines[0].words,[(0.,'A'),(.5,'B')])
        self.assertTrue(lyrics.warnings)

    def test_invalid_trailing_cue_does_not_erase_earlier_lyrics(self):
        lyrics=parse_ncn_lyrics(b'a\nb\nC\n.\nABC',struct.pack('<4H',0,0,24,60000),parse_midi(midi_fixture()))
        self.assertEqual(lyrics.lines[0].text,'AB')
        self.assertTrue(lyrics.warnings)

    def test_footer_name_inside_timed_text_is_preserved(self):
        lyrics=parse_ncn_lyrics(b'a\nb\nC\n.\nNick_Karaoke\nAB',struct.pack('<20H',*([0]*20)),parse_midi(midi_fixture()))
        self.assertEqual([line.text for line in lyrics.lines],['Nick_Karaoke','AB'])

    def test_unused_incomplete_cursor_tail_is_ignored(self):
        lyrics=parse_ncn_lyrics(b'a\nb\nC\n.\nAB',struct.pack('<3H',0,0,24)+b'\x3d',parse_midi(midi_fixture()))
        self.assertEqual(lyrics.lines[0].text,'AB')
        self.assertTrue(lyrics.warnings)

    def test_legacy_ncn_header_explicit(self):
        data=b'NCN1'+midi_fixture()[4:]
        with self.assertRaises(ValueError):
            parse_midi(data)
        self.assertEqual(len(parse_midi(data,legacy=True).events),2)

    def test_emk_plain_and_historical_profile(self):
        for masked in (False,True):
            song=parse_emk(archive_fixture(masked))
            self.assertEqual(song.lyrics.lines[0].text,'กข')
            self.assertAlmostEqual(song.duration,1.5)

    def test_emk_checksum_corruption_rejected(self):
        data=bytearray(archive_fixture(False))
        data[70]^=1
        with self.assertRaises((ValueError,zlib.error)):
            unpack_emk(bytes(data))

    def test_emk_offset_outside_archive_rejected(self):
        data=bytearray(archive_fixture(False))
        struct.pack_into('<QQ',data,0x22,len(data)+1,len(data)+100)
        with self.assertRaises(ValueError):
            unpack_emk(bytes(data))

    def test_emk_without_lyrics_keeps_music_and_reports_warning(self):
        song=parse_emk(archive_fixture(assets={'MIDI_DATA':midi_fixture()}))
        self.assertTrue(song.events)
        self.assertTrue(song.lyric_warning)

    def test_smooth_wipe_uses_known_anchor_interval(self):
        lyrics=parse_lrc('[00:01.00]<00:01.00>ก<00:02.00>ข')
        current,nextline,prefix,word,fraction=lyric_progress(lyrics,1.5)
        self.assertEqual((prefix,word),('','ก'))
        self.assertAlmostEqual(fraction,.5)


class RemoteProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.library=SongLibrary(self.root/'songs.sqlite3')
        file=self.root/'demo.mid'
        file.write_bytes(midi_fixture())
        self.song_id=self.library.add_files([file])[0]
        self.commands=[]
        def dispatch(value):
            self.commands.append(value)
            return {'ok':True}
        self.remote=RemoteServer(self.library,dispatch,lambda:{'title':'ทดสอบ','queue':[]},host='127.0.0.1',port=0)
        self.remote.configure(operator=True)
        self.tokens={}
        self.remote.start()
        self.url=f'http://127.0.0.1:{self.remote.port}'

    def tearDown(self):
        self.remote.close()
        self.temp.cleanup()

    def call(self,url,key='',body=None,origin=None):
        if key in (self.remote.request_key,self.remote.operator_key):
            if key not in self.tokens:
                self.tokens[key]=self.call('/api/login',body={'code':key})['token']
            key=self.tokens[key]
        headers={'Authorization':'Bearer '+key}
        if origin:
            headers['Origin']=origin
        payload=b'' if body is None else json.dumps(body).encode()
        headers['Host']='127.0.0.1:'+str(self.remote.port)
        headers['Content-Length']=str(len(payload))
        wire=(('POST' if body is not None else 'GET')+' '+url+' HTTP/1.0\r\n'+'\r\n'.join(k+': '+v for k,v in headers.items())+'\r\n\r\n').encode()+payload
        class MemoryConnection:
            def __init__(self):
                self.input=io.BytesIO(wire)
                self.output=bytearray()
            def makefile(self,*_):
                return self.input
            def sendall(self,data):
                self.output.extend(data)
        connection=MemoryConnection()
        self.remote.server.RequestHandlerClass(connection,('127.0.0.1',12345),self.remote.server)
        header,result=bytes(connection.output).split(b'\r\n\r\n',1)
        code=int(header.split(b' ')[1])
        if code>=400:
            raise urllib.error.HTTPError(self.url+url,code,'Request rejected',{},None)
        return json.loads(result)

    def test_guest_can_search_but_paths_are_private(self):
        data=self.call('/api/songs?q=demo',self.remote.request_key)
        self.assertEqual(data['songs'][0]['id'],self.song_id)
        self.assertNotIn('path',data['songs'][0])

    def test_missing_key_and_guest_transport_rejected(self):
        for key,body,code in [('',None,401),(self.remote.request_key,{'action':'stop'},403)]:
            with self.assertRaises(urllib.error.HTTPError) as result:
                self.call('/api/state' if body is None else '/api/command',key,body)
            self.assertEqual(result.exception.code,code)

    def test_duplicate_request_does_not_add_twice(self):
        command={'action':'queue','song_id':self.song_id,'request_id':'same-request'}
        self.call('/api/command',self.remote.request_key,command)
        duplicate=self.call('/api/command',self.remote.request_key,command)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(len(self.commands),1)

    def test_operator_can_set_volume_key_and_speed(self):
        for action, value in [('volume',73), ('key',-2), ('speed',110)]:
            command={'action':action,'value':value}
            self.assertTrue(self.call('/api/command',self.remote.operator_key,command)['ok'])
            self.assertEqual({k:v for k,v in self.commands[-1].items() if not k.startswith('_')},command)

    def test_guest_cannot_change_volume_key_or_speed(self):
        for action in ('volume','key','speed'):
            with self.assertRaises(urllib.error.HTTPError) as result:
                self.call('/api/command',self.remote.request_key,{'action':action,'value':50})
            self.assertEqual(result.exception.code,403)
        self.assertEqual(self.commands,[])

    def test_operator_and_origin_boundary(self):
        self.assertTrue(self.call('/api/command',self.remote.operator_key,{'action':'stop'})['ok'])
        with self.assertRaises(urllib.error.HTTPError) as result:
            self.call('/api/command',self.remote.operator_key,{'action':'stop'},'http://another-host')
        self.assertEqual(result.exception.code,403)

if __name__=='__main__':
    unittest.main()
