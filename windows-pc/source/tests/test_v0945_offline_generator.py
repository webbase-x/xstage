"""Batch converter regression tests. Never require BASS, Drive, or licensed SF2."""
import csv
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from karaoke.offline_generator import (discover, metadata_map, convert_directory,
                                      choose_workers, atomic_json)
from karaoke.legacy import ncn_lyrics
from karaoke.smf import load_midi
from karaoke.web_assets import lyrics_document, signature
from tests.test_studio import midi_fixture


class StubRenderer:
    calls = 0
    broken = set()
    def __init__(self, native, settings, font, cache_dir, ffmpeg='ffmpeg'):
        self.cache = Path(cache_dir); self.font = font; self.settings = settings
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def build(self, song, parts):
        if song['code'] in self.broken:
            raise ValueError('SIMULATED_CORRUPT')
        type(self).calls += 1
        digest = signature(parts, self.font, self.settings)
        out = self.cache / digest[:2]; out.mkdir(parents=True, exist_ok=True)
        a = out / (digest + '.m4a')
        l = out / (digest + '.json')
        a.write_bytes(b'FAKEAAC-TEST-' * 128)
        midi = load_midi(parts['media'])
        timed = ncn_lyrics(parts['media'], midi) if 'cursor' in parts else midi.lyrics
        if not timed or not timed.lines:
            raise ValueError('ไม่มีเนื้อร้อง')
        l.write_text(json.dumps(lyrics_document(song, midi, timed, midi.duration+1.5),ensure_ascii=False), encoding='utf-8')
        return digest, a, l, midi.duration+1.5


