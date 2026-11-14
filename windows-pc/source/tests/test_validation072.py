import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from karaoke.library import parse_json, read_json, JsonRecoveryError, SongQueue, SongLibrary, QueueItem
from karaoke.json_recovery import restore_json
from test_studio import midi_fixture

class Json072Tests(unittest.TestCase):
    def test_duplicate_keys_at_any_depth_are_rejected(self):
        for payload in ('{"volume":1,"volume":2}','{"settings":{"eq":1,"eq":2}}','[{"song_id":1,"song_id":2}]'):
            with self.subTest(payload=payload),self.assertRaises(ValueError):parse_json(payload)
    def test_repeated_keys_in_different_objects_remain_valid(self):
        self.assertEqual(parse_json('[{"song_id":1},{"song_id":2}]'),[{'song_id':1},{'song_id':2}])
    def test_duplicate_settings_preserves_original_and_exact_backup(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';raw=b'{"volume":1,"volume":2}';p.write_bytes(raw)
            with self.assertRaises(JsonRecoveryError):read_json(p,{})
            self.assertEqual(p.read_bytes(),raw);self.assertEqual(next(Path(d).glob('*.bak')).read_bytes(),raw)
    def test_duplicate_recovery_candidate_does_not_replace_target(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'settings.json';p.write_bytes(b'{}');source=Path(d)/'saved.json';source.write_bytes(b'{"volume":1,"volume":2}')
            with self.assertRaises(ValueError):restore_json(p,source)
            self.assertEqual(p.read_bytes(),b'{}');self.assertFalse(list(Path(d).glob('*.bak')))

class Playlist072Tests(unittest.TestCase):
    def test_late_invalid_entry_does_not_modify_actual_index_or_queue(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);song=root/'valid.mid';song.write_bytes(midi_fixture());library=SongLibrary(root/'songs.sqlite3');q=SongQueue(root/'queue.json');q.add(QueueItem(99));before=q.path.read_bytes()
            source=root/'playlist.json';source.write_text(json.dumps({'format':'xstage.playlist','version':1,'tracks':[{'path':str(song)},{'path':'bad.mid','speed':'invalid'}]}))
            with self.assertRaises(ValueError):q.import_file(source,library)
            self.assertEqual(library.count(),0);self.assertEqual(q.items,[QueueItem(99)]);self.assertEqual(q.path.read_bytes(),before)
    def test_invalid_paths_rejected_before_library_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);q=SongQueue(root/'queue.json');library=Mock();source=root/'playlist.json'
            for path in ('','   ','a\x00.mid'):
                source.write_text(json.dumps({'format':'xstage.playlist','tracks':[{'path':'valid.mid'},{'path':path}]}))
                with self.subTest(path=path),self.assertRaises(ValueError):q.import_file(source,library)
            library.add_files.assert_not_called();self.assertEqual(q.items,[])
    def test_unsupported_version_rejected_before_library_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);q=SongQueue(root/'queue.json');library=Mock();source=root/'playlist.json'
            for version in (2,True,'1'):
                source.write_text(json.dumps({'format':'xstage.playlist','version':version,'tracks':[{'path':'valid.mid'}]}))
                with self.subTest(version=version),self.assertRaises(ValueError):q.import_file(source,library)
            library.add_files.assert_not_called()
    def test_duplicate_keys_and_nan_rejected_before_library_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);q=SongQueue(root/'queue.json');library=Mock();source=root/'playlist.json'
            for payload in ('{"format":"xstage.playlist","tracks":[{"path":"a.mid","path":"b.mid"}]}','{"format":"xstage.playlist","tracks":[{"path":"a.mid","key":NaN}]}'):
                source.write_text(payload)
                with self.assertRaises(ValueError):q.import_file(source,library)
            library.add_files.assert_not_called()
    def test_legacy_playlist_and_missing_files_remain_supported(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);song=root/'valid.mid';song.write_bytes(midi_fixture());library=SongLibrary(root/'songs.sqlite3');q=SongQueue(root/'queue.json');source=root/'playlist.json'
            source.write_text(json.dumps({'format':'newKaraoke.playlist','tracks':[{'path':str(song),'speed':999},{'path':str(root/'missing.mid')}]}))
            self.assertEqual(q.import_file(source,library),(1,1));self.assertEqual(library.count(),1);self.assertEqual(q.items[0].speed,150)

class BuildPython072Tests(unittest.TestCase):
    def run_ps(self,script):
        root=Path(__file__).resolve().parents[1]
        def quote(value):return "'"+str(value).replace("'","''")+"'"
        prefix="$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; $OutputEncoding=[Console]::OutputEncoding; . "+quote(root/'tools/Build-Python.ps1')+"; "
        process=subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',prefix+script],cwd=root,capture_output=True,encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(process.returncode,0,process.stdout+'\n'+process.stderr)
        return process.stdout.strip()
    def test_current_build_python_passes_and_missing_path_fails(self):
        exe="'"+str(sys.executable).replace("'","''")+"'"
        out=self.run_ps("@{valid=(Test-XStageBuildPython "+exe+");missing=(Test-XStageBuildPython 'D:/nonexistent-build-python.exe');invalid=(Test-XStageBuildPython ([string][char]0))} | ConvertTo-Json -Compress")
        result=json.loads(out);self.assertTrue(result['valid']);self.assertFalse(result['missing']);self.assertFalse(result['invalid'])
    def test_selection_skips_wrong_minor_version(self):
        out=self.run_ps("function Test-XStageBuildPython {param([string]$Executable) return $Executable -eq 'python313'}; Select-XStageBuildPython -Candidates @('python314','missing','python313')")
        self.assertEqual(out,'python313')
    def test_no_compatible_python_does_not_launch_installer(self):
        out=self.run_ps("$script:launched=$false; function Start-Process {$script:launched=$true;throw 'unexpected installer'}; function Test-XStageBuildPython {return $false}; try {Select-XStageBuildPython -Candidates @('python314');exit 1} catch {if($script:launched){exit 2};Write-Output 'rejected-without-install'}")
        self.assertEqual(out,'rejected-without-install')
    def test_default_discovery_finds_actual_compatible_python(self):
        out=self.run_ps("$found=Get-XStageBuildPython; @{ok=(Test-XStageBuildPython $found)} | ConvertTo-Json -Compress")
        self.assertTrue(json.loads(out)['ok'])
    def test_build_source_is_valid_powershell_syntax(self):
        root=Path(__file__).resolve().parents[1];path="'"+str(root/'Build-Source.ps1').replace("'","''")+"'"
        out=self.run_ps("$tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile("+path+",[ref]$tokens,[ref]$errors)|Out-Null;if($errors.Count){$errors|Out-String|Write-Output;exit 1};Write-Output 'syntax-ok'")
        self.assertEqual(out,'syntax-ok')
