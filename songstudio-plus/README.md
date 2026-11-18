# X-Stage Song Studio Plus — Technical Preview v0.1.3

A new, standalone Windows-first song-production project in the existing
https://github.com/webbase-x/xstage repository. It does not replace or
modify the older X-Stage Song Studio application.

**Preview, not production.** The current Windows EXE is unsigned. Do not use
the preview on the only copy of a valuable music library. The Karaoke PC,
Web and Android players do not yet decode the new binary format.

## Five core workflows

1. Import: search a source folder recursively, hash original media first
   with streamed SHA-256, compare against SQLite, then locate required lyrics
   and timing companions. NCN uses MID + LYR + CUR. Other MIDI/KAR, audio,
   and video are registered without fake lyrics.
2. SQLite: all relational tables start with xstage_; Song ID, media SHA-256,
   and Lyrics Version ID are separate. Do NOT create any backup or copy of imported media.
   SQLite stores only source references, SHA-256, and metadata.
3. Lyrics Editor: search whole lyric lines, group identical complete lines,
   select any set of groups, replace full lines, retain independent timing
   per song, and undo edits. Interpolated cues are marked estimated.
4. Audio/video lyrics: attach a timed LRC file to a registered song. LRC
   provides line boundaries; per-glyph timing is estimated and clearly
   marked as such. Automatic AI transcription is NOT included in preview.
5. X-Media Builder: stream-copy media into a single XMID/XMP3/XM4A/XMP4
   file with embedded binary title, artist, lyrics and timing. No sidecar
   JSON or XSK is generated.

## Start

Python 3.11+ for the core and local API. The native Windows desktop requires
PySide6 (bundled in the Windows Preview EXE):

    python songstudio-plus/app.py --workspace "D:\XStageSongPlus"

Windows Preview EXE is built by:
https://github.com/webbase-x/xstage/actions/workflows/test-songstudio-plus.yml

The Windows EXE opens its own embedded desktop window, not Chrome or Edge.
The internal API remains loopback-only at 127.0.0.1 on a random port.
Source data is kept on the PC; no cloud upload in Plus.

## Workspace

    XStageSongPlus/
      DB/xstage_plus.sqlite3
      (no SOURCE media or backup folder created by new imports)
      MIDI/MID/XMID/0/00000001.xmid
      AUDIO/XMP3/0/00000002.xmp3
      AUDIO/XM4A/0/...
      VDO/XMP4/0/...

The integer output code comes from the destination catalog, not the source
filename. Original filenames and paths are retained in SQLite.

## Two independent SHA-256 deduplication layers

- Media: SHA-256 of exact original media bytes. Same hash means skip copying
  the media again even if filenames differ.
- Lyrics: fingerprint LYR/CUR/LRC sources and digest decoded lyric lines and
  timing. Same media with different lyrics is stored as a new version.

SHA-256 of MP3 and M4A is not an identity of the underlying musical work.
Matching titles do not prove byte-identity either. The preview never deletes
or automatically merges similar-sounding media.

## Binary X-Media format v1

This is a Plus-specific container, NOT a renamed standard MIDI/MP3.

All integer fields are unsigned little-endian:

    magic                 8 bytes ASCII XSTGPLS1
    format version        uint32 = 1
    metadata size         uint64
    original media size   uint64
    original media sha    32 raw bytes
    metadata sha          32 raw bytes
    metadata records      size-delimited binary
    media payload         unchanged source bytes

Metadata records: six length-prefixed UTF-8 strings (song ID, song code,
lyrics version ID, title, artist, overall timing status); uint32 line count;
each line: two float64 values (start/end seconds), two UTF-8 strings
(text and status), uint32 cue count; each cue: two float64 values (start and
duration) and its UTF-8 text.

There is no external JSON file. plus_core.read_xfile decodes records with
bounds checks without loading the whole audio/video into memory. Future
players must seek directly to the embedded media offset and apply a
suitable MIDI synth / audio / video decoder. A standard MP3/MIDI player
cannot open a Plus container simply by renaming it.

## Safety and recovery

- Never alters or deletes any import source.
- Never copies, backs up, moves, or deletes original media on import.
- SQLite stores verified source locations and SHA-256; files must remain accessible
  for X-media export. Re-import from a new source location to relink media.
- Earlier preview-created SOURCE copies, if present, are left untouched.
- Rejects overwriting unknown or changed X-media output.
- SQLite transactions protect edits. Undo refuses to overwrite subsequent
  edits on selected songs.
- X-media build hashes the source while copying into the final X-file and
  verifies against the stored SHA-256 in the same streaming pass.
- Failed individual inputs are logged in xstage_import_items, other files
  continue importing.
- Re-importing the same folder safely resumes through deduplication.
- Loopback-only local API and a session token protect mutations.

## Explicit limitations

- No automatic speech-to-text / vocal alignment for MP3/M4A/MP4 yet.
- No full real-time MIDI/SoundFont XMID playback engine yet.
- Karaoke PC/Web/APK do not yet support X-Media v1.
- No native merge of a separate Plus SQLite file from another PC yet;
  importing source folders from many PCs is supported.
- No signed Windows installer or automatic updating yet.
- No user-reviewed playback/lyric audition UI yet.
- Very large real-world collections need additional load testing.

## Tests

    python -m unittest discover -s songstudio-plus/tests -p "test_*.py" -v

All changes are isolated to songstudio-plus/ apart from adding the entry in
the existing app portal. Old Song Studio and Karaoke remain unchanged.
