# X-Stage Song Studio Pro — Technical Preview v0.1.37

A new, standalone Windows-first song-production project in the existing
https://github.com/webbase-x/xstage repository. It does not replace or
modify the older X-Stage Song Studio application.

**Preview, not production.** The current Windows EXE is unsigned. Do not use
the preview on the only copy of a valuable music library. The Karaoke PC,
Web and Android players do not yet decode the new binary format.


## v0.1.37 — Remove song metadata results in group lyric editor

- Removed the entire song/artist/untimed-LYR metadata result panel from
  the **Batch Lyrics Editor**, including its counts, card grid and old
  secondary API request. The editor now shows only matching current
  lyric groups for batch editing, with bounded on-scroll loading.
- This removes only the presentation and its unused client search call;
  the SQLite songs, titles, artists, drafts, lyrics and existing file
  exports are not modified or deleted.
- This release has a distinct Windows Setup version so older bundled Qt
  WebViews can receive the change through the verified auto-updater.

## v0.1.36 — Stable popup UX and safe XMID updating

- Notifications: repeated events do not flash or reset the same message,
  errors remain visible with a Close button, and confirmation dialogs refuse
  overlapping user clicks. All other native dialogs guard repeated showModal.
- Verified GitHub updates: temporary feed failures no longer remove an
  already-visible update notice. The detached Windows installer waits for the
  app to close, rejects still-open instances, writes an Inno Setup log and
  displays a persistent Windows error message when setup fails.
- Continuous SQLite searches with scroll-triggered bounded pages and visible
  row virtualization replace grouped-lyrics page buttons.
- XMID/X-Media export tabs separate unconverted, converted and needs-repair
  songs, lazy-load the lists and exclude already-converted items from the
  build queue. Source media, SQLite and original lyric revisions stay intact.
- The public v0.1.35 installer remains current until v0.1.36 Windows CI
  produces a verified Setup with SHA-256 proof.

## v0.1.35 — Observable imports and release consistency

- The running import view now displays the age of the **last real progress report**
  while separately confirming that the Local Engine responds. Long periods
  without a progress callback are not misrepresented as new files completed:
  large SHA-256 reads or SQLite stalls require investigation, not fake percentages.
- A direct **เปิด Log งานนี้** action is available beside the active import,
  without opening Settings. The local diagnostic log records sampled actual
  import counters roughly every 20 seconds and still records start/finish/errors.
- Correct the session API version (previously left at 0.1.30) to the one
  canonical desktop/updater version. Keep the installer, UI, tests and Windows
  artifact names on v0.1.35.
- Preserve existing Song IDs, lyric versions, import checkpoints, source media
  and the SQLite workspace. No automatic cleanup/migration of user data.
- The v0.1.34 public manifest stays in force until the **Windows Setup is built,
  smoke-tested and SHA-256 verified** by the publishing workflow. This is still
  an unsigned Preview and X-media player support is separate work.

## v0.1.34 — Build selection for reviewed lyrics

- Fixes Menu 06 **สร้างไฟล์ X-Stage** when songs with complete timing were shown as unselectable only because their current lyric version still needed explicit review.
- Songs with status `review` now have an active checkbox. Selecting one opens a confirmation explaining that the current lyrics/timing were edited or estimated; confirming records approval for that exact current Lyrics Version, then selects it for the build.
- **เลือกทั้งหมดหน้านี้** handles review-status songs with one explicit confirmation and approves only the visible current versions.
- Songs with missing lyrics or incomplete CUR remain blocked and cannot be built. The build panel now shows counts for ready, review, and truly blocked songs instead of silently disabling rows.
- The build backend still re-validates approved IDs before producing any X-Stage file.

## v0.1.33 — Updater normalized-target repair

