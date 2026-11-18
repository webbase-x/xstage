# X-Stage Song Studio Plus — Technical Preview v0.1.6

A new, standalone Windows-first song-production project in the existing
https://github.com/webbase-x/xstage repository. It does not replace or
modify the older X-Stage Song Studio application.

**Preview, not production.** The current Windows EXE is unsigned. Do not use
the preview on the only copy of a valuable music library. The Karaoke PC,
Web and Android players do not yet decode the new binary format.

## Seven core workflows

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
5. Pre-build audition: choose a registered song, play real audio/video
   through a local HTTP Range stream, or MIDI on the Windows MIDI Mapper.
   Preview the actual SQLite lyric cues against the sound and manually mark
   pass / timing error / needs-review. Does NOT produce an X-media file.
6. X-Media Builder: stream-copy media into a single XMID/XMP3/XM4A/XMP4
   file with embedded binary title, artist, lyrics and timing. No sidecar
   JSON or XSK is generated.
7. Evidence-only risk history: identify exact line/cue structural errors,
   separate estimated timing from confirmed problems, and keep all manual
   review outcomes attached to the reviewed lyrics version.

## Prebuild audition: listen before producing .x...

Open **ทดสอบก่อนสร้าง .x...** (menu 04). Search by title, artist or code,
select a song, then press Play. Audio/video uses the exact original registered
source via a loopback-only byte-range endpoint (no media copy). MIDI uses the
Windows MIDI Mapper through WinMM and standard tempo/time events, without
installing a separate SoundFont. If Windows has no output synthesizer, the app
reports the issue; unsupported audio/video codecs similarly report failure.

Lyrics are read from the current SQLite Lyrics Version, with real stored
per-character/syllable cue timestamps. Estimated LRC timing is labeled and
is NOT silently treated as measured data. Previews can be paused/seeked, but
seeking into the middle of a sustained MIDI note may not restore its sound:
for definitive validation, listen from the beginning of that phrase.

Only the person listening can choose **ฟังแล้วตรง**, **พบปาดผิดจริง**, or
**ยังต้องตรวจ**, optionally adding a note. Those actions enter the persistent
`xstage_swipe_reviews` history, per Song ID and Lyrics Version ID. A file
without sufficient timing may be listened to but cannot be exported by the
pre-build shortcut. This preview pane remains a source-file audition, **not** X-media container
playback. X-Media v1 output is decoded by Karaoke Web/Android v1.0.120
Build 1120 and by the current Karaoke PC compatibility source; older Karaoke
builds remain unchanged and may not understand X-Media.

**NCN import rule:** an NCN MID with missing/empty matching LYR or CUR is
skipped *before* calculating the MID SHA-256. A skip reason is recorded; no
new song or incomplete lyrics version is created. Existing legacy SQLite
records are not retroactively deleted. Standalone MIDI/KAR and audio/video
are still registered independently.

## Windows taskbar and screen fitting

The Windows application sets both its EXE icon and the native HWND small/
large icons used by taskbar and Alt+Tab. Workspace views occupy the available
window height; song lists and lyrics/risk details use numbered pages instead
of long scrollbars. Use Ctrl+Plus / Ctrl+Minus / Ctrl+0 for zoom.

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

## SHA-256 checks ONLY the primary music/media files

- The importer's **file SHA-256** is calculated solely from the original
  MID/KAR/MP3/M4A/MP4/WAV/... media file. Never SHA-256 a .LYR, .CUR or .LRC.
- Companion-file changes use source path, file size and modification timestamp
  to avoid unnecessary re-parsing. New/changed companions are decoded; the
  **already-parsed lyric content** is fingerprinted in memory only to preserve
  separate SQLite versions. This is not a second file SHA-256 scan.
- When NCN CUR runs short, save all lines with verified time positions as an
  **incomplete** version plus the complete raw LYR text as a **draft**. Neither
  becomes eligible for XMID export until timing is complete.
- When LYR exists without CUR, store the title, artist and original text
  in SQLite as a draft. Distinguish missing sidecars, incomplete time cues and
  genuine parser errors in the import report.
- Existing Song IDs, media SHA-256 records, and old lyric versions are
  retained. Import the same source folder again to retry earlier misses safely.

SHA-256 of MP3 and M4A is not an identity of the underlying musical work.
Matching titles do not prove byte-identity either. The preview never deletes
or automatically merges similar-sounding media.

## Recover lyrics for songs already registered in SQLite

Open the new Import screen and choose **"ตรวจซ่อมเนื้อร้องและเวลาปาดสี"**.
This targeted job searches saved original media locations for songs that
currently have **no complete timed lyric version**. It does not need to
recatalog the media, perform media SHA-256 again, copy songs, or create
backups. It also restores complete versions mistakenly displaced by
partial CUR versions in the earlier preview (one-time SQLite repair).

Recovery tries measured NCN MID/LYR/CUR first, then a timed LRC sidecar or
embedded MIDI/KAR lyrics. It understands flat, bucketed, and mirrored
Song(s)/Lyrics/Lyr/Cursor/Cur directories and MP3/MP4 + LRC in sibling
Lyrics folders. UTF-8 Thai LYR converted from CP874 and CUR entries for
blank lines are recognized only when byte/timing evidence supports them.

A text-only LYR is **stored and previewable** even without usable CUR.
Partially timed CUR lines are kept with an `incomplete` status, never
advertised as fully synced. LRC provides line times; interpolated per-glyph
sweeps are **estimated**, not measured. A missing/changed original source
is reported separately and never silently paired with another song.
Manual lyric edits and complete original versions are protected.

The dashboard now separates songs with *any readable lyric text*, songs
with *complete line timing*, and total historical lyric versions. Those
three quantities are intentionally not interchangeable.

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
- X-Media v1 requires Karaoke Web/Android v1.0.120 Build 1120 or a Karaoke PC build containing the current compatibility layer; older player builds remain unsupported.
- No native merge of a separate Plus SQLite file from another PC yet;
  importing source folders from many PCs is supported.
- No signed Windows installer or automatic updating yet.
- Prebuild audition uses the original media; Windows playback device and supported codecs are not guaranteed on every PC.
- Very large real-world collections need additional load testing.

## Tests

    python -m unittest discover -s songstudio-plus/tests -p "test_*.py" -v

All changes are isolated to songstudio-plus/ apart from adding the entry in
the existing app portal. Old Song Studio and Karaoke remain unchanged.
