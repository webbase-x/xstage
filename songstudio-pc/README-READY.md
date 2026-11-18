## Build 369 — Multi-PC XStageSong incremental import

- MIDI to .XSK และ MIDI to Lyrics JSON ลงทะเบียนเพลงใน `XStageSong/DB/song-registry.sqlite3` ที่เก็บรหัสเพลงคงที่และ SHA-256 แยกจากเลขเพลงในไฟล์
- โอนโฟลเดอร์ `XStageSong` จากเครื่องอื่นหรือ USB เข้าสู่ Song Studio PC ได้โดยเลือกต้นทางในเมนูนำเข้า Karaoke PC หรือเผยแพร่ไป Google Drive สำหรับ Karaoke Web/APK
- ตัวกรองใหม่: เพลงใหม่, เพลงเดียวกันคนละสกุล, เวอร์ชันแก้ไข, เพลงซ้ำ; รายการชื่อ/รหัสชนที่ยังไม่ยืนยันจะไม่เขียนทับอัตโนมัติ
- ปลายทาง PC อัปเดต SQLite เดิมและ `DB/songs-portable.json`; Drive เผยแพร่ Catalog แบบ File ID และรู้จัก XSK2 ที่มี Lyrics JSON ภายในไฟล์เดียว
- บันทึกประวัตินำเข้าและรายการซ้ำข้ามครั้งสำหรับทบทวน; การย้ายหรือลบไฟล์จริงยังต้องผ่านเมนูตรวจเพลงซ้ำพร้อมการยืนยันและตรวจ SHA-256
- รักษาไฟล์เพลงและเนื้อร้องต้นฉบับทั้งหมด ไม่มีการลบไฟล์ซ้ำอัตโนมัติ; เมื่อไม่มีอินเทอร์เน็ตสามารถสร้างเพลงและฐานท้องถิ่นก่อนเผยแพร่ทีหลัง
- เครื่องต้นทาง/ปลายทางสามารถใช้เลขเพลงเดียวกันกับเพลงคนละเรื่องได้: รหัสปลายทางจัดใหม่เฉพาะขณะนำเข้าโดยไม่แก้ต้นทาง

## Build 368 — MIDI to Lyrics JSON: Resume รุ่นเก่าและทบทวน ERR

- เปิดคลัง XStageSong เดิมแล้วสร้างต่อทันที: อ้างอิง Catalog ที่ตรวจสอบได้ของ Build ก่อนหน้า, ใช้ hash ต้นฉบับยืนยันก่อนข้ามและไม่สร้างเพลงที่มีอยู่แล้วซ้ำ
- เก็บประวัติผลสำเร็จ/ข้ามซ้ำ/ข้อผิดพลาดที่ `XStageSong/DB/json-pro-review.sqlite3` อย่างถาวร (ไม่ผูกกับตัวติดตั้ง Windows); ปิดโปรแกรมหรืออัปเดต PC Ready แล้วผลลัพธ์เดิมยังอยู่
- รายการที่เคยผ่านแล้วใช้ fingerprint ของไฟล์ประกอบและสถานะ Catalog เพื่อข้ามอย่างรวดเร็ว; ต้นทางแก้ไขจะตรวจและสร้างเอกสารใหม่โดยไม่เขียนทับรุ่นเก่า
- หน้า MIDI to Lyrics JSON มี “สร้างต่อจากคลังเดิม”, “ทบทวนไฟล์ที่ข้าม / ERR / ผิดพลาด” พร้อมตัวกรองและแบ่งหน้า, และ “ลองใหม่เฉพาะ ERR”
- ลองใหม่เฉพาะ ERR อ่านคิวที่บันทึกไว้โดยตรง ไม่เดินสแกนเพลงสำเร็จหลายหมื่นรายการ; ERR ที่แก้ไขสำเร็จจะอัปเดตสถานะเป็น completed
- รุ่นเก่าบันทึกเพียง 50 สาเหตุแรก: ต้องสั่ง “สร้างต่อจากคลังเดิม” ครั้งแรกเพื่อจัดทำรายการ ERR เก่าผ่านการเทียบ Catalog; หลังจากนั้นคิว ERR คงอยู่
- เก็บ MIDI, LYR, CUR และ JSON ต้นฉบับเดิมไว้; ไม่แต่งเวลาเนื้อร้องขึ้นเองเมื่อไฟล์ไม่รองรับหรือผิดรูปแบบ
- ตัวอ่าน NCN legacy รู้จัก header NCN1 และ MThd แต่ยังตรวจโครงสร้าง track และเวลา MIDI อย่างเคร่งครัด
- รายการผิดพลาดจากระบบไฟล์จะลองใหม่ในรอบถัดไป ส่วนข้อผิดพลาดรูปแบบเพลงรอการทบทวนแบบตั้งใจ เพื่อไม่เสียเวลาวนซ้ำ
- ทดสอบการอัปเกรดจาก Catalog รุ่นเก่า, การหยุดระหว่างเขียน, ประวัติข้อผิดพลาดข้ามรอบ, และการลองใหม่เฉพาะ ERR ใน Windows CI ก่อนเผยแพร่

