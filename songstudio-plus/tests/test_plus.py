"""End-to-end regressions for the entirely separate X-Stage Song Studio Plus."""
from __future__ import annotations
import importlib
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import plus_core as plus

def varlen(n):
    out=[n&127]
    n >>=7
    while n:
        out.insert(0,0x80|(n&127)); n>>=7
    return bytes(out)

def midi():
    # 20 seconds of legal MIDI events to bound NCN lyric timing.
    track=(b"\x00\xff\x51\x03\x07\xa1\x20"+
           b"\x00\x90\x3c\x64"+
           varlen(480*20)+b"\x80\x3c\x00"+
           b"\x00\xff\x2f\x00")
    return (b"MThd"+struct.pack(">IHHH",6,0,1,480)+
            b"MTrk"+struct.pack(">I",len(track))+track)

class PlusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.workspace=self.base/"workspace"
        self.src=self.base/"input"
        self.src.mkdir()
        plus.init(self.workspace)

    def tearDown(self):
        self.temp.cleanup()

    def put(self,name,data):
        p=self.src/name
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
        return p

    def lrc(self,path,text="[00:01.00]By Nick >>>\n[00:05.00]Next line\n"):
        (path.parent/(path.stem+".lrc")).write_text(text,encoding="utf-8")

    def test_windows_ui_scales_and_remains_offline_ready(self):
        root=Path(__file__).resolve().parents[1]
        desktop=(root/"desktop_ui.py").read_text(encoding="utf-8")
        css=(root/"web"/"style.css").read_text(encoding="utf-8")
        html=(root/"web"/"index.html").read_text(encoding="utf-8")
        self.assertIn("self.base_zoom=1.20",desktop)
        self.assertIn("fit_zoom(self.width(),self.height()",desktop)
        self.assertIn("def resizeEvent(self,event):",desktop)
        self.assertIn("def reset_zoom(self):",desktop)
        self.assertIn("self.web.setZoomFactor(self.default_zoom)",desktop)
        for shortcut in ("Ctrl++","Ctrl+-","Ctrl+0"):
            self.assertIn(shortcut,desktop)
        self.assertIn("max-width:2800px",css)
        self.assertIn("font-family:\"Segoe UI\"",css)
        self.assertNotIn("fonts.googleapis.com",css)
        self.assertIn("zoom-hint",html)
        self.assertIn('id="stat-ready"',html)
        self.assertIn('id="stat-pending"',html)
        self.assertIn('id="issues-load"',html)
        self.assertIn('id="recover-lyrics"',html)
        self.assertIn('id="stat-with-text"',html)

    def test_build_catalog_filters_ready_and_review_with_incremental_offsets(self):
        import manual_editor as manual
        ready=self.put("NCN_A.mp3",b"MUSIC-READY"*500)
        self.lrc(ready,"[00:01.00]พร้อมสร้าง\\n[00:05.00]ต่อไป\\n")
        review=self.put("REVIEW.mp3",b"MUSIC-REVIEW"*500)
        self.lrc(review,"[00:01.00]รอตรวจ\\n[00:05.00]ต่อไป\\n")
        missing=self.put("MISSING.mp3",b"MUSIC-NO-LYR"*500)
        plus.import_folder(self.workspace,self.src)
        # LRC creates an estimated version, requiring manual approval.
        rows=plus.songs(self.workspace)
        review_song=next(r for r in rows if r["title"]=="REVIEW")
        ready_song=next(r for r in rows if r["title"]=="NCN_A")
        self.assertTrue(manual.approve(
            self.workspace,ready_song["id"],ready_song["version_id"])["approved"])
        first=manual.build_catalog(self.workspace,"attention",0,1)
        second=manual.build_catalog(self.workspace,"attention",first["offset"],1)
        self.assertEqual(len(first["rows"]),1)
        self.assertTrue(first["has_more"])
        self.assertEqual(len(second["rows"]),1)
        self.assertNotEqual(first["rows"][0]["id"],second["rows"][0]["id"])
        self.assertEqual({x["manual_status"] for x in first["rows"]+second["rows"]},
                         {"review","missing"})
        self.assertEqual([r["id"] for r in manual.build_catalog(
            self.workspace,"ready")["rows"]],[ready_song["id"]])
        manual.approve(self.workspace,review_song["id"],review_song["version_id"])
        remaining=manual.build_catalog(self.workspace,"attention")["rows"]
        self.assertEqual([r["manual_status"] for r in remaining],["missing"])
        self.assertEqual(len(manual.build_catalog(self.workspace,"ready")["rows"]),2)
        with self.assertRaises(ValueError):
            manual.build_catalog(self.workspace,"invalid")


    def test_catalog_build_stream_enumerates_all_registered_songs_even_unready(self):
        import manual_editor as manual
        ready=self.put("S1.mid",midi())
        self.lrc(ready)
        missing=self.put("S2.mid",midi()+b"extra")
        # The second file has no lyric data; it must still enter the entire
        # catalog and be reported as blocked, never silently excluded.
        plus.import_folder(self.workspace,self.src)
        songs=plus.songs(self.workspace)
        self.assertEqual(len(songs),2)
        self.assertEqual(plus.catalog_song_count(self.workspace),2)
        ids=list(plus.catalog_song_ids(self.workspace,batch_size=1))
        self.assertEqual(set(ids),{s["id"] for s in songs})
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(manual.ready_count(self.workspace),0)
        self.assertEqual(manual.approved_build_ids(self.workspace),[])
        for song in songs:
            if song["title"]=="S2":
                with self.assertRaisesRegex(ValueError,"ยังไม่มีเนื้อร้องพร้อมเวลา"):
                    plus.build_song(self.workspace,song["id"])
        self.assertEqual(plus.catalog_song_count(self.workspace),2)

    def test_mid_registry_dedup_survives_separate_builds_and_restarts(self):
        # Same physical MIDI can be registered under different names/paths.
        # The SQLite catalog and XMID output must contain only one copy.
        original=self.put("A/song-a.mid",midi())
        self.lrc(original)
        duplicate=self.put("B/song-b.mid",original.read_bytes())
        self.lrc(duplicate)
        imported=plus.import_folder(self.workspace,self.src)
        self.assertEqual(imported["files_new"],1)
        self.assertEqual(imported["media_duplicates"],1)
        songs=plus.songs(self.workspace)
        self.assertEqual(len(songs),1)
        sid=songs[0]["id"]
        first=plus.build_song(self.workspace,sid)
        self.assertFalse(first["skipped"])
        output=Path(first["path"])
        self.assertEqual(output.suffix,".xmid")
        self.assertEqual(output.name,"00001.xmid")
        self.assertEqual(plus.read_xfile(output)["code"],"00001")
        initial_mtime=output.stat().st_mtime_ns
        with plus.connect(self.workspace) as db:
            row=db.execute("""SELECT * FROM xstage_midi_export_registry""").fetchone()
            self.assertEqual(row["midi_sha256"],plus.digest(original))
            self.assertEqual(row["song_id"],sid)
            self.assertEqual(row["output_sha256"],first["sha256"])
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM xstage_midi_export_registry").fetchone()[0],1)
        for _ in range(2):
            reused=plus.build_song(self.workspace,sid)
            self.assertTrue(reused["skipped"])
            self.assertEqual(reused["sha256"],first["sha256"])
            self.assertEqual(output.stat().st_mtime_ns,initial_mtime)
        plus._INITIALIZED.clear()  # simulate another app process
        self.assertTrue(plus.build_song(self.workspace,sid)["skipped"])
        self.assertEqual(output.stat().st_mtime_ns,initial_mtime)
        # Older SQLite databases lack the new fingerprint ledger. Backfill
        # verified existing files instead of creating a duplicate output.
        with plus.connect(self.workspace) as db:
            db.execute("DELETE FROM xstage_midi_export_registry")
        self.assertTrue(plus.build_song(self.workspace,sid)["skipped"])
        with plus.connect(self.workspace) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM xstage_midi_export_registry").fetchone()[0],1)
        self.assertEqual(output.stat().st_mtime_ns,initial_mtime)

    def test_mid_registry_rejects_corrupt_output_in_later_run(self):
        src=self.put("corruption.mid",midi())
        self.lrc(src)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        built=plus.build_song(self.workspace,song["id"])
        target=Path(built["path"])
        with target.open("ab") as out:
            out.write(b"corrupt-content")
        plus._INITIALIZED.clear()
        with self.assertRaisesRegex(ValueError,"ปลายทางมีไฟล์ที่ไม่ตรงกับทะเบียน"):
            plus.build_song(self.workspace,song["id"])

    def test_exported_song_does_not_enter_build_queue_again(self):
        import manual_editor as manual
        path=self.put("single.mp3",b"PAYLOAD-MP3"*900)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        manual.approve(self.workspace,song["id"],song["version_id"])
        self.assertEqual(len(manual.build_catalog(self.workspace,"ready")["rows"]),1)
        self.assertEqual(len(manual.build_catalog(self.workspace,"converted")["rows"]),0)
        first=plus.build_song(self.workspace,song["id"])
        self.assertFalse(first["skipped"])
        self.assertEqual(manual.build_catalog(self.workspace,"ready")["rows"],[])
        self.assertEqual(len(manual.build_catalog(self.workspace,"converted")["rows"]),1)
        self.assertEqual(manual.approved_build_ids(self.workspace),[])
        self.assertEqual(manual.ready_count(self.workspace),0)
        self.assertEqual(manual.approved_selected_ids(self.workspace,[song["id"]]),set())
        # A later build must query the on-disk SQLite export record, not an
        # ephemeral selection in memory. Even when the original has moved,
        # an unchanged, verified output must not be written again.
        result_path=Path(first["path"])
        original_bytes=result_path.read_bytes()
        initial_mtime=result_path.stat().st_mtime_ns
        with plus.connect(self.workspace) as db:
            record=db.execute("""SELECT version_id,sha256,output_path
              FROM xstage_exports WHERE song_id=?""",(song["id"],)).fetchone()
            self.assertEqual(record["version_id"],song["version_id"])
            self.assertEqual(record["sha256"],first["sha256"])
        for repeat in range(2):
            second=plus.build_song(self.workspace,song["id"])
            self.assertTrue(second["skipped"])
            self.assertEqual(second["sha256"],first["sha256"])
            self.assertEqual(result_path.stat().st_mtime_ns,initial_mtime)
            self.assertEqual(result_path.read_bytes(),original_bytes)
        # Drop the per-process initialization cache to exercise a reopened
        # workspace connection as happens after restarting the application.
        plus._INITIALIZED.clear()
        self.assertTrue(plus.build_song(self.workspace,song["id"])["skipped"])
        self.assertEqual(result_path.stat().st_mtime_ns,initial_mtime)

    def test_schema_all_tables_prefixed_and_separate_from_legacy(self):
        with plus.connect(self.workspace) as db:
            names=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertTrue(names)
        self.assertTrue(all(x.startswith("xstage_") or x.startswith("sqlite_") for x in names))
        self.assertFalse((self.workspace/"DB"/"song-registry.sqlite3").exists())

    def test_same_media_different_name_or_source_reuses_media(self):
        one=self.put("PC_A/00001.mp3",b"\xff\xfb"+"A".encode()*4000)
        self.lrc(one)
        two=self.put("PC_B/99999.mp3",one.read_bytes())
        self.lrc(two,"[00:01.00]Nick Different\n[00:05.00]Next line\n")
        summary=plus.import_folder(self.workspace,self.src)
        self.assertEqual(summary["files_new"],1)
        self.assertEqual(summary["media_duplicates"],1)
        report=plus.stats(self.workspace)
        self.assertEqual(report["songs"],1)
        self.assertEqual(report["media"],1)
        self.assertEqual(report["lyrics"],2)
        self.assertEqual(report["songs_with_lyrics"],1)
        self.assertEqual(report["songs_without_lyrics"],0)
        self.assertEqual(report["lyrics_versions"],2)
        self.assertEqual(report["songs_estimated_timing"],1)
        rows=plus.songs(self.workspace)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["code"],1)
        self.assertEqual(len(list((self.workspace/"SOURCE").rglob("*.mp3"))),0)
        with plus.connect(self.workspace) as db:
            sources=db.execute("SELECT source_path FROM xstage_media_sources").fetchall()
        self.assertEqual(len(sources),2)
        self.assertIn(str(one.resolve()),{x["source_path"] for x in sources})

    def test_rerun_import_does_not_duplicate_media_or_lyrics(self):
        path=self.put("track.mp3",b"MP3-CONTENT"*500)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        before=plus.stats(self.workspace)
        result=plus.import_folder(self.workspace,self.src)
        after=plus.stats(self.workspace)
        self.assertEqual(result["files_new"],0)
        self.assertEqual(result["lyrics_new"],0)
        self.assertEqual(result["hash_cache_hits"],1)
        self.assertEqual(result["bytes_hashed"],0)
        self.assertEqual({k:before[k] for k in ("songs","media","lyrics")},
                         {k:after[k] for k in ("songs","media","lyrics")})

    def test_same_filename_different_bytes_get_unique_code(self):
        self.put("A/00001.mid",midi())
        self.put("B/00001.mid",midi()+b"extension")
        out=plus.import_folder(self.workspace,self.src)
        self.assertEqual(out["files_new"],2)
        songs=plus.songs(self.workspace)
        self.assertEqual(len(songs),2)
        self.assertEqual(len({x["code"] for x in songs}),2)

    def test_lyric_search_separates_current_lines_from_song_metadata(self):
        path=self.put("english.mp3",b"MP3-ENGLISH"*1200)
        self.lrc(path,"[00:01.00]Some real lyrics\n[00:05.00]Love line\n")
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        with plus.connect(self.workspace) as db:
            db.execute("""UPDATE xstage_songs SET title=?,artist=? WHERE id=?""",
                ("Karaoke Evening","XSTAGE Artist",song["id"]))
        result=plus.search_context(self.workspace,"kArAoKe")
        self.assertEqual(len(result["songs"]),1)
        self.assertEqual(result["songs"][0]["title"],"Karaoke Evening")
        self.assertTrue(result["songs"][0]["has_current_lyrics"])
        self.assertEqual(plus.groups(self.workspace,"karaoke"),[],
                         "A song-title match must never be an editable lyric group")
        self.assertEqual(len(plus.groups(self.workspace,"love")),1)
        self.assertEqual(
            plus.plan_edit(self.workspace,"karaoke",["karaoke evening"])["lines"],0,
            "A metadata-only key must never select lyrics for replacement")
        result_artist=plus.search_context(self.workspace,"xstage")
        self.assertEqual(len(result_artist["songs"]),1)
        self.assertEqual(plus.search_context(self.workspace,"%")["songs"],[],
                         "Wildcard input must be treated as literal")

    def test_lyric_search_finds_untimed_drafts_without_bulk_replacing(self):
        self.put("unfinished.mp3",b"MP3-UNFINISHED"*1000)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        with plus.connect(self.workspace) as db:
            db.execute("""INSERT INTO xstage_lyric_drafts
                (song_id,source_path,title,artist,raw_text,reason,updated_at)
                VALUES (?,?,?,?,?,?,?)""",
                (song["id"],"missing.lyr","Untimed","Singer",
                 "ข้อความรอเวลา Karaoke นะครับ","waiting-cur",plus.now()))
        result=plus.search_context(self.workspace,"karaoke")
        self.assertEqual(result["songs"],[])
        self.assertEqual(len(result["drafts"]),1)
        self.assertEqual(result["drafts"][0]["id"],song["id"])
        self.assertEqual(plus.groups(self.workspace,"karaoke"),[],
                         "Untimed draft content is not an editable timed group")

    def test_settings_exposes_real_update_actions_and_lyric_groups(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/"web"/"index.html").read_text(encoding="utf-8")
        js=(root/"web"/"app.js").read_text(encoding="utf-8")
        for control in ("settings-update-check","settings-update-install",
                        "settings-update-direct","lyrics-search-feedback",
                        "group-list","groups-scroll-status"):
            self.assertIn('id="'+control+'"',html)
            self.assertIn('"'+control+'"',js)
        self.assertNotIn('id="lyrics-search-context"',html)
        self.assertNotIn('api("/api/lyrics/search-context',js)
        self.assertIn('api("/api/groups',js)
        self.assertIn('syncSettingsUpdate()',js)

    def test_remove_song_from_active_catalog_preserves_sqlite_and_source(self):
        media=self.put("remove-safe.mp3",b"SAFE-ORIGINAL"*500)
        plus.import_folder(self.workspace,self.src)
        before=plus.songs(self.workspace)
        self.assertEqual(len(before),1)
        item=before[0]
        result=plus.hide_song(self.workspace,item["id"])
        self.assertTrue(result["removed"])
        self.assertTrue(media.is_file())
        self.assertEqual(plus.songs(self.workspace),[])
        self.assertEqual(plus.catalog_song_count(self.workspace),0)
        self.assertEqual(list(plus.catalog_song_ids(self.workspace)),[])
        with plus.connect(self.workspace) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM xstage_songs WHERE id=?",
                (item["id"],)).fetchone()[0],1)

    def test_encoded_looking_lyric_groups_are_hidden_but_source_preserved(self):
        plain=self.put("encoded.mp3",b"ENCODED-MEDIA"*500)
        token=("bw3woQ5X2H2lgLFMsIMNVxkmG9iXBN4p"
               "P10eyckXWBD4IWU7f4535O15oW5sR9Y4q8T7n2W6")
        self.lrc(plain,f"[00:01.00]{token}\n[00:05.00]GMM Grammy\n")
        plus.import_folder(self.workspace,self.src)
        self.assertTrue(plus.suspicious_lyric_text(token))
        self.assertTrue(plus.suspicious_lyric_text("84EYeOdPWRChjjIB+pgMmA8o"))
        self.assertTrue(plus.suspicious_lyric_text(
            "5ozaQcAG9CnEtIQsYn8vnBDjGGP4")) 
        self.assertFalse(plus.suspicious_lyric_text("*****GMM Grammy*****"))
        self.assertFalse(plus.suspicious_lyric_text("รักเธอเสมอ"))
        self.assertFalse(plus.suspicious_lyric_text("Long lyric line with spaces 2026"))
        self.assertEqual(plus.groups(self.workspace,"bw3wo"),[])
        self.assertEqual([x["text"] for x in plus.groups(self.workspace,"GMM")],
                         ["GMM Grammy"])
        with plus.connect(self.workspace) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM xstage_lyric_lines WHERE text=?",
                (token,)).fetchone()[0],1)
            with self.assertRaisesRegex(ValueError,"ข้อมูลเข้ารหัส"):
                plus.chosen_rows(db,"bw3wo",[token])

    def test_group_replace_and_undo_preserve_independent_line_bounds(self):
        old=["[00:02.00].....nick.....\n[00:06.00]Keep A\n",
             "[00:09.00]Nick ......\n[00:15.00]Keep B\n",
             "[00:18.00]By  nick >>>\n[00:25.00]Keep C\n"]
        for n,lyrics in enumerate(old):
            path=self.put(f"track{n}.mp3",bytes([n+10])*1000)
            self.lrc(path,lyrics)
        plus.import_folder(self.workspace,self.src)
        found=plus.groups(self.workspace,"NiCk")
        self.assertEqual(len(found),3)
        self.assertEqual(sorted(x["lines"] for x in found),[1,1,1])
        keys=[x["group_key"] for x in found]
        plan=plus.plan_edit(self.workspace,"Nick",keys)
        self.assertEqual((plan["songs"],plan["lines"]),(3,3))
        before={}
        for song in plus.songs(self.workspace):
            with plus.connect(self.workspace) as db:
                v=db.execute("SELECT id FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",
                             (song["id"],)).fetchone()
                before[song["id"]]=plus.get_version_lines(db,v["id"])
        result=plus.replace_groups(self.workspace,"Nick",keys,"x-stage karaoke",3)
        self.assertEqual((result["changed_songs"],result["changed_lines"]),(3,3))
        for song in plus.songs(self.workspace):
            with plus.connect(self.workspace) as db:
                v=db.execute("SELECT * FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",
                             (song["id"],)).fetchone()
                after=plus.get_version_lines(db,v["id"])
            self.assertEqual(after[0][0]["text"],"x-stage karaoke")
            self.assertEqual(after[0][0]["start_time"],before[song["id"]][0][0]["start_time"])
            self.assertEqual(after[0][0]["end_time"],before[song["id"]][0][0]["end_time"])
            self.assertEqual(after[1][0]["text"],before[song["id"]][1][0]["text"])
            self.assertEqual(after[1][0]["start_time"],before[song["id"]][1][0]["start_time"])
            self.assertEqual(after[0][0]["timing_status"],"estimated")
        self.assertEqual(plus.undo_edit(self.workspace,result["batch"])["restored_songs"],3)
        self.assertEqual(len(plus.groups(self.workspace,"Nick")),3)

    def test_batch_replacement_succeeds_even_if_original_cue_text_is_misaligned(self):
        """Real legacy NCN-like mismatch must not roll back the entire selection."""
        import threading
        for index in range(3):
            path=self.put(f"corrupt_{index}.mp3",bytes([index+15])*1200)
            self.lrc(path,f"[00:02.00]Nick Footer {index}\n[00:08.00]Keep\n")
        plus.import_folder(self.workspace,self.src)
        selections=plus.groups(self.workspace,"Nick")
        self.assertEqual(len(selections),3)
        keys=[x["group_key"] for x in selections]
        with plus.connect(self.workspace) as db:
            matched=list(plus.chosen_rows(db,"Nick",keys))
            self.assertEqual(len(matched),3)
            # Same behavior as a malformed legacy NCN CUR: cue segments
            # exist but do not reconstruct the original line exactly.
            db.execute("UPDATE xstage_lyric_cues SET text='BROKEN' WHERE id=("
                "SELECT id FROM xstage_lyric_cues WHERE line_id=? ORDER BY position LIMIT 1)",
                (matched[0]["id"],))
            # Another song has zero individual cursor positions.
            db.execute("DELETE FROM xstage_lyric_cues WHERE line_id=?",
                       (matched[1]["id"],))
        stages=[]
        outcome=plus.replace_groups(self.workspace,"Nick",keys,
             "X-Stage Karaoke",3,lambda progress,message: stages.append(progress),None)
        self.assertEqual(outcome["changed_lines"],3)
        self.assertEqual(outcome["changed_songs"],3)
        self.assertEqual(outcome["needs_review_lines"],1)
        self.assertEqual(outcome["combined_lines"],2)
        self.assertEqual(outcome["padded_lines"],0)
        self.assertTrue(stages and stages[-1]["done"]==3)
        with plus.connect(self.workspace) as db:
            for row in matched:
                current=db.execute("""SELECT * FROM xstage_lyric_versions
                    WHERE song_id=? AND is_current=1""",
                    (row["song_id"],)).fetchone()
                lyrics=plus.get_version_lines(db,current["id"])
                self.assertEqual(lyrics[0][0]["text"],"X-Stage Karaoke")
                self.assertEqual(lyrics[0][0]["start_time"],row["start_time"])
                self.assertEqual(lyrics[0][0]["end_time"],row["end_time"])
                if row==matched[1]:
                    self.assertEqual(current["timing_status"],"incomplete")
                    self.assertEqual(lyrics[0][0]["timing_status"],"incomplete")
                    self.assertEqual(lyrics[0][1],[])
                else:
                    self.assertEqual(lyrics[0][0]["timing_status"],"estimated")
                    self.assertEqual("".join(cue["text"] for cue in
                        plus.display_cues(lyrics[0][0]["text"],lyrics[0][1])),
                        "X-Stage Karaoke")
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM xstage_edit_changes WHERE batch_id=?",
                (outcome["batch"],)).fetchone()[0],3)
        self.assertEqual(plus.undo_edit(self.workspace,outcome["batch"])["restored_songs"],3)
        self.assertEqual(plus.plan_edit(self.workspace,"Nick",keys)["lines"],3)

    def test_replacement_pads_cursor_slots_and_combines_swipe_without_new_times(self):
        def source(values,text):
            return [{"text":ch,"start_time":at,"duration":.5}
                    for ch,at in zip(text,values)]
        original="By Nick >>>"
        measured=[1.0+i*.25 for i in range(len(original))]
        cues=source(measured,original)
        changed,status=plus.remap_cues(original,"X-Stage",1.,5.,cues)
        self.assertEqual(status,"estimated")
        self.assertEqual(len(changed),len(cues))
        self.assertEqual([v[1] for v in changed],measured)
        self.assertEqual([v[0] for v in changed][len(plus.glyphs("X-Stage")):],
                         [">"]*(len(cues)-len(plus.glyphs("X-Stage"))))
        serialized=[{"text":v[0],"start_time":v[1],"duration":v[2]} for v in changed]
        self.assertEqual("".join(c["text"] for c in
                                 plus.display_cues("X-Stage",serialized)),"X-Stage")
        # Existing literal > characters are never removed from visible text.
        self.assertEqual(len(plus.display_cues(original,cues)),len(cues))
        self.assertEqual(len(plus.display_cues("X>>",[
            {"text":"X"},{"text":">"},{"text":">"},{"text":">"}])),3)
        # The X container retains all measured positions but makes the
        # added cursor placeholders nonprinting.
        line={"text":"X-Stage","start_time":1.,"end_time":5.,
              "timing_status":"estimated"}
        blob=plus.metadata_bytes({"id":"song","code":1},
                {"id":"version","title":"Title","artist":"Artist",
                 "timing_status":"estimated"},[(line,serialized)])
        packed=plus.decode_metadata(blob)["lines"][0]
        self.assertEqual(packed["text"],"X-Stage")
        self.assertEqual(len(packed["cues"]),len(cues))
        self.assertEqual("".join(x["text"] for x in packed["cues"]),"X-Stage")
        self.assertEqual([x["startTime"] for x in packed["cues"]],measured)

        old="Nick"
        few=[{"text":v,"start_time":t,"duration":.5}
             for v,t in zip(old,(1.0,2.0,3.0,4.0))]
        grouped,status=plus.remap_cues(old,"X-Stage Karaoke",1.,6.,few)
        self.assertEqual(status,"estimated")
        self.assertEqual(len(grouped),len(few))
        self.assertEqual([x[1] for x in grouped],[1.,2.,3.,4.])
        self.assertEqual("".join(x[0] for x in grouped),"X-Stage Karaoke")
        self.assertTrue(any(len(x[0])>1 for x in grouped))
        # A combining Thai vowel/mark is kept with its base letter.
        thai,status=plus.remap_cues(old,"ก้",1.,6.,few)
        self.assertEqual(thai[0][0],"ก้")
        self.assertEqual([x[0] for x in thai[1:]], [">",">",">"])
        corrupted=[{**v,"text":"BROKEN"} for v in few]
        recovered,status=plus.remap_cues(old,"ข้อความใหม่",1.,6.,corrupted)
        self.assertNotEqual(status,"incomplete")
        self.assertEqual([x[1] for x in recovered],[1.,2.,3.,4.])
        self.assertEqual(plus.remap_cues(old,"new",1.,6.,[]),
                         ([],"incomplete"))
        reversed_times=[{**v,"start_time":5-i} for i,v in enumerate(few)]
        self.assertEqual(plus.remap_cues(old,"new",1.,6.,reversed_times),
                         ([],"incomplete"))

    def test_cancelled_group_edit_rolls_back_all_songs(self):
        import threading
        path=self.put("rollback.mp3",b"ROLLBACK"*100)
        self.lrc(path,"[00:02.00]Nick Example\n[00:07.00]Keep\n")
        plus.import_folder(self.workspace,self.src)
        keys=[row["group_key"] for row in plus.groups(self.workspace,"Nick")]
        cancelled=threading.Event()
        cancelled.set()
        with self.assertRaisesRegex(Exception,"ยกเลิก"):
            plus.replace_groups(self.workspace,"Nick",keys,
                                "X-Stage Karaoke",1,cancel=cancelled)
        self.assertEqual(plus.plan_edit(self.workspace,"Nick",keys)["lines"],1)
        with plus.connect(self.workspace) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM xstage_edit_batches").fetchone()[0],0)

    def test_xmedia_binary_stores_source_and_lyrics_without_sidecar(self):
        path=self.put("001.mp3",b"FAKE-MEDIA-TEST"*999)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        result=plus.build_song(self.workspace,song["id"])
        output=Path(result["path"])
        self.assertEqual(output.suffix,".xmp3")
        self.assertEqual(output.parent.parent.name,"XMP3")
        info=plus.inspect_xfile(output,True)
        self.assertEqual(info["media_sha256"],plus.digest(path))
        decoded=plus.read_xfile(output,verify_media=True)
        self.assertEqual(decoded["mediaSha256"],plus.digest(path))
        self.assertEqual(decoded["lines"][0]["text"],"By Nick >>>")
        self.assertEqual(decoded["timingStatus"],"estimated")
        self.assertGreater(len(decoded["lines"][0]["cues"]),0)
        self.assertEqual(decoded["lines"][1]["timingStatus"],"estimated")
        self.assertEqual(decoded["lines"][0]["startTime"],1.0)
        self.assertEqual(decoded["lines"][1]["startTime"],5.0)
        self.assertEqual(decoded["mediaOffset"]+decoded["mediaBytes"],output.stat().st_size)
        self.assertEqual(output.read_bytes()[-path.stat().st_size:],path.read_bytes())
        self.assertTrue(plus.build_song(self.workspace,song["id"])["skipped"])
        self.assertEqual(list(self.workspace.rglob("*.json")),[])
        self.assertEqual(list(self.workspace.rglob("*.xsk")),[])

    def test_midi_ncn_original_bytes_and_lyrics_from_companions(self):
        p=self.put("NCN/Song/0/00001.mid",midi())
        self.put("NCN/Lyrics/0/00001.lyr",
                 "เพลงทดสอบ\nศิลปินทดสอบ\nC\n\nNick\n".encode("cp874"))
        self.put("NCN/Cursor/0/00001.cur",struct.pack("<5H",0,1,2,3,4))
        info=plus.import_folder(self.workspace,self.src)
        self.assertEqual(info["failures"],0)
        rows=plus.songs(self.workspace)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["title"],"เพลงทดสอบ")
        self.assertEqual(rows[0]["artist"],"ศิลปินทดสอบ")
        self.assertEqual(len(plus.groups(self.workspace,"Nick")),1)
        built=plus.build_song(self.workspace,rows[0]["id"])
        self.assertEqual(Path(built["path"]).name,"00001.xmid")
        self.assertEqual(plus.read_xfile(built["path"])["code"],"00001")
        self.assertEqual(plus.inspect_xfile(built["path"],True)["media_sha256"],plus.digest(p))

    def test_only_media_file_is_sha256_hashed_and_ncns_can_recover(self):
        from unittest.mock import patch
        song=self.put("NCN/Song/0/01337.mid",midi())
        lyr=self.put("NCN/Lyrics/0/01337.lyr",
            "เพลงทดสอบ\nศิลปิน\nC\n\nNick\nAnother\n".encode("cp874"))
        # Deliberately short CUR: first line's cues still have real times.
        cur=self.put("NCN/Cursor/0/01337.cur",struct.pack("<5H",0,1,2,3,4))
        original_digest=plus.digest
        with patch.object(plus,"digest",wraps=original_digest) as file_hash:
            first=plus.import_folder(self.workspace,self.src)
        self.assertEqual(first["files_new"],1)
        self.assertEqual(first["partial_lyrics"],1)
        self.assertEqual(first["failures"],0)
        self.assertEqual([Path(x.args[0]).suffix.lower()
                          for x in file_hash.call_args_list],[".mid"])
        song_info=plus.songs(self.workspace)[0]
        self.assertEqual(song_info["timing_status"],"incomplete")
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],0)
        self.assertEqual(plus.stats(self.workspace)["songs_partial_lyrics"],1)
        self.assertEqual(plus.stats(self.workspace)["songs_draft_lyrics"],0)
        with plus.connect(self.workspace) as db:
            draft=db.execute("SELECT raw_text FROM xstage_lyric_drafts").fetchone()[0]
        self.assertIn("Another",draft)
        with self.assertRaisesRegex(ValueError,"CUR"):
            plus.build_song(self.workspace,song_info["id"])
        # Source MID unchanged -> cache its SHA. CUR is re-read but NOT SHA'd.
        cur.write_bytes(struct.pack("<13H",*range(13)))
        with patch.object(plus,"digest",wraps=original_digest) as rehash:
            second=plus.import_folder(self.workspace,self.src)
        self.assertEqual(second["failures"],0)
        self.assertEqual(second["lyrics_new"],1)
        self.assertEqual(second["hash_cache_hits"],1)
        self.assertEqual(rehash.call_count,0)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],1)
        self.assertEqual(plus.stats(self.workspace)["songs_partial_lyrics"],0)
        self.assertEqual(plus.stats(self.workspace)["songs_draft_lyrics"],0)
        self.assertIsNone(plus.songs(self.workspace)[0].get("draft_reason"))

    def test_incomplete_ncn_triplet_skipped_before_hash_and_registration(self):
        from unittest.mock import patch
        self.put("NCN/Song/0/07777.mid",midi())
        self.put("NCN/Lyrics/0/07777.lyr",
                 "ชื่อเพลง\nชื่อศิลปิน\nC\n\nทดสอบเนื้อร้อง\n".encode("cp874"))
        with patch.object(plus,"digest",side_effect=AssertionError("No SHA for skipped NCN")):
            result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["files_new"],0)
        self.assertEqual(result["skipped_ncn"],1)
        self.assertEqual(result["failures"],0)
        self.assertEqual(plus.stats(self.workspace)["songs"],0)
        with plus.connect(self.workspace) as db:
            entry=db.execute("SELECT outcome,message FROM xstage_import_items").fetchone()
        self.assertEqual(entry["outcome"],"skipped-ncn-incomplete")
        self.assertIn("CUR",entry["message"])


    def test_mirrored_ncn_folder_aliases_are_recognized(self):
        self.put("Collection/Songs/0/00321.mid",midi())
        self.put("Collection/Lyric/0/00321.lyr",
                 "เพลงหลายโฟลเดอร์\nศิลปินทดสอบ\nC\n\nNick\n".encode("cp874"))
        self.put("Collection/CUR/0/00321.CUR",
                 struct.pack("<5H",0,1,2,3,4))
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["failures"],0)
        self.assertEqual(result["lyrics_new"],1)
        self.assertEqual(plus.songs(self.workspace)[0]["title"],"เพลงหลายโฟลเดอร์")
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],1)

    def test_reimport_same_lyrics_skips_sidecar_parsing(self):
        from unittest.mock import patch
        song=self.put("NCN/Song/0/00105.mid",midi())
        self.put("NCN/Lyrics/0/00105.lyr",
                 "ชื่อเพลง\nชื่อศิลปิน\nC\n\nNick\n".encode("cp874"))
        self.put("NCN/Cursor/0/00105.cur",struct.pack("<5H",0,1,2,3,4))
        plus.import_folder(self.workspace,self.src)
        before=plus.stats(self.workspace)["lyrics"]
        with patch.object(plus,"document_for",side_effect=AssertionError("reparsed companions")):
            after=plus.import_folder(self.workspace,self.src)
        self.assertEqual(after["failures"],0)
        self.assertEqual(after["lyrics_new"],0)
        self.assertEqual(after["hash_cache_hits"],1)
        self.assertEqual(plus.stats(self.workspace)["lyrics"],before)

    def test_bad_ncn_lyric_companion_keeps_verified_media(self):
        midi_file=self.put("corrupt.mid",midi())
        self.put("corrupt.lyr",b"broken")
        self.put("corrupt.cur",b"\\x00\\x00")
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["files_new"],1)
        self.assertEqual(result["failures"],1)
        self.assertEqual(plus.stats(self.workspace)["media"],1)
        self.assertEqual(plus.stats(self.workspace)["songs"],1)
        self.assertEqual(plus.stats(self.workspace)["lyrics"],0)
        song=plus.songs(self.workspace)[0]
        with self.assertRaisesRegex(ValueError,"เนื้อร้อง"):
            plus.build_song(self.workspace,song["id"])
        with plus.connect(self.workspace) as db:
            outcome=db.execute(
                "SELECT outcome FROM xstage_import_items ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(outcome,"lyrics-error")
        issues=plus.import_issues(self.workspace)
        self.assertEqual(len(issues),1)
        self.assertEqual(issues[0]["outcome"],"lyrics-error")
        self.assertEqual(plus.stats(self.workspace)["songs_without_lyrics"],1)

    def test_import_prefers_complete_cur_over_new_incomplete_data(self):
        self.put("NCN/Song/0/08721.mid",midi())
        self.put("NCN/Lyrics/0/08721.lyr",
                 "ชื่อเพลง\nผู้ร้อง\nC\n\nNick\nAnother\n".encode("cp874"))
        cur=self.put("NCN/Cursor/0/08721.cur",struct.pack("<13H",*range(13)))
        first=plus.import_folder(self.workspace,self.src)
        self.assertEqual(first["lyrics_new"],1)
        previous=plus.songs(self.workspace)[0]
        self.assertNotEqual(previous["timing_status"],"incomplete")
        cur.write_bytes(struct.pack("<5H",0,1,2,3,4))
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["partial_lyrics"],1)
        active=plus.songs(self.workspace)[0]
        self.assertEqual(active["version_id"],previous["version_id"])
        self.assertNotEqual(active["timing_status"],"incomplete")
        with plus.connect(self.workspace) as db:
            versions=list(db.execute("SELECT id,timing_status,is_current FROM xstage_lyric_versions"))
        self.assertEqual(len(versions),2)
        self.assertEqual(len([x for x in versions if x["is_current"]]),1)
        self.assertEqual(len([x for x in versions if x["timing_status"]=="incomplete"]),1)
        self.assertTrue(plus.build_song(self.workspace,active["id"]))

    def test_repair_previous_partial_current_without_deleting_versions(self):
        self.put("NCN/Song/0/00124.mid",midi())
        self.put("NCN/Lyrics/0/00124.lyr",
                 "เพลง\nศิลปิน\nC\n\nNick\nAnother\n".encode("cp874"))
        cursor=self.put("NCN/Cursor/0/00124.cur",struct.pack("<5H",0,1,2,3,4))
        plus.import_folder(self.workspace,self.src)
        old=plus.songs(self.workspace)[0]
        self.assertEqual(old["timing_status"],"incomplete")
        cursor.write_bytes(struct.pack("<13H",*range(13)))
        plus.import_folder(self.workspace,self.src)
        ready=plus.songs(self.workspace)[0]
        self.assertNotEqual(ready["timing_status"],"incomplete")
        with plus.connect(self.workspace) as db:
            db.execute("UPDATE xstage_lyric_versions SET is_current=0 WHERE song_id=?",
                       (ready["id"],))
            db.execute("""UPDATE xstage_lyric_versions SET is_current=1
                          WHERE id=?""",(old["version_id"],))
            db.execute("DELETE FROM xstage_migrations WHERE key='plus-lyrics-quality-v1'")
        result=plus.stats(self.workspace)
        self.assertEqual(result["songs_with_lyrics"],1)
        self.assertEqual(plus.songs(self.workspace)[0]["version_id"],ready["version_id"])
        self.assertEqual(result["lyrics_versions"],2)

    def test_folder_without_song_component_finds_matching_lyr_cur(self):
        self.put("LooseCollection/0/00425.mid",midi())
        self.put("LooseCollection/Lyrics/0/00425.lyr",
                 "เพลงตัวอย่าง\nผู้ร้อง\nC\n\nNick\n".encode("cp874"))
        self.put("LooseCollection/Cursor/0/00425.cur",struct.pack("<5H",0,1,2,3,4))
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["lyrics_new"],1)
        self.assertEqual(result["failures"],0)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],1)

    def test_damaged_cur_uses_valid_lrc_in_same_song_folder(self):
        path=self.put("Song/0/00142.mid",midi())
        self.put("Lyrics/0/00142.lyr",
                 "หัวเพลง\nศิลปิน\nC\n\nNick\n".encode("cp874"))
        self.put("Cursor/0/00142.cur",b"badCUR")
        self.lrc(path,"[00:01.00]Hello\n[00:03.00]World\n")
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["failures"],0)
        self.assertEqual(result["lyrics_new"],1)
        with plus.connect(self.workspace) as db:
            record=db.execute("""SELECT origin,timing_status FROM xstage_lyric_versions
                                 WHERE is_current=1""").fetchone()
        self.assertEqual(record["origin"],"LRC")
        self.assertEqual(record["timing_status"],"estimated")
        self.assertTrue(plus.build_song(self.workspace,plus.songs(self.workspace)[0]["id"]))

    def test_repeated_import_does_not_replace_user_edited_lyrics(self):
        self.put("Song/0/00981.mid",midi())
        self.put("Lyrics/0/00981.lyr",
                 "ชื่อเพลง\nศิลปิน\nC\n\nNick\n".encode("cp874"))
        self.put("Cursor/0/00981.cur",struct.pack("<5H",0,1,2,3,4))
        plus.import_folder(self.workspace,self.src)
        group=plus.groups(self.workspace,"Nick")
        before=plus.plan_edit(self.workspace,"Nick",[group[0]["group_key"]])
        plus.replace_groups(self.workspace,"Nick",[group[0]["group_key"]],
                            "Updated lyric",before["lines"])
        edited=plus.songs(self.workspace)[0]["version_id"]
        plus.import_folder(self.workspace,self.src)
        self.assertEqual(plus.songs(self.workspace)[0]["version_id"],edited)
        with plus.connect(self.workspace) as db:
            row=db.execute("SELECT origin FROM xstage_lyric_versions WHERE id=?",
                           (edited,)).fetchone()
        self.assertEqual(row["origin"],"edit")

    def test_one_click_recovery_reads_existing_lyrics_without_media_hash(self):
        from unittest.mock import patch
        self.put("Loose/0/01681.mid",midi())
        first=plus.import_folder(self.workspace,self.src)
        self.assertEqual(first["files_new"],1)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],0)
        self.put("Loose/Lyrics/0/01681.lyr",
                 "กู้เนื้อร้อง\nนักร้อง\nC\n\nNick\n".encode("cp874"))
        self.put("Loose/Cursor/0/01681.cur",struct.pack("<5H",0,1,2,3,4))
        with patch.object(plus,"digest",side_effect=AssertionError("Media must not be rehashed")):
            repaired=plus.recover_existing_lyrics(self.workspace)
        self.assertEqual(repaired["total"],1)
        self.assertEqual(repaired["recovered_ready"],1)
        self.assertEqual(repaired["failures"],0)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],1)
        self.assertEqual(plus.stats(self.workspace)["media"],1)
        self.assertFalse((self.workspace/"SOURCE").exists())
        self.assertEqual(plus.songs(self.workspace)[0]["title"],"กู้เนื้อร้อง")

    def test_recovery_reports_disconnected_source_without_fake_lyrics(self):
        source=self.put("offline.mid",midi())
        plus.import_folder(self.workspace,self.src)
        source.unlink()
        recovery=plus.recover_existing_lyrics(self.workspace)
        self.assertEqual(recovery["missing_sources"],1)
        self.assertEqual(recovery["recovered_ready"],0)
        self.assertEqual(recovery["failures"],0)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],0)

    def test_utf8_lyr_can_align_to_original_cp874_cursor(self):
        self.put("NCN/Song/0/00888.mid",midi())
        lyric="รักเธอ"
        self.put("NCN/Lyrics/0/00888.lyr",
                 ("ชื่อเพลง\nศิลปิน\nC\n\n"+lyric+"\n").encode("utf-8-sig"))
        count=1+len(lyric.encode("cp874"))
        self.put("NCN/Cursor/0/00888.cur",
                 struct.pack("<"+"H"*count,*range(count)))
        report=plus.import_folder(self.workspace,self.src)
        self.assertEqual(report["failures"],0)
        self.assertEqual(report["lyrics_new"],1)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],1)
        song=plus.songs(self.workspace)[0]
        with plus.connect(self.workspace) as db:
            version=db.execute("SELECT id FROM xstage_lyric_versions WHERE song_id=? AND is_current=1",
                               (song["id"],)).fetchone()[0]
            lines=plus.get_version_lines(db,version)
        self.assertEqual(lines[0][0]["text"],lyric)

    def test_ncn_blank_lyric_row_consumes_cursor_when_count_matches(self):
        self.put("NCN/Song/0/00482.mid",midi())
        self.put("NCN/Lyrics/0/00482.lyr",
                 "ชื่อเพลง\nศิลปิน\nC\n\nNick\n\nNext\n".encode("cp874"))
        # 5 cues for Nick, one blank-row marker, 5 cues for Next.
        self.put("NCN/Cursor/0/00482.cur",struct.pack("<11H",*range(11)))
        report=plus.import_folder(self.workspace,self.src)
        self.assertEqual(report["failures"],0)
        self.assertEqual(report["lyrics_new"],1)
        song=plus.songs(self.workspace)[0]
        with plus.connect(self.workspace) as db:
            vid=db.execute("SELECT id FROM xstage_lyric_versions WHERE is_current=1").fetchone()[0]
            lines=plus.get_version_lines(db,vid)
        self.assertEqual(len(lines),2)
        self.assertEqual(lines[1][0]["text"],"Next")
        # Each cursor position is 1/48 second at 120 BPM and division=480.
        self.assertAlmostEqual(lines[1][0]["start_time"],7/48,places=3)

    def test_recovery_does_not_attach_lyrics_to_changed_media(self):
        from unittest.mock import patch
        song=self.put("Loose/0/00809.mid",midi())
        plus.import_folder(self.workspace,self.src)
        self.put("Loose/Lyrics/0/00809.lyr",
                 "เพลง\nศิลปิน\nC\n\nNick\n".encode("cp874"))
        self.put("Loose/Cursor/0/00809.cur",struct.pack("<5H",0,1,2,3,4))
        raw=bytearray(song.read_bytes())
        raw[-5]=raw[-5]^1
        song.write_bytes(bytes(raw))
        with patch.object(plus,"digest",side_effect=AssertionError("No media SHA in recovery")):
            repair=plus.recover_existing_lyrics(self.workspace)
        self.assertEqual(repair["recovered_ready"],0)
        self.assertEqual(repair["changed_sources"],1)
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],0)

    def test_recovery_is_not_an_extra_lyrics_version_on_rerun(self):
        self.put("Loose/0/00552.mid",midi())
        plus.import_folder(self.workspace,self.src)
        self.put("Loose/Lyrics/0/00552.lyr",
                 "ชื่อเพลง\nศิลปิน\nC\n\nNick\n".encode("cp874"))
        self.put("Loose/Cursor/0/00552.cur",struct.pack("<5H",0,1,2,3,4))
        first=plus.recover_existing_lyrics(self.workspace)
        self.assertEqual(first["recovered_ready"],1)
        before=plus.stats(self.workspace)["lyrics_versions"]
        second=plus.recover_existing_lyrics(self.workspace)
        self.assertEqual(second["total"],0)
        self.assertEqual(plus.stats(self.workspace)["lyrics_versions"],before)

    def test_audio_mirrored_lrc_yields_estimated_sweep_not_fake_original(self):
        self.put("Media/Audio/0/06710.mp3",b"MP3-DATA"*120)
        self.put("Media/LRC/0/06710.lrc",
                 "[00:01.00]First\n[00:04.00]Second\n".encode("utf-8"))
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["lyrics_new"],1)
        self.assertEqual(result["failures"],0)
        song=plus.songs(self.workspace)[0]
        self.assertEqual(song["timing_status"],"estimated")
        self.assertEqual(plus.stats(self.workspace)["songs_with_lyrics"],1)

    def test_new_sidecar_folders_are_detected_without_restarting(self):
        self.put("Collection/0/06012.mid",midi())
        result=plus.import_folder(self.workspace,self.src)
        self.assertEqual(result["lyrics_new"],0)
        self.put("Collection/Lyrics/0/06012.lyr",
                 "ชื่อเพลง\nผู้ร้อง\nC\n\nNick\n".encode("cp874"))
        self.put("Collection/Cursor/0/06012.cur",
                 struct.pack("<5H",0,1,2,3,4))
        repaired=plus.recover_existing_lyrics(self.workspace)
        self.assertEqual(repaired["recovered_ready"],1)
        self.assertEqual(plus.stats(self.workspace)["songs_with_text"],1)

    def test_all_ncn_missing_triplet_skips_without_song_id(self):
        from unittest.mock import patch
        self.put("NCN/Song/0/00798.mid",midi())
        with patch.object(plus,"digest",side_effect=AssertionError("No hash needed")):
            run=plus.import_folder(self.workspace,self.src)
        self.assertEqual(run["skipped_ncn"],1)
        self.assertEqual(run["files_new"],0)
        self.assertEqual(plus.stats(self.workspace)["songs"],0)
        with plus.connect(self.workspace) as db:
            row=db.execute("SELECT outcome,message FROM xstage_import_items").fetchone()
        self.assertEqual(row["outcome"],"skipped-ncn-incomplete")
        self.assertIn("LYR",row["message"])
        self.assertIn("CUR",row["message"])

    def test_non_ncn_audio_without_sidecars_still_registers(self):
        self.put("Music/001.mp3",b"audio"*250)
        run=plus.import_folder(self.workspace,self.src)
        self.assertEqual(run["files_new"],1)
        self.assertEqual(run["skipped_ncn"],0)
        self.assertEqual(plus.stats(self.workspace)["songs"],1)

    def test_missing_lyrics_not_claimed_as_karaoke(self):
        self.put("no-lyrics.mp3",b"audio"*200)
        plus.import_folder(self.workspace,self.src)
        item=plus.songs(self.workspace)[0]
        self.assertIsNone(item["version_id"])
        with self.assertRaisesRegex(ValueError,"เนื้อร้อง"):
            plus.build_song(self.workspace,item["id"])

    def test_missing_original_after_import_cannot_export_without_source(self):
        path=self.put("offline.mp3",b"AUDIO-TEST"*100)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        path.unlink()
        with self.assertRaisesRegex(ValueError,"ไม่พบไฟล์เพลงต้นฉบับ"):
            plus.build_song(self.workspace,song["id"])
        self.assertFalse((self.workspace/"SOURCE").exists())

    def test_build_detects_changed_source_without_clobber(self):
        path=self.put("changed.mp3",b"data"*500)
        self.lrc(path)
        plus.import_folder(self.workspace,self.src)
        song=plus.songs(self.workspace)[0]
        path.write_bytes(b"DATA"*500)
        with self.assertRaisesRegex(ValueError,"ต้นฉบับเปลี่ยน"):
            plus.build_song(self.workspace,song["id"])
        self.assertEqual(list(self.workspace.rglob("*.xmp3")),[])

    def test_sha256_changes_when_source_file_changes(self):
        path=self.put("00001.mp3",b"A"*1000)
        plus.import_folder(self.workspace,self.src)
        path.write_bytes(b"B"*1000)
        again=plus.import_folder(self.workspace,self.src)
        self.assertEqual(again["files_new"],1)
        self.assertEqual(plus.stats(self.workspace)["media"],2)

if __name__=="__main__":
    unittest.main()