- Fixes the auto-update failure **“ยังไม่มีไฟล์ Song Studio Pro ที่ยืนยันแล้ว”** that could occur after a release had already been verified.
- Root cause: the update checker returned a normalized verified snapshot (`version/url/sha256/filename`), but the downloader incorrectly passed that internal snapshot back into the public-manifest validator, which expects `name/available/download_url`.
- The downloader now reconstructs the strict manifest shape, re-runs the same official Release URL and SHA-256 checks, and also rejects a mismatched supplied filename.
- A regression test downloads from the exact normalized object returned by the checker so this bootstrap path cannot silently break again.
- **Important for v0.1.31/v0.1.32:** those already-installed builds contain the bootstrap bug, so their automatic-install button cannot repair itself. Install v0.1.33 Setup once manually; automatic updates from v0.1.33 onward use the repaired path.

## v0.1.32 — Responsive grouped lyrics editor

- “กลุ่มข้อความที่พบ” now calculates the page size from the real visible panel area instead of a fixed 4/5/6 rows.
- Page navigation uses that exact dynamic size, keeps selected groups across pages, and shows the visible range on each page.
- “ข้อความใหม่สำหรับทุกกลุ่มที่เลือก” is now a compact editable choice field with **X-Stage Karaoke** as a suggested option; users can still type any custom replacement.
- Group text is kept to one visual line with ellipsis so page sizing remains stable; the full replacement behavior and CUR timing rules are unchanged.

## v0.1.31 — Windows Program Files installer

Windows downloads are now an **Inno Setup EXE**, not a portable program.
The stable desktop EXE installs to
`C:\Program Files\X-Stage\Song Studio Pro\XStageSongStudioPro.exe`
on typical Windows x64 systems. The installer requests Windows UAC, creates
a Start Menu shortcut and uninstaller, and offers an optional desktop shortcut.
This Preview installer is currently unsigned.

The existing workspace, `DB/xstage_plus.sqlite3`, import checkpoints, original
music files and logs stay outside Program Files in their original writable
locations. Updating or uninstalling never deletes the user's database.

New in-app updates verify the published **Setup EXE** and SHA-256, checkpoint
ongoing imports, elevate the installer, and restart with the same workspace.
Old portable v0.1.30 and earlier use the original incompatible EXE-only
updater. They require a **one-time manual Setup download and installation**.

## v0.1.27 — Stability, throughput, and maintenance improvements

- Bound in-memory job history to the latest 40 completed jobs plus currently running tasks; avoid accumulation of obsolete progress and results.
- Report resumed-import throughput from newly processed files, not counters restored from earlier sessions.
- Validate explicit export selections in 400-ID SQLite chunks instead of fetching the entire ready catalog twice.
- Guard responsive Windows layout rules and UI action wiring in CI regression tests.
- Retire obsolete disabled publishing workflows; the active publisher checks the Windows artifact SHA-256 before updating the release manifest.
- Preserve song registry, lyric versions, cue positions, approved reviews, import checkpoints and original media.


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
pre-build shortcut. This is a source-file audition, **not** X-media container
playback; Karaoke PC/Web/Android have not been changed to decode X-media v1.

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

## Windows startup fix in v0.1.7

The app no longer assumes that `%USERPROFILE%\\Documents` exists.
Existing workspaces in the real Windows Documents location (including
OneDrive redirects) or the old `~/Documents/XStageSongPlus` are preferred
and are never moved or replaced. A new installation uses the writable
`%LOCALAPPDATA%\\XStageSongPlus` workspace, with roaming profile and home
directory alternatives if needed. Windows Unicode (including Thai profile
names) is supported without legacy ANSI path encoding.

Use `--workspace "D:\\XStageSongPlus"` only to select an explicit existing or
new workspace. A failed explicit path is reported in a Windows dialog rather
than silently falling back to a new empty song database.

## v0.1.8 NCN original-lyric recovery

Fixes false `partial-lyrics` on NCN MID + LYR + CUR when a trailing
**untimed decorative karaoke vendor credit** occupies the final LYR row,
while all preceding rows have measured CUR entries. The decision requires
both a recognized vendor-only footer and enough original CUR entries for
**every** preceding row. Any timed middle-of-song credits remain untouched.
A short CUR that also truncates real lyric rows still stays `incomplete`.
No cursor event times are invented.