## Build 366 — Setup EXE และไอคอน Windows Taskbar

- เพิ่ม Setup.exe พร้อม runtime สำหรับติดตั้งแบบออฟไลน์ สร้างทางลัด Desktop/Start Menu พร้อมไอคอน และตรวจติดตั้งจริงใน Windows CI
- กำหนด AppUserModelID ให้โปรเซสหน้าต่างก่อนเปิด Qt และกำหนดไอคอนให้หน้าต่างโดยตรง
- ฝังไอคอนในตัวเปิด EXE และใช้ EXE สำหรับทางลัด Desktop รวมถึงทางลัดที่ย้ายหลังอัปเดต
- หน้าเว็บ Song Studio ไม่พาไป GitHub Releases เมื่อยังไม่มีไฟล์พร้อมดาวน์โหลด
- ต้องตรวจ Taskbar บน Windows จริงหลังติดตั้งรุ่นนี้; การทดสอบบน Linux ไม่ยืนยันภาพบน Taskbar

## Build 365 — เก็บชื่อเพลงและศิลปินให้ตรงกันสำหรับ Karaoke ทุกแพลตฟอร์ม

- MIDI to Lyrics JSON อ่านชื่อเพลง/ศิลปินจริงจาก Lyrics JSON, NCN LYR, KAR metadata และหัว LRC [ti:]/[ar:] แล้วบันทึกลง top-level title/artist ของ Lyrics JSON พร้อมกับ Song Studio Catalog
- ส่งต่อชื่อเดียวกันผ่าน PC portable catalog/SQLite และการเผยแพร่คลังออนไลน์สำหรับ Web/Android APK โดยไม่ใช้รหัสเพลงหรือชื่อโปรแกรมแทนข้อมูลจริง
- การสร้างเพลงแบบเดิมใน Song Studio รักษาชื่อที่ผู้ใช้แก้ไขไว้ก่อน และย้าย metadata ของเนื้อร้องเข้าสู่ JSON/Catalog
- Karaoke PC อ่านชื่อเพลง/ศิลปินจาก .MID/.KAR + .JSON ที่มีรหัสตรงกัน และยังคงให้ข้อมูลจาก XSK ปิดผนึกมีลำดับความสำคัญสูงสุด
- หากต้นฉบับไม่มีข้อมูลชื่อเพลง/ศิลปินจริง ระบบจะแสดงว่าไม่ระบุ ไม่แต่งชื่อหรือศิลปินขึ้นเอง
- เพิ่ม regression tests สำหรับชื่อภาษาไทยจาก LRC, NCN, JSON, การส่งออกฐาน Karaoke PC, ข้อมูลแก้ไขของผู้ใช้ และ MIDI + JSON
- ชื่อที่ถูกส่งออกผิดไปก่อนหน้านี้จะไม่ถูกแก้ทับอัตโนมัติในฐานเพลงเดิม; ให้สร้าง/นำเข้าหรือเผยแพร่ Catalog ที่แก้ไขแล้วใหม่

## Build 364 — MIDI to Lyrics JSON: สร้างต่อเนื่องและยกเลิกข้อจำกัดตามฮาร์ดแวร์

