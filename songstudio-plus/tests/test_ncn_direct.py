import tempfile
import unittest
from pathlib import Path
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ncn_direct as direct
import plus_core as core

def fixture(root,header,body="ทดสอบ"):
    root.mkdir(parents=True,exist_ok=True)
    midi=root/"00001.mid"
    track=b"\x00\x90\x3c\x40\x83\x60\x80\x3c\x00\x00\xff\x2f\x00"
    midi.write_bytes(b"MThd"+struct.pack(">IHHH",6,0,1,480)+b"MTrk"+struct.pack(">I",len(track))+track)
    midi.with_suffix(".lyr").write_bytes(("\r\n".join(header+[body])+"\r\n").encode("cp874"))
    midi.with_suffix(".cur").write_bytes(struct.pack("<"+"H"*(len(body)+1),*range(len(body)+1)))
    return midi

class DirectTests(unittest.TestCase):
    def test_classic_and_reordered_labels(self):
        for header in (["ชื่อจริง","ศิลปินจริง","C",""],["Artist: ศิลปินจริง","Key: C","Title: ชื่อจริง"]):
            with self.subTest(header=header),tempfile.TemporaryDirectory() as d:
                root=Path(d)/"ncn";out=Path(d)/"xmid"
                midi=fixture(root,header)
                before={p.name:p.read_bytes() for p in root.iterdir()}
                result=direct.convert_folder(str(root),str(out))
                self.assertEqual(result["converted"],1,result)
                self.assertEqual(direct.convert_folder(str(root),str(out))["skipped"],1)
                self.assertFalse(list(Path(d).rglob("*.sqlite*")))
                self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
                core.read_xfile(out/"00001.xmid",verify_media=True)
    def test_ambiguous_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"ncn";out=Path(d)/"out"
            fixture(root,["ศิลปินจริง","ชื่อจริง","unknown"])
            self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
            self.assertFalse(list(out.glob("*.xmid")))


