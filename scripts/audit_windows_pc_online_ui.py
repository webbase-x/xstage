#!/usr/bin/env python3
"""Inventory PC-only Online integration in verified source ZIP, without extracting code to the app."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/"downloads/X-Stage-Karaoke-v1.0.76-Windows-Source-Continuous-Medley.zip"
PATTERNS={
  "online-brand":re.compile(r"X[- ]Stage\s+Karaoke\s+Online|X[- ]Stage\s+Online|คาราโอเกะออนไลน์",re.I),
  "web-link":re.compile(r"webbase-x\.github\.io/xstage|github\.com/webbase-x/xstage",re.I),
  "online-api":re.compile(r"\bopen_online\b|\bonline_mode\b|\bweb_online\b|\bweb_stage\b|\bweb_app\b|open.*karaoke.*online",re.I),
  "web-protocol":re.compile(r"\bwebsocket\b|\bpeerjs\b|\bwebrtc\b|\bgoogle_drive\b|\bonline_sync\b",re.I),
}
SCAN={".py",".json",".js",".html",".css",".ini",".md",".txt",".ps1",".cmd",".bat"}
def main():
  if not ARCHIVE.is_file():raise SystemExit("Missing PC source ZIP")
  with ARCHIVE.open("rb") as f: digest=hashlib.file_digest(f,"sha256").hexdigest()
  print("Windows PC source zip size:",ARCHIVE.stat().st_size)
  print("Windows PC source SHA-256:",digest)
  with zipfile.ZipFile(ARCHIVE) as z:
    names=z.namelist()
    print("Source entries:",len(names))
    groups={}
    for member in z.infolist():
      path=Path(member.filename)
      if member.is_dir() or path.suffix.lower() not in SCAN or member.file_size>500_000:continue
      try: text=z.read(member).decode("utf-8-sig")
      except UnicodeDecodeError:
        try:text=z.read(member).decode("cp874")
        except UnicodeDecodeError:continue
      for i,line in enumerate(text.splitlines(),1):
        for key,pattern in PATTERNS.items():
          if pattern.search(line):
            groups.setdefault(key,[]).append((member.filename,i))
    for group,locs in groups.items():
      print(f"GROUP {group}: {len(locs)}")
      for path,n in locs[:80]:print(f"  {path}:{n}")
    focus={
      "karaoke/ui.py":[(1,115),(170,210),(300,425),(740,805)],
      "karaoke/context_menu.py":[(1,112)],
      "karaoke/classic.py":[(60,112)],
      "karaoke/shutdown.py":[(25,65)],
      "karaoke/google_account_ui.py":[(75,125)],
      "main.py":[(1,108)],
      "karaoke/__init__.py":[(1,130)]
    }
    for source,ranges in focus.items():
      if source not in names:continue
      try:contents=z.read(source).decode("utf-8-sig").splitlines()
      except UnicodeDecodeError:continue
      for lo,hi in ranges:
        print(f"FOCUS {source} {lo}-{hi}")
        for i in range(lo-1,min(hi,len(contents))):
          print(f"  {i+1:04d} {contents[i][:210]}")
    print("CANDIDATE UI MODULES")
    for name in names:
      if re.search(r"(?i)menu|action|toolbar|web|online|sync|settings|main\.py",name):
        print(" ",name)
if __name__=="__main__":main()