- ยกเลิกการปฏิเสธงานเพราะ CPU ใช้งานสูง, RAM เหลือน้อย และจำนวนคอร์ CPU; ยังป้องกันงานเขียนคลังเดียวกันชนกันและการติดตั้งอัปเดตพร้อมงานอื่น
- MIDI to Lyrics JSON เผยแพร่ Catalog เป็นระยะ (ทุก 1,024 เพลงหรือ 60 วินาทีของการประมวลผล) เพื่อให้ไฟล์ที่สำเร็จแล้วใช้ได้ก่อนจบทั้งชุด
- เมื่อยกเลิกงานหรือสแกนผิดพลาด จะพยายามบันทึกงานที่สำเร็จแล้วลง Catalog; งานเดิมที่ทำสำเร็จใช้ต่อได้โดยไม่เขียนทับ
- คำนวณ SHA-256 ระหว่างคัดลอกแทนการอ่านปลายทางซ้ำ; สำหรับ MIDI ดนตรีล้วนที่ไม่มีเหตุการณ์คำร้อง จะข้ามการแยกอ่าน Note/Event โดยละเอียด
- แสดงจำนวนไฟล์ที่ค้นหา จำนวนเพลงที่สร้าง ข้ามซ้ำ และเหตุผลที่ไม่สำเร็จบนหน้า MIDI to Lyrics JSON
- การยกเลิกข้อจำกัดฮาร์ดแวร์ไม่ใช่การยกเลิก License Pro; โหมด Pro ยังคงใช้สิทธิ์ตามเดิม
- ผลจาก MIDI ที่ไม่มีข้อมูลคำร้องพร้อมเวลาจริงยังต้องใช้แหล่ง Lyrics/LYR+CUR, LRC/JSON หรือคำร้องที่ฝังอยู่ในไฟล์; ไม่สร้างเวลาปลอม
- ตรวจสอบการทดสอบ GitHub Actions ของ Build 364 และไฟล์ ZIP ที่เผยแพร่ก่อนแจ้งว่าใช้งานจริงได้ครบ

## Build 363 — ตรวจเพลงซ้ำ: จัดการไฟล์เพลงและไฟล์ประกอบเป็นชุด

- The first menu now supports **two separate review modes**: **SHA-256 exact bytes** (truly identical media files) and **same filename code** (manual candidates only). Same-code items can be different songs or encodings; do not treat them as proven duplicates. Same-code mode requires the user to check and affirm musical identity, and has no mass-select action.
- Set **preferred file type to keep** (.XSK, .MID, .KAR, .MP3, .M4A, .MP4, etc.) or choose a **keeper radio** for each duplicate group. A previous "original" can be moved/recycled only after another file is selected to remain.
- Per-song **companion sidecars** are discovered from exact matching filename stems (.json, .lrc, .lyr, .cur), including supported sibling SONG/LYR/CUR and SONG/LYRICS directory layouts. They are **not** part of media duplicate detection. A companion shared with another retained media is protected, not removed.
- Before any destructive action, the local PC Engine generates a complete **plan preview**: keeper paths and types, all media and sidecars to change, skipped shared files, operation and selected destination. A fresh per-preview ID is required for confirmation.
- **Move** uses an independently chosen folder outside the original scan tree. All files from the same song are staged, SHA-256 verified and stored with source-relative directory paths and original basenames; destination collisions fail closed, never overwrite or rename a companion.
- **Delete** sends the selected media and companions to the **Windows Recycle Bin**, never intentionally permanently deletes, and refuses unsupported drives. The live `XStageSong` catalog remains protected. One kept media file per duplicate group is mandatory.
- No automatic deletion, no Google Drive deletion, and no name-only match is ever auto-acted on. The user must explicitly select affected songs and approve the preview.
- Tested: NCN MID+LYR+CUR moves, audio+JSON trash, keeper replacement, type preference, stale preview token, shared-sidecar preservation, Windows native Qt bundle, and UI contracts.

## Build 362 — ตรวจเพลงซ้ำ (menu 1)

- The first Song Studio PC menu is **ตรวจเพลงซ้ำ**. Select any local source folder, including nested MIDI, KAR, XSK, audio, and video. It scans **media only**; JSON/LRC/LYR/CUR, SoundFonts and databases are never mistaken for songs.
- An exact duplicate means **byte-identical file content**, verified by file size, a fast head/tail sample, then full-file SHA-256. Equal song names/codes are not sufficient; the same recording in different encodings is not claimed to be an identical file.
- Results are grouped with an explicit protected keeper, full paths, file sizes, and SHA digest. Browse groups, select up to 300 duplicate copies per confirmed action, and choose **move** (copy+SHA-256+source remove) or **send to Windows Recycle Bin** (never permanent deletion).
- Actual deletion/move is never automatic. The action requires a confirmation, a fresh SHA-256 comparison for both original and selected copy, and retains at least one source copy. Changed/stale files, symlinks and the active `XStageSong` library are protected.
- A move destination must be outside the scan tree. Originals and all associated lyrics/catalog files are left untouched. Operations are restricted to the local PC Engine; no Google Drive deletion.
- All previous MIDI to .XSK, MIDI to Lyrics JSON, Lyrics AI, editor, import/export, and download workflows remain as separate menus in their former order, shifted down by one.
- NOTE: This menu identifies byte-identical files, **not acoustic duplicates after MP3/M4A transcoding**. Do not move/delete tracks that are actively referenced by other playlists or external databases without updating those references.