Real-world diagnostic (private customer files, **not** committed): song
`068008138` has 59 preceding lines requiring 1,439 CUR entries, followed
by an untimed decorative vendor footer, and 1,446 CUR values (7 surplus).
The original MIDI contains 11 tracks. No real song files were copied to
this repository.

If a previous Plus import marked a song `บันทึกเนื้อร้องบางส่วน`, run
**ตรวจซ่อมเนื้อร้องและเวลาปาดสี** (Lyrics recovery), or re-import the same
original song folder, to create a complete new SQLite lyric version. The
older version and any manual edits are preserved. Inspect the actual timing
in the pre-build player before creating an XMID.

## v0.1.9 — Menu 05: ตรวจและปาดเนื้อร้อง

An additional **08-menu** layout has Menu 05 for manual karaoke correction
and moves Build to Menu 06. It supports every cataloged song, including
complete lyrics (which need no re-swipe), incomplete CUR timings, untimed LYR
drafts, and songs with no lyrics. The original media files are immutable.

- Search and filter missing/untimed, partial, awaiting confirmation, skipped,
  and all songs. Each item has an explicit state and a separately saved review.
- Play the source MIDI using the local Windows MIDI mapper, or play registered
  audio/video through byte-range loopback streaming. The karaoke display uses
  measured or explicitly entered cue start times, never interpolated onsets.
- Edit lyric text, break it into exact segments, adjust line start/end and
  per-segment starts, capture start/cue/end while listening, or paste a new
  untimed lyric draft. **Save** creates a new SQLite lyric version or partial
  draft, **Skip** records a review decision, and **Approve** authorizes the
  current fully timed version after listening. Incomplete or draft-only work
  is never tagged as ready.
- Original complete NCN files are ready without rewriting their lyrics.
  Estimated/manual timings enter the "awaiting confirmation" queue.
- Menu 06 has four selection actions: all eligible songs (whole catalog),
  only this page, clear all, and clear only this page. The bulk all-ready
  selection is a server-side catalog predicate, not an in-browser list of
  hundreds of thousands of checkboxes. Ineligible songs remain visible
  but cannot be included in export.

The preview EXE is for further testing on real Windows MIDI synthesizers;
the new binary X-container still requires a compatible karaoke player.


## v0.1.10 — Focus workspace and evidence-led corrections

Menu 05 is now editor-first at standard Windows resolutions. Four immediate
layout controls let the user hide the primary sidebar, hide the song queue,
expand/collapse the karaoke display, or enter a full-width edit focus mode.
This only changes UI layout, not playback/source state. Escape exits focus.

The scrolling middle area holds a compact evidence panel and one expanded
lyric line at a time; the other lines remain visible as collapsed navigation
rows. Playback, seek, and Save / Skip / Approve remain outside the lyric
scroller. A short-window layout preserves the controls; the list is scrollable
inside the editor instead of pushing Save below the window.

Detected findings display **observed issue, affected line and suggested
manual next step**, with a click-to-edit action, and are organized as:
- Structural mismatch (cue text differs from lyrics, invalid or reversed
  timestamps, overlap, cue duration beyond the line)
- Missing information (no lyrics, missing line times, missing/partial cues,
  incomplete source CUR)
- Unverified timing (estimates requiring listening, **not** proof of error)

No lyric correction or timing is invented automatically. The backend also
reuses the existing evidence-based xstage_swipe analyzer for saved versions.
As the user edits, the UI refreshes the visible checks without silently
saving. Ctrl+S saves; leaving a dirty manual editor requires confirmation.
Manual timing approval requires saving and listening to the current version.


## Start

Python 3.11+ for the core and local API. The native Windows desktop requires
PySide6 (bundled in the Windows Preview EXE):

    python songstudio-plus/app.py --workspace "D:\XStageSongPlus"

Windows Preview EXE is built by:
https://github.com/webbase-x/xstage/actions/workflows/test-songstudio-pro.yml

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
- Karaoke PC/Web/APK do not yet support X-Media v1.
- No native merge of a separate Plus SQLite file from another PC yet;
  importing source folders from many PCs is supported.
