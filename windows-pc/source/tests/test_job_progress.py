import csv
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from karaoke.jobs import JobReporter,percent,timing
from karaoke.index_plan import SongPlan
from karaoke.library import SongLibrary
from karaoke.lister import build_list
from karaoke.legacy import dbf_count,dbf_records
from karaoke.ui import KaraokeApp
from karaoke.job_dialog import JobWindow,duration
from test_studio import midi_fixture,dbf_fixture

class JobProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=SongLibrary(self.root/'app-state/songs.db')
    def tearDown(self):self.temp.cleanup()
    def midi(self,name='songs/1.mid'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(midi_fixture());return path
    def test_count_precedes_processing_and_overlap_counted_once(self):
        self.midi();self.midi('songs/sub/2.mid');events=[]
        (self.root/'songs/sub/skip.xmk').write_bytes(b'unsupported')
        roots=[{'path':str(self.root/'songs'),'type':'ทุกประเภท'}, {'path':str(self.root/'songs/sub'),'type':'ทุกประเภท'}]
        result=build_list(self.db,roots,events=events.append)
        self.assertEqual(result[0],2);self.assertEqual(result[1],1)
        self.assertEqual(sum(e.get('type')=='notice' for e in events),1)
        goal=next(i for i,e in enumerate(events) if e.get('type')=='phase' and e.get('phase')=='ตรวจเดิม / ตรวจซ้ำก่อนนำเข้า')
        self.assertEqual(events[goal]['total'],2)
        items=[i for i,e in enumerate(events) if e.get('type')=='item']
        self.assertEqual(len(items),2);self.assertGreater(min(items),goal)
    def test_fixed_snapshot_handles_disappeared_file_and_later_addition(self):
        path=self.midi();events=[]
        with SongPlan() as plan:
            plan.folder(path.parent);self.assertEqual(plan.count(),1)
            path.unlink();self.midi('songs/new.mid')
            result=plan.run(self.db,events=events.append)
        self.assertEqual(result[0],0)
        item=next(e for e in events if e.get('type')=='item')
        self.assertFalse(item['ok']);self.assertEqual(events[-1]['done'],1);self.assertEqual(events[-1]['total'],1)
    def test_item_is_reported_after_commit_with_preserved_metadata(self):
        path=self.midi();sid=self.db.add_files([path])[0];self.db.edit(sid,'CUSTOM','ชื่อแก้ไข','ผู้ร้อง')
        recorded=[]
        def inspect_done(item):
            self.assertEqual(self.db.get(sid)['title'],item['title'])
            recorded.append(item)
        self.db.add_files([path],inspected=inspect_done)
        self.assertEqual(recorded[0]['title'],'ชื่อแก้ไข');self.assertEqual(recorded[0]['code'],'CUSTOM')
    def test_empty_job_and_percent_boundaries(self):
        self.assertIsNone(percent({'total':None,'done':5}))
        self.assertEqual(percent({'total':0,'done':0}),0)
        self.assertEqual(percent({'total':0,'done':0,'finished':True}),100)
        self.assertEqual(percent({'total':0,'done':0,'finished':True,'cancelled':True}),0)
        self.assertEqual(percent({'total':4,'done':1}),25)
        self.assertEqual(percent({'total':4,'done':5}),100)
        self.assertEqual(timing({'done':50,'total':100,'phase_elapsed':10}),(5,10))
        self.assertEqual(timing({'done':0,'total':100,'phase_elapsed':0}),(0,None))
    def test_full_csv_and_throttled_packets_do_not_drop_items(self):
        messages=queue.Queue();report=JobReporter(messages,self.root)
        report.event(dict(type='phase',phase='อ่านข้อมูลเพลง',total=350,target=350))
        for i in range(350):report.event(dict(type='item',ok=True,path=str(i),code=str(i),title='เพลง'))
        report.finish()
        with report.log_path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
        self.assertEqual(len(rows),351)
        packets=[]
        while not messages.empty():packets.append(messages.get()[1])
        self.assertGreaterEqual(sum(len(p['rows']) for p in packets),300)
        self.assertLessEqual(sum(len(p['rows']) for p in packets),350)
        self.assertLess(len(packets),20)
        self.assertEqual(packets[-1]['state']['processed'],350)
        self.assertEqual(percent(packets[-1]['state']),100)
    def test_notice_does_not_inflate_song_goal_and_csv_is_safe(self):
        report=JobReporter(queue.Queue(),self.root)
        report.event(dict(type='notice',ok=False,path='unsupported.xmk',title='=FORMULA'))
        report.event(dict(type='phase',phase='อ่านข้อมูลเพลง',total=1,target=1))
        report.event(dict(type='item',ok=True,path='1.mid',title='+FORMULA'))
        report.finish()
        self.assertEqual(report.state['processed'],1);self.assertEqual(report.state['unsupported'],1)
        with report.log_path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.reader(stream))
        self.assertEqual(rows[1][4],"'=FORMULA");self.assertEqual(rows[2][4],"'+FORMULA")
    def test_cancelled_job_preserves_partial_fraction(self):
        report=JobReporter(queue.Queue(),self.root)
        report.event(dict(type='phase',phase='อ่านข้อมูลเพลง',total=10,target=10))
        report.event(dict(type='item',ok=True,path='1.mid'));report.finish(cancelled=True)
        self.assertTrue(report.state['cancelled']);self.assertEqual(percent(report.state),10)
    def test_dbf_count_uses_active_rows(self):
        path=self.root/'SONG.DBF';path.write_bytes(dbf_fixture())
        self.assertEqual(dbf_count(path),len(list(dbf_records(path))))
    @unittest.skip('v0.9.41 retired behavior: automatic copy/hide/quarantine or old cleanup; replaced by tests/test_v0941_*')
    def test_index_worker_reports_goal_rows_duplicates_and_final_state(self):
        self.midi();self.midi('songs/2.mid');messages=queue.Queue();report=JobReporter(messages,self.root)
        app=SimpleNamespace(scanning=False,cancel_scan=threading.Event(),status_var=Mock(),
            song_queue=SimpleNamespace(items=[]),current_song=None,library=self.db,messages=messages,
            begin_job=lambda:report,job_event=report.event,write_import_report=Mock())
        operation=lambda:build_list(self.db,[{'path':str(self.root/'songs'),'type':'ทุกประเภท'}],events=report.event,cancelled=app.cancel_scan)
        KaraokeApp.start_index_job(app,operation)
        packets=[]
        while True:
            kind,data=messages.get(timeout=10)
            if kind=='job_progress':packets.append(data)
            if kind=='scan_error':self.fail(data)
            if kind=='scan_done':break
        self.assertEqual(self.db.count(),1)
        self.assertTrue(packets[-1]['state']['finished'])
        self.assertEqual(packets[-1]['state']['target'],2)
        self.assertEqual(packets[-1]['state']['processed'],2)
        self.assertEqual(packets[-1]['state']['duplicates'],1)
        self.assertEqual(sum(len(p['rows']) for p in packets),2)
    def test_window_update_bounds_recent_rows_and_displays_fraction(self):
        from unittest.mock import MagicMock
        ui=object.__new__(JobWindow);ui.state={};ui.cancel_requested=False
        for name in ['phase','percentage','bar','cancel','file','report','cards','current','workspace']:setattr(ui,name,Mock())
        ui.phase_count=Mock();ui.metrics={key:Mock() for key in ['target','processed','accepted','rejected','duplicates']}
        ui.tree=MagicMock();ui.tree.get_children.return_value=tuple(str(i) for i in range(400))
        packet=dict(state=dict(phase='อ่าน',total=100,done=25,target=100,processed=25,accepted=25),rows=[])
        ui.update(packet)
        ui.tree.delete.assert_called_once_with(*tuple(str(i) for i in range(100)))
        ui.percentage.configure.assert_called_with(text='25.0%',fg='#73dadd')
        self.assertEqual(duration(65),'01:05');self.assertEqual(duration(None),'กำลังคำนวณ')

    def test_summary_includes_target_counts_time_and_full_report(self):
        reporter=JobReporter(queue.Queue(),self.root)
        reporter.event(dict(type='phase',phase='อ่าน',total=1,target=1))
        reporter.event(dict(type='item',ok=True,path='1.mid',title='เพลง'))
        app=SimpleNamespace(library=self.db,cancel_scan=threading.Event(),job_reporter=reporter)
        KaraokeApp.write_import_report(app,(1,0,[]));reporter.finish()
        text=(self.db.path.parent/'import-report.txt').read_text(encoding='utf-8')
        self.assertIn('เป้าหมาย 1',text);self.assertIn('ตรวจแล้ว 1',text)
        self.assertIn(str(reporter.log_path),text);self.assertIn('ใช้เวลา:',text)

    def test_catalog_goal_and_processed_rows_match_active_record_count(self):
        from karaoke.legacy import import_catalog
        (self.root/'Data').mkdir();file=self.root/'Data/SONG.DBF';file.write_bytes(dbf_fixture())
        reporter=JobReporter(queue.Queue(),self.root)
        import_catalog(self.root,self.db,errors=[],events=reporter.event)
        reporter.finish()
        self.assertEqual(reporter.state['target'],dbf_count(file))
        self.assertEqual(reporter.state['processed'],dbf_count(file))

    def test_worker_failure_emits_terminal_progress_and_error(self):
        messages=queue.Queue();reporter=JobReporter(messages,self.root)
        app=SimpleNamespace(scanning=False,cancel_scan=threading.Event(),status_var=Mock(),
            song_queue=SimpleNamespace(items=[]),current_song=None,library=self.db,messages=messages,
            begin_job=lambda:reporter,job_event=reporter.event,write_import_report=Mock())
        def broken():raise OSError('fixture failure')
        KaraokeApp.start_index_job(app,broken)
        state=None
        while True:
            kind,data=messages.get(timeout=10)
            if kind=='job_progress':state=data['state']
            if kind=='scan_error':break
        self.assertTrue(state['finished']);self.assertEqual(state['error'],'fixture failure')
        app.write_import_report.assert_called_once()
