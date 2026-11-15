"""Safe reconciliation of music uploaded by earlier X-Stage releases.

No credentials or real Drive connection required. Only catalog pointers are
published after audio and lyrics are verified, and already-uploaded media is
never replaced with guessed file IDs.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from karaoke.library import SongLibrary
from karaoke.web_assets import file_hash, safe_stem, signature
from karaoke.web_drive import sync_web_assets
from tests.test_studio import midi_fixture
from tests.test_v0944_web_sync import FakeWebDrive, StubRenderer

class ProofRenderer(StubRenderer):
    def build(self, song, parts, cancel=None):
        sig, audio, lyrics, duration = super().build(song, parts, cancel=cancel)
        data=json.loads(lyrics.read_text(encoding='utf-8'))
        data['lines']=[{'startMs':0,'endMs':1000,'text':'เพลงทดสอบ'}]
        lyrics.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        proof = audio.with_name(audio.stem+'.proof.json')
        proof.write_text(json.dumps({
            'fingerprint':sig,
            'audio_sha256':file_hash(audio),
            'lyrics_sha256':file_hash(lyrics),
        }),encoding='utf-8')
        return sig, audio, lyrics, duration

class LegacyRecoveryR8Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.music=self.base/'Songs';self.music.mkdir()
        self.source=self.music/'99801.mid';self.source.write_bytes(midi_fixture())
        self.library=SongLibrary(self.base/'Data'/'songs.sqlite3')
        self.library.add_files([self.source])
        self.font=self.base/'sound.sf2';self.font.write_bytes(b'fixture')
        self.drive=FakeWebDrive()
        self.cache=self.base/'WebAssets'
        ProofRenderer.builds=0
    def sync(self):
        return sync_web_assets(self.drive,self.library.path,[self.music],
            self.base/'native',{},self.font,self.cache,
            renderer_factory=ProofRenderer, first_batch_size=1)
    def test_uploaded_pair_without_pointer_or_journal_rebuilds_db_without_upload(self):
        # Prior program successfully uploaded media pair then lost DB/pointer.
        self.drive.fail_suffix='current.json'
        with self.assertRaises(Exception):self.sync()
        self.drive.fail_suffix=None
        previous_uploads=list(self.drive.uploads)
        assert any(name.endswith('.m4a') for name in previous_uploads)
        import shutil
        shutil.rmtree(self.cache/'sync')
        before=ProofRenderer.builds
        result=self.sync()
        self.assertEqual(ProofRenderer.builds,before,'no repeat conversion for verified local proof')
        self.assertEqual(result['reused'],1)
        self.assertEqual([x for x in self.drive.uploads[len(previous_uploads):] if x.endswith('.m4a')],[])
        root=self.drive.children('root','XStageWeb')[0]['id']
        pointer=self.drive.children(root,'current.json')[0]
        document=json.loads(self.drive.download(pointer['id']))
        catalog=json.loads(self.drive.download(document['catalogFileId']))
        self.assertEqual(len(catalog['songs']),1)
        self.assertTrue(catalog['songs'][0]['audio']['fileId'])
        self.assertTrue(catalog['songs'][0]['lyrics']['fileId'])
    def test_tampered_local_proof_must_never_skip_media_verification(self):
        self.drive.fail_suffix='current.json'
        with self.assertRaises(Exception):self.sync()
        self.drive.fail_suffix=None
        import shutil
        shutil.rmtree(self.cache/'sync')
        proof=next(self.cache.rglob('*.proof.json'))
        data=json.loads(proof.read_text())
        data['audio_sha256']='0'*64
        proof.write_text(json.dumps(data))
        # Existing renderer can re-render (or reuse its own cached material),
        # but the extra fast path must not accept forged proof.
        result=self.sync()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['uploaded_files'],0)
    def test_existing_legacy_database_is_upgraded_without_media_upload(self):
        original=self.sync()
        root=self.drive.children('root','XStageWeb')[0]['id']
        old_pointer=self.drive.children(root,'current.json')[0]
        manifest=json.loads(self.drive.download(old_pointer['id']))
        old_database=self.drive.download(manifest['catalogFileId'])
        self.drive.create(root,'database.json',old_database)
        self.drive.parent.pop(old_pointer['id'])
        count_audio=len([x for x in self.drive.uploads if x.endswith('.m4a')])
        result=self.sync()
        self.assertEqual(result['total'],1)
        self.assertEqual(result['reused'],1)
        self.assertEqual(count_audio,len([x for x in self.drive.uploads if x.endswith('.m4a')]))
        pointer=self.drive.children(root,'current.json')
        self.assertEqual(len(pointer),1)

if __name__=='__main__':unittest.main()