- No signed Windows installer or automatic updating yet.
- Prebuild audition uses the original media; Windows playback device and supported codecs are not guaranteed on every PC.
- Very large real-world collections need additional load testing.

## Tests

    python -m unittest discover -s songstudio-plus/tests -p "test_*.py" -v

All changes are isolated to songstudio-plus/ apart from adding the entry in
the existing app portal. Old Song Studio and Karaoke remain unchanged.

## Pro v0.1.11 · Unified application

Only Pro is publicly listed. Old PC and Web applications have been retired from the app catalog and dedicated automatic builds. The existing internal `songstudio-plus` code path and `%LOCALAPPDATA%/XStageSongPlus` workspace are intentionally retained for **database backward compatibility**, not as separate applications. Pro never deletes media or old SQLite versions. The new cue editor shows clickable timed segments, captures real current playback positions, provides a one-step cue-timing undo, and hides raw numeric comma-separated times under an advanced disclosure.

## v0.1.13 · Batch lyric replacement fix

Menu 02 no longer rejects a whole batch simply because one NCN lyric line has mismatched or absent CUR cues. It preserves the corrected lyric text and each line's original boundaries, records the resulting version as **incomplete** when measured cue segments cannot be safely matched, and routes those lines to Menu 05 for manual timing. Group edits containing many thousands of lines run as a progress-reported, cancellable SQLite transaction. Cancel/failure rolls back the entire group; a completed batch retains Undo. The embedded frontend now serves `timeline-core.js` and `timeline-ui.js` as local scripts for Menu 05.

## Pro · Align corrected group lyrics to recorded CUR slots

When replacing a lyric line in Menu 02, existing recorded CUR onsets are preserved without interpolation. If the corrected visible lyric has fewer grapheme units than measured cursor slots, the unused slots receive internal silent `>` padding, exactly one for each spare slot. The human-readable SQLite lyric text is **not padded**. Karaoke preview and manual editor omit the extra slots; X-media retains all original onset timestamps but exports those unused slot texts as empty strings, not visible > characters. If the new visible lyric is longer than the number of measured onsets, adjacent graphemes share each original cursor event (combined sweep / ปาดควบ). All remapped rows stay `estimated`, meaning listening verification is still required. If no valid monotonic cursor positions exist, the row remains `incomplete` and is sent to Menu 05 for timing by listening. Original NCN and prior SQLite Lyrics Versions are immutable, and the committed batch remains undoable.

## Pro v0.1.14 · Restore recorded CUR without inventing onset times

Menu 02 batch replacements now map corrected visible lyrics onto the ORIGINAL recorded cursor slots, even if the prior NCN cue text has a structural mismatch. If the corrected line is shorter than the number of recorded onset slots, exactly one silent trailing `>` is added internally for each surplus slot (the visible lyrics/search text does NOT gain extra characters). If the corrected line is longer, contiguous grapheme groups (including Thai combining marks with their base) share the existing onset slots, known as ปาดควบ. No additional time is interpolated. Original line start/end and all source CUR onsets remain unchanged. Both mapping modes are `estimated` and require review by listening in Menu 05. Truly missing or invalid timing stays `incomplete`. The visible lyric editor, preview, and risk audit ignore generated silent `>` slots, while the X container preserves all onsets but writes zero-length display text for silent slots. The results screen reports padded slots and combined-sweep rows.

## v0.1.15 — Native Windows folder/file selection and action audits

Menu 01 chooses folders using a queued Qt `QFileDialog` on the main GUI thread rather than creating `tkinter.Tk()` inside the loopback HTTP worker. Menu 03 uses the same native picker for `.lrc` files. Unicode/Thai paths are passed as Python Unicode strings without shell encoding; cancelling leaves the original input untouched. The UI also has explicit actions to open the source folder and SQLite workspace in Windows Explorer, validates missing drives/folders, and shows actionable errors. Browser-only mode (without the Qt shell) retains manual path input and tells the user why native dialogs are unavailable. Automated tests cover authenticated loopback picker/API access, all 79 visible button IDs, core action wiring, and Windows Qt's queued signal delivery from an HTTP worker to the GUI thread. Existing SQLite and audio/lyric files remain untouched.