## Build 361 — Fast workflows, no forced full-library JSON scan

- **MIDI to Lyrics JSON** now enumerates source media lazily by filename code; a compatible song begins converting as soon as it is discovered instead of waiting for every directory/group to be scanned.
- `00001.mid + 00001.lyr + 00001.cur` is paired from existing source files, including common `SONG/LYR/CUR` sibling folders. No source `.json` is required; lyrics and cue timing are validated at conversion.
- Existing MIDI/KAR embedded cues, local LRC and already-authored media+JSON are still supported as optional source formats.
- The redundant "inspect every subfolder" control and backend endpoint are removed from JSON creation; no extra scan is triggered. Other import/upload/catalog validations stay available when needed.
- Displays discovered, created, duplicate and error counts without inventing a denominator before discovery completes.
- Native Qt desktop (from Build 360), bundled Python/FFmpeg/AI, deduplication, journal/resume, no overwrite and catalog format remain unchanged.
- Workflow audit: `docs/songstudio-pc-workflow-audit-build361.md`.

## MIDI to .XSK automatic pipeline (candidate)

- Choose the source MIDI folder, XSK output folder, and song-code format/length. The default XSK mode no longer requires a completed catalog scan or manual song selection.
- Discovery walks nested folders incrementally without loading an entire directory. The first folder's MIDI files are queued immediately; a bounded producer (32 songs/batch, four batches waiting) scans ahead while the XSK2 ZIP builder processes previous items.
- Newly created XSK2 packages are unencrypted portable ZIP bundles containing the original MIDI/KAR and timed Lyrics JSON. SHA-256, original MIDI bytes and atomic no-overwrite are preserved. Previously encrypted XSK1 files remain untouched; they are not counted as portable XSK2 outputs. Song title and artist must be real metadata, otherwise the item is skipped and reported.
- Display scanned, found, converted, duplicate, incomplete and error counts. An overall percentage is shown only after full enumeration; errors accessing subfolders fail the job rather than silently omitting songs.
- The existing Pro legacy media-export wizard is not altered. Automated tests and Windows release verification must pass before claiming the next ZIP is ready.

## Release features for Build 349

- MIDI to .XSK selects the source, independent output folder, and code length using the existing dedup/packaging format.
- Lyrics AI can reread media tags and paired timed JSON; export reviewed LRC and optionally an unchanged source or transcoded audio.
- Pro Lyrics JSON can publish a separate local audio+lyrics catalog with journaling, duplicate detection, and format choices.
- Lyrics JSON grouped editing, Online/PC import, Drive catalog publishing, backup and downloads continue using their established implementations.
- All changes remain subject to automated Windows and browser testing. A source commit is not proof that the Ready ZIP was built or that Google Drive sign-in is working on a user's machine.

# X-Stage Song Studio PC Ready v0.3.49 Build 349

**Windows 10/11 x64 · portable · no installers / no download-on-first-run**

This is the new bundled distribution of the existing `songstudio-pc` preview engine. It is **not** a recovered copy of the original v0.2.5 Build 205. We keep both in the same repository but explicitly differentiate the available features.

## Release metadata

- Verified PC Ready ZIP pointer: `downloads/song-studio-latest.json`. It changes to Build 349 **only after** the Windows workflow passes its offline tests, the Release uploads successfully, and the checksum is verified. Until then use the version advertised in that file.
- Legacy Source Preview: `downloads/song-studio-source-preview-latest.json` (v0.2.8 Build 208, not a ready installer).
- Verify the published ZIP checksum with the matching GitHub Release `.zip.sha256` asset or the `sha256` field in `downloads/song-studio-latest.json` (after the release is published). Do not use hashes from older builds. This is **not** a signed EXE or MSI installer.
- Both the Source Preview launcher and CI Ready builder pin Python 3.13.10's official SHA-256 before extracting any Python archive.

## Open from Windows