class DirectHardeningTests(unittest.TestCase):
    def test_scan_cancel_inside_single_directory(self):
        from unittest.mock import Mock, patch
        cancel=Mock()
        cancel.is_set.side_effect=[False, False, True]
        with patch.object(direct.os,"walk",return_value=[("root",[],["a.mid","b.mid"])]):
            mids,index=direct.scan(Path("root"),cancel)
        self.assertEqual(mids,[])
        self.assertFalse(index)

    def test_scan_prunes_junction(self):
        from unittest.mock import patch
        dirs=["normal","junction"]
        with patch.object(direct.os,"walk",return_value=[("root",dirs,[])]), patch.object(Path,"is_symlink",return_value=False), patch.object(Path,"is_junction",lambda p:p.name=="junction",create=True):
            direct.scan(Path("root"),None)
        self.assertEqual(dirs,["normal"])

    def test_bounded_read_rejects_substituted_open_descriptor(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"source.mid"
            other=Path(d)/"other.mid"
            source.write_bytes(b"original")
            other.write_bytes(b"replaced")
            self.assertEqual(direct.bounded_read(source, 32)[0], b"original")
            real_open=Path.open
            def substituted(path, *args, **kwargs):
                return real_open(other if path == source else path, *args, **kwargs)
            with patch.object(Path, "open", substituted):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    direct.bounded_read(source, 32)

    def test_bom_and_thai_labels(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ศิลปิน: คนร้อง","คีย์: C","ชื่อเพลง: ชื่อจริง"])
            lyr=midi.with_suffix(".lyr")
            lyr.write_bytes(lyr.read_bytes().decode("cp874").encode("utf-8-sig"))
            self.assertEqual(direct.convert_folder(str(root),str(out))["converted"],1)

    def test_short_backward_or_sentinel_cur(self):
        for positions in ([0,1],[0,2,1,3,4,5],[0,1,2,65535,4,5],[0,1,2,3,4,65534]):
            with self.subTest(positions=positions),tempfile.TemporaryDirectory() as d:
                root=Path(d)/"in";out=Path(d)/"out"
                midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
                midi.with_suffix(".cur").write_bytes(struct.pack("<"+"H"*len(positions),*positions))
                self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
                self.assertFalse(list(out.glob("*.xmid")))

    def test_code_reservation_stable_cancel_resume_and_add(self):
        import threading
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            for p in list(root.iterdir()):
                p.rename(p.with_stem("legacy-z"))
            cancel=threading.Event()
            def notify(stats,message):
                if stats.get("done")==1:
                    cancel.set()
            self.assertEqual(direct.convert_folder(str(root),str(out),notify,cancel)["converted"],1)
            before=(out/"00001.xmid").read_bytes()
            midi=fixture(root,["เพลงใหม่","ผู้ร้องใหม่","C",""])
            for p in root.glob("00001.*"):
                p.rename(p.with_stem("legacy-a"))
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual((result["converted"],result["skipped"]),(1,1),result)
            self.assertEqual((out/"00001.xmid").read_bytes(),before)
            self.assertTrue((out/"00002.xmid").exists())

    def test_component_change_rejected_before_publish(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            original=direct.reader.ncn_document
            def change(*args,**kwargs):
                result=original(*args,**kwargs)
                midi.with_suffix(".lyr").write_bytes(b"changed")
                return result
            with patch.object(direct.reader,"ncn_document",side_effect=change):
                self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
            self.assertFalse(list(out.glob("*.xmid")))

    def test_split_tree_case_insensitive(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"NCN";out=Path(d)/"out"
            midi=fixture(root/"SoNg"/"A",["ชื่อจริง","ศิลปินจริง","C",""])
            for name,ext in (("LYRICS",".lyr"),("CuRsOr",".cur")):
                folder=root/name/"A";folder.mkdir(parents=True)
                midi.with_suffix(ext).rename(folder/("00001"+ext.upper()))
            self.assertEqual(direct.convert_folder(str(root),str(out))["converted"],1)

    def test_plan_100000_virtual_paths_and_stable_resume(self):
        # Allocation/ledger benchmark, not 100k actual file conversions.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"source";out=Path(d)/"out";out.mkdir()
            mids=[root/("legacy-%06d.mid"%n) for n in range(100000)]
            first=direct.plan_codes(root,out,mids)
            self.assertEqual(len(set(first.values())),100000)
            self.assertIn("a00001",first.values())
            second=direct.plan_codes(root,out,[root/"earlier.mid"]+mids)
            self.assertEqual({m:second[m] for m in mids},first)

    def test_non_overwrite_and_nested_path(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out";out.mkdir()
            fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            existing=out/"00001.xmid";existing.write_bytes(b"user content")
            self.assertEqual(direct.convert_folder(str(root),str(out))["failed"],1)
            self.assertEqual(existing.read_bytes(),b"user content")
            with self.assertRaises(ValueError):
                direct.convert_folder(str(root),str(root/"out"))


    def test_explicit_midi_metadata_missing_lyr_artist(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["Title: title","Artist: ","Key: C"],body="ทดสอบ")
            data=midi.read_bytes()
            label=b"Artist: Real Singer"
            event=b"\x00\xff\x01"+bytes([len(label)])+label
            track=event+data[22:]
            midi.write_bytes(data[:18]+struct.pack(">I",len(track))+track)
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            import json
            row=json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            self.assertEqual(row["artist"],"Real Singer")

    def test_actual_10000_synthetic_conversions_and_resume(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            first=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            triplet={ext:first.with_suffix(ext).read_bytes() for ext in (".mid",".lyr",".cur")}
            for number in range(2,10001):
                for ext,data in triplet.items():
                    (root/(f"{number:05d}"+ext)).write_bytes(data)
            start=time.monotonic()
            result=direct.convert_folder(str(root),str(out))
            elapsed=time.monotonic()-start
            self.assertEqual((result["converted"],result["failed"]),(10000,0),result)
            self.assertEqual(len(list(out.glob("*.xmid"))),10000)
            self.assertFalse(list(Path(d).rglob("*.sqlite*")))
            self.assertEqual(first.read_bytes(),triplet[".mid"])
            start=time.monotonic()
            resumed=direct.convert_folder(str(root),str(out))
            resume_elapsed=time.monotonic()-start
            self.assertEqual((resumed["skipped"],resumed["failed"]),(10000,0),resumed)
            print(f"NCN_SYNTHETIC_BENCHMARK count=10000 convert_seconds={elapsed:.3f} resume_seconds={resume_elapsed:.3f}",flush=True)


class DirectCreditTests(unittest.TestCase):
    def test_head_footer_without_cursor_and_missing_artist(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","","C","","เครดิต: ผู้จัดทำ"])
            lyr=midi.with_suffix(".lyr")
            lyr.write_bytes(lyr.read_bytes()+".....เต่า คาราโอเกะ......\r\n".encode("cp874"))
            before=lyr.read_bytes()
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            row=json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            self.assertEqual(row["artist"],"")
            self.assertTrue(row["header_credit"])
            self.assertTrue(row["footer_credit"])
            self.assertEqual(lyr.read_bytes(),before)
            self.assertEqual(result["with_credits"],1)
            self.assertEqual(result["with_warnings"],1)
            core.read_xfile(out/"00001.xmid",verify_media=True)

    def test_surplus_real_public_fixture(self):
        import json
        root=Path(__file__).resolve().parent/"fixtures"/"dontreecrab_ncn"
        with tempfile.TemporaryDirectory() as d:
            result=direct.convert_folder(str(root),d)
            self.assertEqual(result["converted"],1,result)
            row=json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            self.assertEqual(row["unused_cursor_values"],13)
            self.assertEqual(row["title"],"Test Song")
            self.assertEqual(row["artist"],"DontreeCrab")

    def test_real_unmeasured_lyric_not_discarded(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            lyr=midi.with_suffix(".lyr")
            lyr.write_bytes(lyr.read_bytes()+"เนื้อร้องอีกบรรทัด\r\n".encode("cp874"))
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["failed"],1,result)
            self.assertFalse(list(out.glob("*.xmid")))

    def test_timed_credit_kept_as_lyric(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""],body="เครดิต: ผู้จัดทำ")
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            self.assertEqual(result["with_credits"],0)


class ObservedLegacyLayoutTests(unittest.TestCase):
    def test_empty_key_dot_and_surplus(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["title","artist","","."],body="abc")
            lyr=midi.with_suffix(".lyr")
            cur=midi.with_suffix(".cur")
            body=["abc"]
            count=sum(len(x)+1 for x in body)
            cur.write_bytes(struct.pack("<"+"H"*(count+5),*(list(range(count))+[65535]*5)))
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)

    def test_bad_final_credit_never_invalidates_real_lyrics(self):
        import json
        for footer in ("Music_By_นิค_คาราโอเกะ","GMM Grammy","By_นิค_คาราโอเกะ"):
            with self.subTest(footer=footer),tempfile.TemporaryDirectory() as d:
                root=Path(d)/"in";out=Path(d)/"out"
                midi=fixture(root,["title","artist","C","."],body="abc")
                lyr=midi.with_suffix(".lyr");cur=midi.with_suffix(".cur")
                lyr.write_bytes(lyr.read_bytes()+(footer+"\r\n").encode("cp874"))
                cur.write_bytes(cur.read_bytes()+b"\xff\xff"*(len(footer)+1))
                before=cur.read_bytes()
                result=direct.convert_folder(str(root),str(out))
                self.assertEqual(result["converted"],1,result)
                row=json.loads(Path(result["report"]).read_text(encoding="utf-8"))
                self.assertEqual(row["footer_credit"],[footer])
                self.assertEqual(cur.read_bytes(),before)

    def test_exact_cursor_vendor_trailer_and_unknown_suffix(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["title","artist","C","."],body="abc")
            cur=midi.with_suffix(".cur")
            original=cur.read_bytes()
            cur.write_bytes(original+b"\xffwww.patongbusiness.com")
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            self.assertEqual(cur.read_bytes(),original+b"\xffwww.patongbusiness.com")
            self.assertEqual(direct.normalize_cursor_trailer(original+b"X")[0],original+b"X")

    def test_padded_binary_appendix_requires_exact_count(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["title","artist","C","."],body="abc")
            lyr=midi.with_suffix(".lyr");cur=midi.with_suffix(".cur")
            original=lyr.read_bytes()
            appended=original+b"\r\n\r\n\r\n"+b" "*30+b"\x81\x00\x02"
            lyr.write_bytes(appended)
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            self.assertEqual(lyr.read_bytes(),appended)
            self.assertEqual(direct.normalize_lyric_trailer(appended,b"\x00\x00")[0],appended)


class ResumeVerificationTests(unittest.TestCase):
    def test_fast_resume_retries_failure_and_verify_mode_rechecks(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            first=fixture(root,["title","artist","C",""],body="abc")
            bad=root/"00002.mid"
            for ext in (".mid",".lyr",".cur"):
                bad.with_suffix(ext).write_bytes(first.with_suffix(ext).read_bytes())
            bad.with_suffix(".cur").write_bytes(b"\0")
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual((result["converted"],result["failed"]),(1,1),result)
            original=direct.convert_one
            with patch.object(direct,"convert_one",wraps=original) as convert:
                again=direct.convert_folder(str(root),str(out))
                self.assertEqual((again["fast_resumed"],again["failed"],convert.call_count),(1,1,1),again)
            bad.with_suffix(".cur").write_bytes(first.with_suffix(".cur").read_bytes())
            self.assertEqual(direct.convert_folder(str(root),str(out))["converted"],1)
            with patch.object(direct,"convert_one",wraps=original) as convert:
                full=direct.convert_folder(str(root),str(out),mode="verify")
                self.assertEqual((full["fast_resumed"],full["skipped"],convert.call_count),(0,2,2),full)
            first.with_suffix(".lyr").write_bytes(first.with_suffix(".lyr").read_bytes().replace(b"abc",b"xyz"))
            existing=(out/"00001.xmid").read_bytes()
            changed=direct.convert_folder(str(root),str(out))
            self.assertEqual((changed["fast_resumed"],changed["failed"]),(1,1),changed)
            self.assertEqual((out/"00001.xmid").read_bytes(),existing)

    def test_deleted_or_modified_output_is_not_fast_resumed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            fixture(root,["title","artist","C",""],body="abc")
            self.assertEqual(direct.convert_folder(str(root),str(out))["converted"],1)
            target=out/"00001.xmid"
            target.unlink()
            again=direct.convert_folder(str(root),str(out))
            self.assertEqual((again["converted"],again["fast_resumed"]),(1,0),again)
            target.write_bytes(b"external file")
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual((result["failed"],result["fast_resumed"]),(1,0),result)
            self.assertEqual(target.read_bytes(),b"external file")


class ObservedMidiAndAlignmentTests(unittest.TestCase):
    def test_anchored_timed_leading_credit_with_surplus(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            lead="Nick_Karaoke"; body="abc"
            midi=fixture(root,["title","artist","",".",lead],body=body)
            cur=midi.with_suffix(".cur")
            count=len(lead)+1+len(body)+1
            cur.write_bytes(struct.pack("<"+"H"*(count+3),*(list(range(count))+[65535]*3)))
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            parsed=core.read_xfile(out/"00001.xmid",verify_media=True)
            self.assertEqual([x["text"] for x in parsed["lines"]],[lead,body])

    def test_ambiguous_blank_marker_does_not_guess(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["title","artist","C",""],body="abc")
            lyr=midi.with_suffix(".lyr");cur=midi.with_suffix(".cur")
            lyr.write_bytes(lyr.read_bytes()+b"\r\ndef\r\n")
            cur.write_bytes(struct.pack("<12H",*range(12)))
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["failed"],1,result)
            self.assertIn("Ambiguous blank-line CUR alignment",result["errors"])

    def test_observed_marker_normalized_only_after_full_track_validation(self):
        import hashlib,json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["title","artist","C",""],body="abc")
            standard=midi.read_bytes()
            legacy=direct.reader.OBSERVED_SMF_MARKER+standard[4:]
            midi.write_bytes(legacy)
            result=direct.convert_folder(str(root),str(out))
            self.assertEqual(result["converted"],1,result)
            row=json.loads(Path(result["report"]).read_text(encoding="utf-8"))
            self.assertTrue(row["midi_header_normalized"])
            self.assertEqual(row["original_midi_sha256"],hashlib.sha256(legacy).hexdigest())
            target=out/"00001.xmid"
            info=core.read_xfile(target,verify_media=True)
            self.assertEqual(target.read_bytes()[info["mediaOffset"]:],standard)
            self.assertEqual(midi.read_bytes(),legacy)
            # Nonstandard marker alone is never sufficient to accept a file.
            for data in (legacy[:-1],legacy+b"trailing",b"????"+standard[4:]):
                with self.assertRaises(ValueError):
                    direct.reader.midi_events(midi,raw_data=data,include_duration=True)


class PriorReportRetryTests(unittest.TestCase):
    def test_failed_only_mode_reuses_old_report_without_parser_cache(self):
        import json
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["title","artist","C",""],body="abc")
            first=direct.convert_folder(str(root),str(out))
            self.assertEqual(first["converted"],1)
            # Simulate report from v0.1.46: status/code/path but no stamp.
            (out/".ncn-resume.json").unlink()
            report=Path(first["report"])
            row=json.loads(report.read_text(encoding="utf-8"))
            row.pop("resume",None)
            report.write_text(json.dumps(row)+"\n",encoding="utf-8")
            original=direct.convert_one
            with patch.object(direct,"convert_one",wraps=original) as convert:
                result=direct.convert_folder(str(root),str(out),mode="failed_only")
                self.assertEqual((result["report_skipped"],result["fast_resumed"],convert.call_count),(1,0,0),result)
            with patch.object(direct,"convert_one",wraps=original) as convert:
                full=direct.convert_folder(str(root),str(out),mode="verify")
                self.assertEqual((full["report_skipped"],full["skipped"],convert.call_count),(0,1,1),full)

class BufferedDiagnosticsTests(unittest.TestCase):
    def test_csv_categories_summary_and_unchanged_sources(self):
        import csv
        import json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            midi=fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            (root/"00002.mid").write_bytes(midi.read_bytes())
            before={p.name:p.read_bytes() for p in root.iterdir()}
            first=direct.convert_folder(str(root),str(out))
            self.assertEqual((first["converted"],first["rejected"],first["failed"]),(1,1,1))
            folder=Path(first["log_folder"])
            def rows(folder,name):
                raw=(folder/(name+".csv")).read_bytes()
                self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
                with (folder/(name+".csv")).open(encoding="utf-8-sig",newline="") as f:
                    return list(csv.DictReader(f))
            self.assertEqual(rows(folder,"converted")[0]["title"],"ชื่อจริง")
            self.assertEqual(rows(folder,"rejected")[0]["error_code"],"MISSING_LYR_CUR")
            self.assertEqual(rows(folder,"error"),[])
            self.assertEqual(json.loads((folder/"summary.json").read_text(encoding="utf-8")),first)
            second=direct.convert_folder(str(root),str(out))
            self.assertEqual(second["skipped"],1)
            self.assertEqual(len(rows(Path(second["log_folder"]),"existing")),1)
            self.assertNotEqual(first["log_folder"],second["log_folder"])
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            self.assertFalse(list(Path(d).rglob("*.sqlite*")))

    def test_safe_cancel_flushes_partial_report(self):
        import csv
        import json
        import threading
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"in";out=Path(d)/"out"
            fixture(root,["ชื่อจริง","ศิลปินจริง","C",""])
            (root/"00002.mid").write_bytes(b"bad")
            cancel=threading.Event()
            def progress(stats,message):
                if stats["done"]:
                    cancel.set()
            result=direct.convert_folder(str(root),str(out),progress,cancel)
            self.assertTrue(result["cancelled"])
            self.assertEqual(result["done"],1)
            self.assertEqual(len(Path(result["report"]).read_text(encoding="utf-8").splitlines()),1)
            folder=Path(result["log_folder"])
            with (folder/"converted.csv").open(encoding="utf-8-sig",newline="") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))),1)
            self.assertTrue(json.loads((folder/"summary.json").read_text(encoding="utf-8"))["cancelled"])

    def test_spreadsheet_formula_escaped(self):
        self.assertEqual(direct.csv_cell("=1+1"),"'=1+1")
        self.assertEqual(direct.csv_cell("ชื่อเพลง"),"ชื่อเพลง")