## v0.1.23 — SQLite import health and safe maintenance

- The media registry continues to enforce UNIQUE SHA-256 and the lyric version registry keeps UNIQUE(song ID, lyric content SHA-256). Reimporting the same source does not create duplicate Song IDs or identical lyric versions.
- A completed import discards only its now-unnecessary restart checkpoints and success records after persistent batch counters are committed. Cancelled/interrupted jobs still retain all checkpoints for safe resume. Every actionable error/incomplete-lyrics record remains available.
- The Import view has a new SQLite inspection panel showing database/WAL bytes, free reusable pages, song/media/source/lyric counts, import report rows and resume jobs.
- Explicit cleanup keeps issue details for the latest four completed batches and removes outdated *completed-only* report rows. It never touches incomplete, cancelled or interrupted batches, original media, lyric revisions, song catalog or export history.
- Explicit VACUUM optionally returns internal free pages to the filesystem. It is never automatic and requires at least twice the SQLite size in additional free disk space. For large libraries, close the app and make a verified SQLite backup before running cleanup or compaction.
- The Windows v0.1.23 release pipeline packages the preview EXE together with SHA-256 evidence, and the publisher verifies both before changing the public release manifest.

## v0.1.25 — Responsive Windows dashboard without overlapping controls

- The Import screen no longer squeezes all database, recovery, update and diagnostics controls into a fixed-height view; sections retain their natural height and become keyboard/wheel-scrollable without drawing a desktop scrollbar.
- Responsive header actions wrap at narrower Windows widths and preserve the workspace buttons.
- The sidebar menu can scroll internally when the window is too short, avoiding clipped menu items while preserving all eight workflows.
- Verified Windows Preview must be rebuilt and published before already-installed versions can receive the UI fix.


## v0.1.24 — Full SQLite storage audit and selective cleanup

- In the Import screen, **วิเคราะห์ทุกตารางและดัชนี** calculates real table/index page sizes via SQLite `dbstat`, runs a bounded `PRAGMA quick_check(1)` and categorizes each table as essential, temporary, cache, derived or unknown. Unknown tables are reported but **never deleted**.
- Import source paths and exact media SHA-256 registry are preserved. Completed import resume counters now disappear automatically; interrupted/cancelled checkpoints remain available. A successful lyric recovery no longer creates redundant per-song import logs.
- User-initiated **ล้างประวัติงานเสร็จแล้ว** trims disposable import rows, completed-only resume records, orphan lyric scan caches, the old unused `xstage_lyric_source` index, and detailed findings from completed swipe audits older than the two most recent. Audit run summaries and *every human review* remain. All song/media/source, lyric text/cues/versions, drafts, exports, manual edit/undo history and incomplete import jobs remain.
- Database filename size alone is not proof of duplicate songs: large `xstage_lyric_cues` and `xstage_lyric_search` indexes may be essential. Only an in-app table-space report from the user's actual SQLite identifies which data consume the space.
- Explicit **คืนพื้นที่ไฟล์ SQLite** invokes guarded `VACUUM` separately with a disk-space precondition (at least 2 times database bytes free); cleanup alone frees pages internally but may not shrink the .sqlite3 file. Make a verified copy while the app is closed before applying maintenance to valuable databases.

## v0.1.26 — Latest-only verified updater and no-flash controls

