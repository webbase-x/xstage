"""XStageWeb/DB V2 publisher tests; all Drive I/O uses mock private Drive."""
import importlib.util
import json
import struct
import tempfile
import unittest
from pathlib import Path
from test_songstudio_online_publish import FakeOnlineDrive, online

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("xstage_v2_publish",
    ROOT/"songstudio-pc"/"v2_native_publish.py")
import sys
sys.path.insert(0,str(ROOT/"songstudio-pc"))
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.drive=FakeOnlineDrive()
        self.drive.folder("root","XStageWeb")
        self.pub=native.V2NativePublisher(self.drive)
        self.pub.reader._json=lambda ident: json.loads(self.drive.items[str(ident)]["body"].decode("utf8"))
        self.write("input/audio.mp3",b"ID3"+b"X"*2500)
        self.write("input/audio.m4a",b"A"*4000)
        track=b"\\x00\\xff\\x51\\x03\\x07\\xa1\\x20\\x00\\xff\\x2f\\x00"
        midi=b"MThd"+struct.pack(">IHHH",6,0,1,480)+b"MTrk"+struct.pack(">I",len(track))+track
        self.write("input/X01.MID",midi)
        self.write("input/X01.LYR","Test Song\\nSinger\\nC\\n\\nHello\\n".encode("cp874"))
        self.write("input/X01.CUR",struct.pack("<"+"H"*6,*([0]+[i*12 for i in range(5)]))+b"\\xff")
        self.write("input/clip.avi",b"RIFF"+b"x"*2000)
        self.write("input/words.json",
                   json.dumps({"schemaVersion":1,
                               "lines":[{"text":"เพลงทดสอบ","startTime":1}]}).encode("utf8"))

    def write(self,path,data):
        p=self.root/path
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(data)
        return p

    def test_native_audio_video_midi_and_db_pointer(self):
        doc={"schemaVersion":2,"songs":[
            {"id":"A01","code":"A01","title":"Audio","sources":{
                "mp3":"input/audio.mp3","m4a":"input/audio.m4a"},
             "timedLyrics":"input/words.json"},
            {"id":"X01","code":"X01","title":"MIDI","sources":{"ncn":{
                "song":"input/X01.MID","lyrics":"input/X01.LYR","cursor":"input/X01.CUR"}}},
            {"id":"V01","code":"V01","title":"Video","sources":{"avi":"input/clip.avi"}}]}
        result=self.pub.publish(self.root,doc)
        self.assertEqual(result["totalSongs"],3)
        root=self.drive.folder("root","XStageWeb")
        db=self.drive.folder(root,"DB")
        pointer=next(f for f in self.drive.list_children(db) if f["name"]=="current.json")
        doc=self.pub.reader._json(pointer["id"])
        self.assertEqual(doc["schemaVersion"],2)
        catalog=self.pub.reader._json(doc["catalogFileId"])
        songs={x["code"]:x for x in catalog["songs"]}
        self.assertTrue(songs["A01"]["media"]["mp3"]["path"].startswith("AUDIO/MP3/Songs/A/"))
        self.assertTrue(songs["A01"]["media"]["m4a"]["path"].startswith("AUDIO/M4A/Songs/A/"))
        self.assertTrue(songs["A01"]["lyrics"]["path"].startswith("AUDIO/M4A/Lyrics/A/"))
        self.assertTrue(songs["X01"]["media"]["midi"]["path"].startswith("MIDI/NCN/Songs/X/"))
        self.assertTrue(songs["X01"]["media"]["midi"]["lyr"]["path"].startswith("MIDI/NCN/Lyrics/X/"))
        self.assertTrue(songs["X01"]["media"]["midi"]["cur"]["path"].startswith("MIDI/NCN/Cursor/X/"))
        self.assertTrue(songs["X01"]["lyrics"]["path"].startswith("MIDI/NCN/Lyrics/X/"))
        lyric=self.pub.reader._json(songs["X01"]["lyrics"]["fileId"])
        self.assertEqual(lyric["lines"][0]["text"],"Hello")
        self.assertTrue(songs["V01"]["media"]["video"]["path"].startswith("VIDEO/AVI/"))

    def test_rejects_incomplete_ncn_and_unsafe_files(self):
        bad={"schemaVersion":2,"songs":[{"code":"B","sources":{"ncn":{
            "song":"input/X01.MID","lyrics":"input/X01.LYR","cursor":"input/missing.cur"}}}]}
        with self.assertRaises(native.PublishError):
            self.pub.publish(self.root,bad)
        traversal={"schemaVersion":2,"songs":[{"code":"B","sources":{"mp3":"../escape.mp3"}}]}
        with self.assertRaises(native.PublishError):
            self.pub.publish(self.root,traversal)

    def test_rejects_duplicate_code_before_upload(self):
        row={"code":"A","sources":{"mp3":"input/audio.mp3"}}
        with self.assertRaises(native.PublishError):
            self.pub.publish(self.root,{"schemaVersion":2,"songs":[row,row]})

if __name__=="__main__":
    unittest.main()