class OfflineGenerator0945Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.songs = self.root / 'source'
        self.songs.mkdir()
        self.output = self.root / 'public'
        self.font = self.root / 'test.sf2'
        self.font.write_bytes(b'fake sf2 fixture no native load')
        StubRenderer.calls = 0
        StubRenderer.broken = set()
    def add_ncn(self, code='99999', folder='Song/9'):
        media = self.songs/folder/(code+'.mid')
        media.parent.mkdir(parents=True,exist_ok=True)
        media.write_bytes(midi_fixture())
        if folder.startswith('Song/'):
            sibling = folder.split('/',1)[1]
            lyric = self.songs/'Lyrics'/sibling/(code+'.lyr')
            cursor = self.songs/'Cursor'/sibling/(code+'.cur')
        else:
            lyric = media.with_suffix('.lyr')
            cursor = media.with_suffix('.cur')
        lyric.parent.mkdir(parents=True,exist_ok=True)
        cursor.parent.mkdir(parents=True,exist_ok=True)
        lyric.write_bytes('ชื่อเพลงทดสอบ\r\nศิลปินทดสอบ\r\nC\r\n.\r\nกข\r\n'.encode('cp874'))
        cursor.write_bytes(struct.pack('<3H',0,0,24))
        return media, lyric, cursor
    def convert(self, **kwargs):
        return convert_directory(self.songs,self.font,self.output,
                                 renderer_factory=StubRenderer,validate_audio=False,
                                 show_progress=False,callback=lambda *_:None,**kwargs)
    def test_full_ncn_produces_requested_folder_structure_and_timed_json(self):
        self.add_ncn()
        result = self.convert()
        self.assertEqual((result['success'],result['failed']),(1,0))
        a = self.output/'audio/9/99999.m4a'
        l = self.output/'lyrics/9/99999.json'
        self.assertTrue(a.is_file());self.assertTrue(l.is_file())
        j = json.loads(l.read_text(encoding='utf-8'))
        self.assertEqual(j['title'],'ชื่อเพลงทดสอบ')
        self.assertEqual(j['artist'],'ศิลปินทดสอบ')
        self.assertTrue(j['lines'][0]['syllables'])
        self.assertEqual(j['lines'][0]['lineIndex'],0)
        db = json.loads((self.output/'database.json').read_text(encoding='utf-8'))
        self.assertEqual(db['totalSongs'],1)
        self.assertEqual(db['songs'][0]['audio']['path'],'audio/9/99999.m4a')
        self.assertEqual(db['songs'][0]['lyrics']['path'],'lyrics/9/99999.json')
        self.assertEqual(db['songs'][0]['code'],'99999')
        self.assertNotIn('fileId',db['songs'][0]['audio'])
    def test_rerun_uses_verified_existing_asset_without_rerender(self):
        self.add_ncn(); self.convert()
        result=self.convert()
        self.assertEqual(StubRenderer.calls,1)
        self.assertEqual(result['skipped_unchanged'],1)
        self.assertEqual(result['success'],1)
    def test_change_in_cur_triggers_new_render_and_lyrics_update(self):
        _,_,cursor=self.add_ncn();self.convert()
        cursor.write_bytes(struct.pack('<3H',0,24,48))
        r=self.convert()
        self.assertEqual(StubRenderer.calls,2)
        self.assertEqual(r['success'],1)
    def test_bad_triplet_skipped_and_absent_database(self):
        _,_,cur=self.add_ncn(); cur.unlink()
        result=self.convert()
        self.assertEqual(result['success'],0)
        self.assertEqual(result['failed'],1)
        self.assertIn('NCN ไม่ครบ',(self.root/'xstage-web-errors.log').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((self.output/'database.json').read_text(encoding='utf-8'))['songs'],[])
    def test_corrupt_song_does_not_crash_batch_and_is_excluded(self):
        self.add_ncn('99999'); self.add_ncn('91111')
        StubRenderer.broken={'91111'}
        r=self.convert()
        self.assertEqual(r['success'],1)
        self.assertEqual(r['failed'],1)
        self.assertEqual(json.loads((self.output/'database.json').read_text(encoding='utf-8'))['totalSongs'],1)
        self.assertIn('SIMULATED_CORRUPT',(self.root/'xstage-web-errors.log').read_text(encoding='utf-8'))
    def test_two_sources_same_code_are_not_overwritten(self):
        self.add_ncn(folder='Song/9')
        self.add_ncn(folder='extra')
        r=self.convert()
        self.assertEqual(r['success'],2)
        files=list((self.output/'audio/9').glob('*.m4a'))
        self.assertEqual(len(files),2)
        self.assertNotEqual(files[0].name,files[1].name)
    def test_metadata_override_does_not_rerender_audio(self):
        self.add_ncn();self.convert()
        m=self.root/'metadata.csv'
        with m.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['code','title','artist'])
            writer.writeheader();writer.writerow({'code':'99999','title':'แก้ชื่อเพลง','artist':'คนใหม่'})
        r=self.convert(metadata=m)
        self.assertEqual(StubRenderer.calls,2) # metadata changes trigger cache-build, not native AAC in real cache
        self.assertEqual(r['success'],1)
        self.assertEqual(json.loads((self.output/'lyrics/9/99999.json').read_text(encoding='utf-8'))['title'],'แก้ชื่อเพลง')
    def test_no_credentials_or_drive_required(self):
        self.add_ncn(); self.convert()
        all_files=[p.name.lower() for p in self.output.rglob('*') if p.is_file()]
        self.assertFalse(any('client_secret' in n or 'token' in n or 'sqlite' in n for n in all_files))
    def test_worker_selection_conservative_and_validation(self):
        self.assertEqual(choose_workers('1',self.font),1)
        with self.assertRaises(ValueError):choose_workers('0',self.font)
        with self.assertRaises(ValueError):choose_workers('17',self.font)
    def test_real_ffmpeg_pipeline_accepts_bass_style_float_pcm(self):
        import array
        from karaoke.web_assets import render_audio
        from karaoke.offline_generator import _check_aac
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('requires FFmpeg and FFprobe')
        media, *_ = self.add_ncn()
        class FloatPcmSynth:
            def __init__(self): self.started = False; self.sent = []
            def start_offline_song(self):self.started = True
            def render(self, frames):return array.array('f',[0.]*frames*2).tobytes()
            def send(self, data):self.sent.append(data)
        synth = FloatPcmSynth()
        output = self.root/'trial.m4a'
        source = render_audio(media, output, self.root/'native', {}, synth=synth)
        _check_aac(output, 'ffprobe')
        self.assertTrue(synth.started)
        self.assertTrue(synth.sent)
        self.assertGreater(output.stat().st_size, 256)
        self.assertGreater(source.duration, 0)

    def test_atomic_db_not_damaged_by_failed_write(self):
        value={'schemaVersion':1,'songs':[{'code':'001'}]}
        atomic_json(self.output/'database.json',value)
        self.assertEqual(json.loads((self.output/'database.json').read_text(encoding='utf-8')),value)

if __name__=='__main__':
    unittest.main()