- Updating from ANY older X-Stage Song Studio Pro version jumps directly to the highest published/verified release. The update button rechecks the feed at click time; it never downloads intermediate versions.
- To avoid stale GitHub Pages CDN metadata, the updater reads both the public Pages feed and the same repository's GitHub raw feed. Each candidate is constrained to the official X-Stage Song Studio Pro Release URL and a 64-digit SHA-256.
- Windows standalone EXE downloads now retain a version+checksum-bound `.partial` file, resume using validated HTTP Content-Range, retry transient network errors, and verify the COMPLETE file before renaming/installation. Interrupted transfers are NEVER executable.
- On HTTP 403/404/network failures, the interface displays the underlying reason in the job status/log and provides **ดาวน์โหลด EXE โดยตรง** to open the official GitHub Release as a manual fallback.
- Repeated job polling no longer writes unchanged DOM text or forces identical job redraws. Navigation click animation, button hover movement and pulsing progress opacity are disabled to prevent Qt WebEngine flicker while preserving accessible keyboard-focus outlines.
- Existing song SQLite and source media remain untouched by the updater. The Windows preview EXE is not code-signed.

## v0.1.28 — Resolve false 'no verified EXE' and stuck update buttons

- Root cause: the first `/api/update/check` correctly found a published release, but `/api/update/download` independently re-fetched transient Pages/raw metadata and could receive `available=false`. Downloads failed at **zero bytes** despite a verified GitHub EXE already existing.
- The desktop engine now caches the server-verified release target and uses **exactly that version, Release URL, and SHA-256** for the update job; no second manifest request is made on download. Brief check failures may reuse the last successful verification within the same process.
- Verification prefers the GitHub Releases API's actual uploaded EXE asset and its server-reported `sha256:` digest, falling back to the two official manifests only if the API fails. It does not advertise an unpublished preview from a stale manifest.
- Failed downloads/installer attempts restore all update and banner buttons, show the real cause, and offer an official direct-EXE download. A 0-byte job displays 0%, not an invented progress percentage.
- Safe resumed partial downloads, full SHA-256 checks, unchanged SQLite library, and direct update from any previous version are retained. The Windows Preview EXE remains unsigned.

## v0.1.29 — Settings updates and clearer lyric search

- **ตั้งค่า → อัปเดตโปรแกรม** now exposes the existing verified GitHub Release version check, latest-version install and direct EXE link. It mirrors update state and download progress. The old entry in Import remains available.
- **แก้ไขเนื้อร้อง → ค้นหา** searches editable CURRENT timed lyric lines as before, but now also displays separate informational results for song titles, artists, original song codes and untimed LYR drafts. Metadata/drafts are NEVER selectable as bulk replacement targets.
- To reduce large-database I/O, lyric-group queries scan the already-existing covering `xstage_lyric_search` index and only load display text for returned groups. No new FTS/trigram tables or expensive mass reindex migration.
- The search view explicitly indicates pending work, no-match cases, and timeouts instead of claiming a failed query means there are no lyrics. Requests have a bounded 90-second timeout for large local SQLite libraries, and prior responses cannot overwrite a newer query.
- Search still requires the exact phrase to be present in current lyric text for bulk editing. A title-only match (e.g. "karaoke" in a song name) can be viewed but cannot change lyric lines. All original song media and SQLite history are preserved.

## v0.1.30 — Windows display auto-fit (no clipped controls)

- The desktop launcher no longer forces Qt WebEngine to 120% at all sizes. It measures the available Windows *client-area logical pixels* (works with HiDPI scaling) and automatically selects a readable zoom that fits the current desktop window. For example, a maximized 1366×768 screen uses about 80% rather than 120%; large 4K screens can still use up to 120%.
- Maximizing, restoring, or resizing recalculates the fit without reloading the web page or interrupting any SQLite import/job. Ctrl+Plus/Minus are intentional manual overrides; **Ctrl+0 restores automatic fit**. Small laptop taskbar work areas no longer inherit an oversized fixed minimum window.
- Main window, toolbars, search fields, panels, dialogs, lyric-group editor and both import/other views are constrained to the actual screen width. Long panels and views scroll **inside** their workspace (scrollbar chrome stays hidden); buttons and results are not clipped at the bottom or outside the right edge.
- No changes to media import, song registry, saved lyrics, SQLite revisions or user audit results. The preview EXE remains unsigned. Test coverage includes laptop 1366×768, compact window, Full HD, 4K, resize, and layout containment contracts.
