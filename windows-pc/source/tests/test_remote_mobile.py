from unittest.mock import patch
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
from karaoke.remote import RemoteServer
from karaoke.remote_requests import RequestBook
from karaoke.remote_ui import enrich_snapshot, validate_remote_command, stage_invite, make_invite, initial_policy
from karaoke.library import SongQueue, QueueItem
from karaoke.lyrics import Lyrics, LyricLine

class RemoteMobileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        file=self.root/'song.mid';file.write_bytes(b'fixture')
        self.song=dict(id=1,code='01',title='เพลงทดสอบ',artist='นักร้อง',kind='midi',format='MIDI',playable=True,path=str(file))
        self.app=NS(library=NS(get=lambda i:self.song if i==1 else None,search=lambda q,limit:[self.song]),song_queue=SongQueue(self.root/'queue.json'),current_item=None,current_song=None,engine=None,refresh_queue=Mock(),remote_requests=RequestBook(),settings={})
        self.calls=0
        def snapshot():
            value=dict(title='',queue=[])
            enrich_snapshot(self.app,value)
            return value
        def dispatch(command):
            self.calls+=1
            validate_remote_command(self.app,command)
            if command['action'] in ('queue','approve','reject','request_key','cancel_request'):
                return self.app.remote_requests.command(self.app,command,self.remote.policy)
            return {'ok':True}
        self.remote=RemoteServer(self.app.library,dispatch,snapshot,host='127.0.0.1',port=0)
        self.app.remote=self.remote;self.remote.start()
    def tearDown(self):
        self.remote.close();self.temp.cleanup()
    def call(self,path,body=None,token='',origin=None):
        payload=json.dumps(body).encode() if body is not None else b''
        headers={'Authorization':'Bearer '+token,'Host':f'127.0.0.1:{self.remote.port}','Content-Length':str(len(payload))}
        if origin:headers['Origin']=origin
        wire=(('POST' if body is not None else 'GET')+' '+path+' HTTP/1.0\r\n'+'\r\n'.join(k+': '+v for k,v in headers.items())+'\r\n\r\n').encode()+payload
        class Connection:
            def __init__(self):self.input=io.BytesIO(wire);self.output=bytearray()
            def makefile(self,*_):return self.input
            def sendall(self,data):self.output.extend(data)
        connection=Connection();self.remote.server.RequestHandlerClass(connection,('127.0.0.1',12345),self.remote.server)
        header,result=bytes(connection.output).split(b'\r\n\r\n',1)
        return int(header.split(b' ')[1]),json.loads(result)
    def login(self,operator=False):
        if operator:self.remote.configure(operator=True)
        code=self.remote.operator_key if operator else self.remote.request_key
        status,data=self.call('/api/login',{'code':code});self.assertEqual(status,200)
        return data['token']
    def request(self,token,rid='r1',**extra):
        return self.call('/api/command',dict(action='queue',song_id=1,singer='หนึ่ง',request_id=rid,**extra),token)
    def state(self,token):return self.call('/api/state',token=token)[1]
    def test_unexpected_get_failure_is_logged_without_authentication_data(self):
        token=self.login()
        self.remote.snapshot=Mock(side_effect=RuntimeError('snapshot fixture'))
        with self.assertLogs(level='ERROR') as captured:
            status,body=self.call('/api/state',token=token)
        self.assertEqual(status,503)
        log='\n'.join(captured.output)
        self.assertIn('REMOTE_GET failed',log)
        self.assertIn('snapshot fixture',log)
        self.assertNotIn(token,log)
        self.assertNotIn('snapshot fixture',str(body))

    def test_unexpected_post_failure_is_logged_without_request_body(self):
        token=self.login()
        self.remote.dispatch=Mock(side_effect=RuntimeError('dispatch fixture'))
        with self.assertLogs(level='ERROR') as captured:
            status,body=self.call('/api/command',{'action':'queue','song_id':1,'singer':'private singer fixture'},token)
        self.assertEqual(status,503)
        log='\n'.join(captured.output)
        self.assertIn('REMOTE_POST failed',log)
        self.assertIn('dispatch fixture',log)
        self.assertNotIn(token,log)
        self.assertNotIn('private singer fixture',log)
        self.assertNotIn('dispatch fixture',str(body))

    def test_six_digit_distinct_codes_and_default_controls_off(self):
        self.assertRegex(self.remote.request_key,r'^\d{6}$');self.assertRegex(self.remote.operator_key,r'^\d{6}$')
        self.assertNotEqual(self.remote.request_key,self.remote.operator_key)
        self.assertFalse(self.remote.policy['operator'])
        self.assertEqual(self.call('/api/login',{'code':self.remote.operator_key})[0],401)
    def test_pairing_pin_is_not_an_api_token(self):
        self.assertEqual(self.call('/api/state',token=self.remote.request_key)[0],401)
    def test_rate_limit_wrong_codes(self):
        wrong=next(f'{i:06d}' for i in range(10) if f'{i:06d}' not in (self.remote.request_key,self.remote.operator_key))
        for _ in range(5):self.assertEqual(self.call('/api/login',{'code':wrong})[0],401)
        self.assertEqual(self.call('/api/login',{'code':self.remote.request_key})[0],429)
    def test_auto_fifo_and_occurrence_keys(self):
        token=self.login();self.request(token,'a',key=2);self.request(token,'b',key=-3)
        self.assertEqual([(i.request_id,i.key) for i in self.app.song_queue.items],[('a',2),('b',-3)])
        self.assertEqual([r['position'] for r in self.state(token)['mine']],[1,2])
        reloaded=SongQueue(self.root/'queue.json');self.assertEqual(reloaded.items[1].request_id,'b')
    def test_duplicate_after_response_loss_has_one_occurrence(self):
        token=self.login();self.request(token,'same');self.remote.recent.clear()
        status,result=self.request(token,'same')
        self.assertEqual(status,200);self.assertTrue(result['duplicate']);self.assertEqual(len(self.app.song_queue.items),1)
    def test_manual_approval_and_mode_change_preserve_waiting(self):
        guest=self.login();operator=self.login(True);self.remote.configure(approval=True)
        self.request(guest,'a');self.assertEqual(self.app.song_queue.items,[])
        self.remote.configure(approval=False);self.request(guest,'b')
        self.assertEqual([i.request_id for i in self.app.song_queue.items],['b'])
        self.assertEqual(len(self.state(operator)['pending']),1)
        self.assertEqual(self.call('/api/command',dict(action='approve',request_id='a'),operator)[0],200)
        self.assertEqual([i.request_id for i in self.app.song_queue.items],['b','a'])
    def test_ownership_cannot_be_spoofed(self):
        one=self.login();two=self.login();self.request(one)
        self.assertEqual(self.state(two)['mine'],[])
        result=self.call('/api/command',dict(action='cancel_request',request_id='r1',_owner='local',_role='operator'),two)
        self.assertEqual(result[0],400)
        self.assertEqual(len(self.app.song_queue.items),1)
        self.assertNotIn('owner',self.state(one)['mine'][0])
    def test_guest_cannot_approve_or_control(self):
        guest=self.login()
        for action in ('approve','reject','stop','volume','key','next'):
            self.assertEqual(self.call('/api/command',dict(action=action,request_id='a',value=2),guest)[0],403)
    def test_pause_requests_limit_and_edit_permission(self):
        guest=self.login();self.remote.configure(limit=1);self.request(guest)
        self.assertEqual(self.request(guest,'two')[0],400)
        self.remote.configure(allow_edit=False)
        self.assertEqual(self.call('/api/command',dict(action='cancel_request',request_id='r1'),guest)[0],400)
        self.remote.configure(allow_edit=True)
        self.assertEqual(self.call('/api/command',dict(action='cancel_request',request_id='r1'),guest)[0],200)
        self.remote.configure(accepting=False)
        self.assertEqual(self.request(guest,'three')[0],400)
    def test_edit_own_key_and_cancel_exact_occurrence(self):
        guest=self.login();self.request(guest,'a');self.request(guest,'b')
        self.call('/api/command',dict(action='request_key',request_id='b',key=-4),guest)
        self.assertEqual([i.key for i in self.app.song_queue.items],[0,-4])
        self.call('/api/command',dict(action='cancel_request',request_id='a'),guest)
        self.assertEqual([i.request_id for i in self.app.song_queue.items],['b'])
    def test_playing_item_is_no_longer_editable(self):
        guest=self.login();self.request(guest)
        self.app.current_item=self.app.song_queue.pop()
        self.assertEqual(self.state(guest)['mine'][0]['status'],'playing')
        self.assertEqual(self.call('/api/command',dict(action='cancel_request',request_id='r1'),guest)[0],400)
        self.app.current_item=None
        self.assertEqual(self.state(guest)['mine'][0]['status'],'ended')
    def test_rotation_invalidates_sessions_but_preserves_queue(self):
        guest=self.login();self.request(guest);old=self.remote.request_key
        self.remote.rotate_codes();self.assertNotEqual(old,self.remote.request_key)
        self.assertEqual(self.call('/api/state',token=guest)[0],401);self.assertEqual(len(self.app.song_queue.items),1)
    def test_disable_control_revokes_existing_operator_session(self):
        operator=self.login(True);self.remote.configure(operator=False)
        self.assertEqual(self.call('/api/command',dict(action='stop'),operator)[0],401)
        self.remote.configure(operator=True)
        self.assertEqual(self.call('/api/state',token=operator)[0],401)
    def test_dispatch_rechecks_revocation(self):
        token=self.login(True);s=self.remote.sessions[token]
        command=dict(_session=token,_owner=s['owner'],_role=s['role'],_generation=s['generation'])
        self.remote.configure(operator=False);self.remote.configure(operator=True)
        with self.assertRaises(ValueError):validate_remote_command(self.app,command)
    @patch('karaoke.pcm_player.available',return_value=False)
    def test_non_midi_rejects_key_and_no_private_path(self, _available):
        guest=self.login();self.song['path']=str(self.root/'song.mp3');Path(self.song['path']).touch()
        songs=self.call('/api/songs?q=',token=guest)[1]['songs']
        self.assertFalse(songs[0]['supports_key']);self.assertNotIn('path',songs[0])
        self.assertEqual(self.request(guest,key=2)[0],400)
    def test_lyrics_snapshot_contains_timing_and_offsets(self):
        self.app.current_song=self.song;self.app.engine=NS(position=2.,speed=1.2)
        self.app.lyrics=Lyrics([LyricLine(1,'สวัสดี',[(1,'สวัส'),(2,'ดี')]),LyricLine(5,'ถัดไป')],100)
        self.app.offset_var=NS(get=lambda:150)
        value={'queue':[]};enrich_snapshot(self.app,value)
        self.assertEqual(value['offset_ms'],250);self.assertEqual(value['playback_rate'],1.2)
        self.assertEqual(value['lyric_lines'][0]['words'][1],(2,'ดี'))
    def test_invite_toggle_independent_of_accepting(self):
        invite=make_invite('192.168.1.3',8080,self.remote.request_key,'Stage WiFi');self.app.remote_invite=invite
        self.assertIsNone(stage_invite(self.app));self.app.settings.update(remote_show_stage=True,remote_idle_only=True)
        self.assertIs(stage_invite(self.app),invite);self.remote.configure(accepting=False)
        self.assertIs(stage_invite(self.app),invite);self.app.current_song=self.song
        self.assertIsNone(stage_invite(self.app));self.app.settings['remote_idle_only']=False
        self.assertIs(stage_invite(self.app),invite)
        self.assertNotIn(self.remote.operator_key,invite['url'])
    def test_failed_queue_save_rolls_back_before_retry(self):
        token=self.login()
        original=self.app.song_queue.save
        self.app.song_queue.save=Mock(side_effect=OSError('disk full'))
        self.assertEqual(self.request(token)[0],503)
        self.assertEqual(self.app.song_queue.items,[])
        self.assertEqual(self.app.remote_requests.records,{})
        self.app.song_queue.save=original
        self.assertEqual(self.request(token)[0],200)
        self.assertEqual(len(self.app.song_queue.items),1)
    def test_reject_removes_pending_without_touching_queue(self):
        token=self.login();operator=self.login(True);self.remote.configure(approval=True)
        self.request(token)
        self.assertEqual(self.call('/api/command',dict(action='reject',request_id='r1'),operator)[0],200)
        self.assertEqual(self.state(token)['mine'][0]['status'],'rejected')
        self.assertEqual(self.app.song_queue.items,[])
    def test_close_editing_cannot_change_pending_key(self):
        token=self.login();self.remote.configure(approval=True);self.request(token)
        self.remote.configure(allow_edit=False)
        self.assertEqual(self.call('/api/command',dict(action='request_key',request_id='r1',key=3),token)[0],400)
        self.assertEqual(self.state(token)['mine'][0]['key'],0)
    def test_saved_approval_mode_restored_but_control_starts_off(self):
        policy=initial_policy(dict(remote_approval=True,remote_accepting=False,remote_operator=True,remote_limit=5))
        self.assertTrue(policy['approval']);self.assertFalse(policy['accepting'])
        self.assertFalse(policy['operator']);self.assertEqual(policy['limit'],5)
    def test_saved_limit_invalid_or_out_of_bounds(self):
        self.assertEqual(initial_policy({'remote_limit':'bad'})['limit'],3)
        self.assertEqual(initial_policy({'remote_limit':999})['limit'],20)
    def test_origin_boundary_on_pairing(self):
        self.assertEqual(self.call('/api/login',{'code':self.remote.request_key},origin='http://evil')[0],403)
    def test_same_request_from_other_owner_is_not_cached_success(self):
        one=self.login();two=self.login();self.request(one,'same')
        self.assertEqual(self.request(two,'same')[0],400)

if __name__=='__main__':unittest.main()