1. Download **X-Stage-Song-Studio-PC-Ready-v0.3.49-build349.zip** **only after it appears as a verified asset** on the GitHub Releases page; do not mistake the Source Preview ZIP for the fully bundled Ready ZIP.
2. Extract the **entire ZIP archive** into a folder. Do not launch the CMD directly inside the ZIP preview.
3. Double-click **Start-Song-Studio.cmd**.
4. The Windows folder picker and SoundFont file picker open visibly in the foreground, including Thai-language folder names. No external tools are required.
5. The launcher checks that the bundled Python, FFmpeg, FluidSynth, SoundFont and HTDemucs AI libraries/model are intact, using SHA-256 checksums, without downloading anything.
6. The local engine opens the PC app interface in Edge app-style mode (or in your default browser if Edge isn't present). Work with files on this computer.
7. You may change input/output folders. The chosen paths persist across new ZIP releases under Windows `%LOCALAPPDATA%\\X-Stage\\SongStudio\\preferences.json`.
8. For a custom X-Stage Song Studio **Windows desktop shortcut icon**, run `Create-Desktop-Shortcut.cmd` in the extracted folder (optional).

### Included components

- Python 3.13.10 **embedded**, runs from `.runtime/python` (no system Python or pip installation)
- FFmpeg and ffprobe **executables**, `.runtime/tools`
- FluidSynth and the DLLs it requires, `.runtime/fluidsynth/bin`
- Default GeneralUser GS `.sf2` SoundFont, NumPy, ONNX Runtime CPU and HTDemucs ONNX model (~166 MB), `.runtime/soundfonts`
- PC engine `engine.py`, redesigned Pro PC/Web UI (`studio/pro-design.css`), XSK creation module (`created_xsk_export.py`), runtime manifest and third-party notices
- New X-Stage Song Studio `studio/app-icon.svg` favicon, pre-rendered `studio/app-icon-512.png` and Windows `studio/app-icon.ico` with all icon sizes, included in Ready ZIP

All listed components are downloaded and verified **on the GitHub Actions Windows build runner**, not on the user's PC. The build additionally runs the bundled Ready launcher with `-NoLaunch` to verify that it can initialize without installing or downloading dependencies. `Start-Song-Studio.cmd` never calls `Invoke-WebRequest` or installs software.

### Pro XSK from previously created songs

- Open **สร้าง .XSK · Pro** after activating a valid Pro License Key under **ตั้งค่า → License & Pro**.
- Choose MIDI/KAR + already generated, timed Lyrics JSON from the local catalog, select the XSK output folder, and create in batches of up to 100.
- Compare MIDI content by SHA-256; skip identical tracks even when filenames differ. When different content collides with an XSK code, allocate an available numeric code before appending a new one.
- Leave both source media and source JSON unmodified. Do not overwrite pre-existing XSK files. Keep legacy encrypted XSK1 under its old filename and allocate a separate code for a new XSK2; unreadable/corrupt XSK2 still fails closed.
- XSK2 requires no encryption keys. Per-user Pro licenses are not pre-activated in a public ZIP. The user must supply a valid individual Pro license; Google Drive requires network access and account authorization.

### Functions implemented in this source engine

- Scan source folders, search/select songs, persist source/output preferences
- **JSON-only lyric editing:** The head/tail/search replacement editor updates only timed Lyrics JSON, preserves original MID/LYR/CUR, interpolates display cues within each original lyric line if the text length changes, and supports ZIP backup/undo. No artificial dot or “ดนตรี>” filler text.
- **Default export:** Original MIDI/KAR copied with SHA-256 verification + timed Lyrics JSON. Optional M4A conversion creates a new audio file without changing source MIDI. Source NCN .LYR/.CUR are import-only and never uploaded.
- **Private Drive v4:** Exactly two folders, XStageSong/AUDIO (media and SoundFonts) and XStageSong/LYRICS (timed lyrics, catalogs, current.json). Legacy layouts can be read but not silently migrated, rewritten or deleted.
- Convert supported audio formats to M4A (AAC 192 kbps) using FFmpeg; preserve existing M4A audio
- Render MIDI/KAR to WAV using bundled FluidSynth and default SF2, then convert to M4A
- **Offline AI Separation:** HTDemucs ONNX model and NumPy/ONNX Runtime are included in the Ready ZIP. Choose “แยกเสียงร้อง AI (Full Offline)” in create-step 3; create-step 4 exports the instrumental M4A plus a separate vocals M4A. Preview uses the same local AI model. No additional downloads on the user's PC.
- **Live listening:** Step 3 now searches songs independently, plays as a real MP3 stream without generating preview files, and mixes matching same-stem backing audio and MIDI via the chosen SF2/SF3 using FluidSynth. Volume levels apply when starting a new stream. Audio-only files play normally; there is no manufactured MIDI accompaniment. Edit LRC and save as companion lyrics file.
- Local work status, progress, cancellation, and non-overwriting output names

### AI separation limitations

- CPU-only in this edition; a reasonably fast 64-bit PC and sufficient memory are required. Processing takes longer than standard conversion.
- The chosen AI model uses four-stem Demucs separation; output quality varies by recording. It is not a perfect vocal remover.
- The GitHub source folder contains `ai_separate.py` and `ai-model.lock.json`, while the large model binary is shipped in the GitHub Release ZIP, not committed to the Git history.

### Dialog UX

Native browser confirmation windows have been replaced with styled in-app borderless dialogs and toast notifications; the Windows folder/file chooser remains a native OS dialog.

### Preventing duplicate songs across separate sessions

- The first successful build stores the original source's canonical path and SHA-256 in the durable local catalog.
- A second build, even after exiting and restarting Song Studio, **skips** that exact source and never allocates a second audio/lyric file.
- A copied or renamed source with identical audio bytes is also skipped by SHA-256.
- Completed songs are fsynced to `songs/.build-journal.jsonl` before processing the next song. After interruption the next run checks both catalogs and this journal; `current.json` is published atomically.
- Brand-new output uses `songs/audio/<first-digit>/`, companion lyrics `songs/lyrics/<first-digit>/`, grouped immutable `songs/catalogs/`, and `songs/current.json`.
- Legacy outputs created by older versions without source fingerprints cannot always be matched automatically; the engine blocks ambiguous unindexed filename collisions and reports the reason rather than silently making duplicate numbered files.
- Two genuinely different originals with the same filename can coexist with a collision-safe suffix, while existing media is never overwritten.

### Google Drive OAuth for every PC user (one owner configuration)

**The app developer configures the matching Google Desktop OAuth Client ID + Client Secret ONCE.**
Do **not** distribute any user's refresh/access token, profile, or Google password.

1. In Google Cloud, enable Google Drive API and set up Google Auth Platform.
   For users outside your organization, choose **External** and publish
   the OAuth consent app **In production**. While in **Testing**, only
   allowlisted test users can authenticate and consent usually expires after
   seven days (for non-identity scopes). Follow Google's verification requirements.
2. At **Google Auth Platform → Clients → Create client → Desktop app**, create
   a dedicated **X-Stage Song Studio PC** client. Download the original OAuth
   Desktop JSON containing BOTH `installed.client_id` and `installed.client_secret`.
   Do **NOT** use the Web app Client ID from `config.js`: Web/TV use different
   OAuth client types. Google can reject a Desktop token request with
   `HTTP 400: client_secret is missing` if the secret is omitted, even with PKCE.
3. In the repository **Settings → Secrets and variables → Actions** set:
   - **Variable:** `XSTAGE_GOOGLE_DESKTOP_CLIENT_ID` = Desktop Client ID
   - **Secret:** `XSTAGE_GOOGLE_DESKTOP_CLIENT_SECRET` = matching Desktop Client Secret
   From the **same** downloaded Desktop JSON. The next `PC Ready Offline ZIP`
   build embeds the complete *public Desktop OAuth client configuration*
   (both values) into `config/google-oauth-client.json`. GitHub Actions stores
   the build input Secret outside Git history, but anyone who downloads a
   native application can inspect the resulting Desktop credentials; this
   field is **not** a confidential server secret. **Never include** users'
   access tokens or refresh tokens in a release.
4. Every end user extracts that release and clicks **Google Login**.
   No JSON picker is required. Each user selects **their own** Google account
   and approves **their own** Drive access once. Personal OAuth tokens are
   never included in the downloadable ZIP.

**Persistent Windows user storage:** `%LOCALAPPDATA%\X-Stage\SongStudio\`.
This stores `preferences.json`, a user's optional `oauth-client.json`
override and `google-auth.dpapi` (encrypted refresh token). New application
ZIP releases automatically reuse the same per-Windows-account settings.
Old per-ZIP `data` contents are copied into this folder if not present; they
never overwrite an existing user profile. Separate Windows accounts have
separate authorization, which is required for privacy.

**Fallback and repair for older builds:** If the developer has not configured
BOTH GitHub settings, the ZIP intentionally does not bundle a broken ID-only
OAuth file. Open **Settings → Advanced → Choose Desktop OAuth Client JSON**
and select the **original full JSON from Google Cloud** once. The app now
preserves both `client_id` and `client_secret` under Windows AppData; future
releases do not require choosing again. Older versions (Build 310–312) stripped
`client_secret` on import. Reimport the ORIGINAL JSON once after upgrading.
If the same Desktop client is fully bundled in the new release, the app can
bypass the obsolete ID-only AppData override automatically.

**Important:** this does NOT log users into Google automatically or bypass
Google consent. Desktop clients are public: their `client_secret` cannot be considered
confidential once shipped to users. We still use PKCE and encrypted *per-user*
refresh tokens, and never ship the user's tokens. `drive.file` limits visibility
to files this application created or was explicitly granted access to.
The app owner must publish the Google consent screen appropriately for the
target audience; Google may require brand verification.

**Testing status:** GitHub Windows automated tests can check the bundled
Client ID and mock the OAuth callback, and validate Windows DPAPI roundtrip.
They cannot verify sign-in against a real account without the user's consent.

### Live SoundFont and PC window fixes

- On MIDI-only tracks, the original melody is rendered through the bundled default SoundFont while the chosen SoundFont is independently mixed. Muting the chosen SoundFont does not mute the original track.
- Both volume sliders, the selected SoundFont and the MIDI preset are processed on the running stream; no preview file is created and the playback time is preserved.
- The Edge PC app launches maximized with desktop-scale responsive layout. If Edge is unavailable, your default browser opens and its window size remains under browser control.
- "M4A only" and "M4A + lyrics" are both tested with real files. A later full build adds missing Lyrics without rewriting an existing M4A.

### Build button fix in v0.3.12 Build311

- Both buttons (M4A only / M4A + lyrics) now use one confirmation, then show the actual PC Engine job ID directly on Step 4.
- Preflight checks song IDs, input existence, format support, FFmpeg, SoundFont (for MIDI), AI mode readiness and output write permission **before** acknowledging a job.
- The Step 4 panel shows current progress, skipped existing songs, M4A/Lyrics counts and detailed errors. Failures remain visible until next action.
- Windows CI includes a real authenticated HTTP POST `/api/jobs` + GET `/api/status` smoke test, followed by output validation for both create actions and `songs/current.json`.
- Existing completed songs are skipped without regeneration. Older source formats such as NCN remain unsupported and now produce a clear explanation instead of silent inactivity.

### Verify song lyrics while auditioning, and optional offline AI transcript

In Step 3, find a song by title, singer or code and start the no-file karaoke
preview. The lyrics panel displays lines in sync with the player's playback
position, and labels the genuine source: timed LRC, MIDI/KAR embedded lyric,
or NCN Song + Lyrics + Cursor components. When lyrics cannot be matched or
the NCN trio is incomplete, the app reports the exact reason and never
fabricates a blank or guessed lyric document.

**AI only when original audio has audible singing:** Ready Build 316 includes
the pinned multilingual Whisper.cpp base model and native Windows CLI. On
an MP3/M4A/WAV/etc. with no usable existing lyrics, click
**AI ถอดเสียงร้องเป็นร่างเนื้อร้อง** and select Thai or auto-detect language.
The on-device ASR transcribes to an **unverified** line-timed draft in
`%LOCALAPPDATA%\\X-Stage\\SongStudio\\ai-lyrics-drafts`.
No private audio is sent to a server. A temporary mono WAV is deleted
after inference; no M4A song is created by the audition workflow.
Use **ตรวจและบันทึกร่าง AI** to correct the guessed text and timing before
it is accepted as an editable LRC or used in the final catalog.

Important limitations: Whisper is a speech recognizer, not a reliable song
lyrics recognizer. It can mishear Thai singing, improvise/hallucinate words on
instrumental music, or miss entire verses. Never auto-publish AI transcripts
as verified karaoke lyrics. A pure MIDI/NCN instrumental contains note
events, **not a singer's words**, so transcription is not offered unless
an actual audio recording with vocals exists.

### Limitations

- **NCN** music handling, **Google Drive access to files owned by a different OAuth application** remain unimplemented in the source engine. The UI still shows legacy controls for PC/Web parity; these actions will display a clear unsupported error rather than silently claiming success.
- Users may choose their own compatible SoundFont; the default bundled SF2 works out of the box.
- Actual music performance depends on CPU speed, RAM and file codec.
- The app does not have a signed native Windows installer/executable. It is a portable ZIP with a double-click CMD launcher, not a signed EXE.
- Windows SmartScreen/Defender may scrutinize this unsigned bundle. Review checksums and project source. Do not disable security protections merely to run it.
- GitHub Actions validates the build and basic local conversion, but device-specific behavior still needs local testing on the target Windows computer.

### Privacy

Songs, soundfonts and output files are handled locally. The local server binds to `127.0.0.1` and uses an in-memory session token for its API. The PC interface can optionally link to the separately hosted web control with an explicit pairing token. The application does not upload song contents by default.

### Developer workflow

- Runtime package generator: `scripts/build_songstudio_ready.ps1`
- GitHub workflow: `.github/workflows/build-songstudio-pc-ready.yml`
- Source (without runtime binaries): `songstudio-pc/`
- Distributed ZIP: GitHub Release `song-studio-pc-ready-v0.3.36-build336`
- Third-party redistribution notes: `THIRD_PARTY_NOTICES.md`

**If the SHA-256 integrity check fails**, the app does not run: download and extract a fresh verified ZIP. Do not download missing components separately.

## Google Drive library layout v4 — AUDIO + LYRICS

All new owner-private music libraries use exactly two flat directories under
`XStageSong/`; there are no format, category, code or bucket subfolders:

```text
XStageSong/
  AUDIO/
    00001-<source SHA prefix>.mid
    00002-<media hash>.m4a
    Piano-<hash>.sf2
    ...
  LYRICS/
    00001-<lyrics hash>.json
    00002-<lyrics hash>.json
    catalog-base-<generation>.json
    catalog-delta-<generation>.json
    current.json
    ...
```

Song Studio keeps the source MIDI byte-identical in standard X-Stage export
mode, and writes timed Lyrics JSON without changing source LYR/CUR.
The user may optionally render to M4A without editing the original MIDI.
A source .LYR/.CUR/.LRC may be imported locally to create verified JSON but
is **not** uploaded to Google Drive.

`current.json` is published **last**, after the media and immutable catalog
have passed checksum verification. The Web and Android TV read the same
private catalog and fetch the media by Google Drive File ID. Existing
layout-v1/v2 roots and layout-v3 `TEXT/` catalogs remain readable for backup
and inspection, but a legacy library is not automatically migrated,
overwritten or deleted; publishing in v4 requires verified migration.

The local PC working library remains `XStageSong/` with its own local
`audio/`, `lyrics/` and catalog journal structure. It must not be
confused with the two-folder private **Google Drive** layout.

## Export to X-Stage Karaoke PC (native SQLite)

Song Studio and Karaoke PC both name the local library `XStageSong`.
Use **นำเข้า X-Stage Karaoke PC** to select the installed Karaoke PC folder,
its `Songs` folder, or the `XStageSong` folder itself. The export places
media in `XStageSong/AUDIO`, timed lyrics and local catalog pointers in
`XStageSong/LYRICS`, and creates or updates **Karaoke PC's native
`songs.sqlite3` SQLite database** through its own `SongLibrary` schema and
upsert method. The existing songs, user-edited artist/title, favorites and
queue are preserved. A verified, timestamped SQLite backup is made before
modifying an existing database; no files with conflicting bytes are replaced.

When a genuine Karaoke PC installation is detected, the export selects
`<install>/Data/songs.sqlite3` (or `<install>/App/data/songs.sqlite3`
when that is the existing active DB). If both independent databases exist,
export stops for manual resolution rather than updating the wrong one.
For a destination that is not a verified Karaoke PC installation, a
**portable native-format SQLite database** is written to
`XStageSong/DB/songs.sqlite3`. This export-only database does not become
the player's active index automatically: select that library in Karaoke PC
or use a verified installed destination.

When authoring and playback share the same physical `XStageSong` folder
(on case-insensitive Windows, `audio` and `AUDIO` name the same directory),
the exporter reuses identical media and publishes immutable
`-pc-snapshot-<sha>` lyrics copies for the Karaoke PC catalog. This prevents
later lyric changes in Song Studio from rewriting an earlier published
Karaoke PC lyric reference.

### Verification

The Windows Ready CI runs `scripts/test_songstudio_drive_layout.py` and
`scripts/test_songstudio_online_publish.py` before making its ZIP artifact.
These cover the two flat folders, online pointer/catalog layout,
download restoration, duplicate-root safety and interrupted uploads.

