#!/usr/bin/env python3
"""Read-only audit of X-Stage Karaoke PC source archive for MIDI/lyrics parity.

Print only bounded code excerpts from a SHA256-verified, owned source archive.
Does not import, execute or modify source files inside the archive.
"""
from __future__ import annotations
from collections import Counter
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "downloads" / "X-Stage-Karaoke-v1.0.76-Windows-Source-Continuous-Medley.zip"
EXPECTED_SHA256 = "bb9498deff94e8bf3debe48bcce32a9b5e6adb595c4c26783f8553128cdfe224"
TERMS = re.compile(r"midi|\\bkar\\b|\\bncn\\b|bass_midi|soundfont|\\bsf2\\b|fluidsynth|ffmpeg|\\bm4a\\b|\\blrc\\b|lyric|cursor|export|transcod|\\btempo\\b|karaoke", re.I)
SIGNALS = re.compile(r"def .*?(?:midi|lyric|lrc|convert|export|song|timing|tempo)|(?:midi|kar|ncn).{0,60}(?:m4a|lrc|lyric|tempo)|(?:m4a|lrc|lyric).{0,60}(?:midi|kar|ncn)|BASS_MIDI|soundfont|ffmpeg|audio_to_video|render.*audio|tempo.*tick|tick.*tempo|@T|@L|\\\\|/\\\\", re.I)
def main():
    assert ARCHIVE.is_file(), f"Missing owned source archive: {ARCHIVE}"
    with ARCHIVE.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    assert digest == EXPECTED_SHA256, "Karaoke PC source archive SHA256 mismatch"
    print(f"VERIFIED source ZIP SHA256={digest}")
    with zipfile.ZipFile(ARCHIVE) as z:
        files = [i for i in z.infolist() if i.filename.endswith(".py") and not i.is_dir()]
        print(f"ARCHIVE py_files={len(files)} total_entries={len(z.infolist())}")
        analyzed=[]
        for item in files:
            if item.file_size>750_000:
                continue
            payload = z.read(item)
            try:
                code = payload.decode("utf-8-sig")
            except UnicodeDecodeError:
                try: code = payload.decode("cp874")
                except UnicodeDecodeError: continue
            lines = code.splitlines()
            candidates = [(i+1, s.strip()) for i,s in enumerate(lines)
                          if SIGNALS.search(s) and not s.lstrip().startswith("#")]
            if candidates:
                score=sum(4 if re.search(r"(?i)(?:midi|kar|ncn).{0,60}(?:m4a|lrc|lyric)|(?:m4a|lrc|lyric).{0,60}(?:midi|kar|ncn)|BASS_MIDI|soundfont|ffmpeg", line) else 1
                          for _,line in candidates)
                analyzed.append((score,item.filename,candidates,lines))
        analyzed.sort(key=lambda entry:(-entry[0],entry[1]))
        print("TOP SOURCE MODULES BY MIDI/LYRICS/AUDIO SIGNALS:")
        for score,path,candidates,_ in analyzed[:45]:
            print(f"  {path} score={score} lines={len(candidates)}")
        print("SOURCE EXCERPTS (file:line and code):")
        budget=44_000
        for score,path,candidates,lines in analyzed[:20]:
            if budget<200: break
            out=f"=== {path} (score={score}; {len(lines)} lines) ==="
            print(out);budget-=len(out)
            picks=candidates[:40]
            for number,content in picks:
                if len(content)>220:content=content[:220]+"..."
                out=f"  {number:04d} {content}"
                print(out);budget-=len(out)
                if budget<200:break
        print("AUDIT FINISHED; read-only, no Karaoke PC code executed")
if __name__=="__main__":
    main()
