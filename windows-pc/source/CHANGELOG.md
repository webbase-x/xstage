## v0.9.48 — Windows Online sync responsiveness and song type selection

- Centre the X-Stage Karaoke Online dialog on the active desktop window and show live scan counts and elapsed time.
- Scan SQLite song count before verifying individual Song Bundles; report inspected items without blocking Tk events.
- Filter real Google Drive sync jobs by NCN or MIDI/KAR. MP3/MP4 remain unavailable until the audio renderer supports them.
- Show processed/total and percent for the conversion/upload pipeline; retain 0.9.47 cancellation and resumable sync semantics.
- Do not publish or delete existing remote media merely because a category is deselected.

## v0.9.47 — X-Stage Online dialog re-open/re-sync and SoundFont choice

- Keep online window open and progress polling active after a sync finishes; allow another sync without restarting the PC application.
- Fix cancellation, external destruction, stale busy flags and app shutdown with an idle Online dialog.
- Default to the PC SoundFont stack/settings, with an explicitly selected separate SoundFont for web conversion only.
- Add Windows/Xvfb GUI lifecycle and SoundFont isolation regression tests.

# v0.9.45 (2026-11-09)
- เพิ่ม Offline NCN/MIDI Batch Converter (`Convert-Web-Assets.cmd`) สร้าง M4A, Lyrics JSON และ database.json บนดิสก์ โดยไม่ใช้ Drive
- เปลี่ยน X-Stage Karaoke Online ให้แสดงจำนวนเพลงจาก DB ก่อนเริ่ม และรอกดปุ่มซิงก์
- อัปโหลด M4A/JSON รายเพลงพร้อมเรนเดอร์เพลงถัดไปใน Worker; Catalog ส่งหลังงานทั้งหมด และ `current.json` ส่งท้ายสุด
- เก็บสำเนา DB ที่เผยแพร่สำเร็จใน Data/WebAssets; หยุด/ล้มเหลวไม่เปิดเว็บและไม่สลับ Catalog
- รองรับซิงก์เพลงเดิมหรือส่งต่อเมื่อหลุด; เพิ่ม Regression บน UI และการทำงานซ้อนกันของ Renderer/Upload

# X-Stage Karaoke — 0.9.44

- เมนูคลิกขวา X-Stage Karaoke Online เปิด Web Asset Sync (ไม่เรียก Google Drive Backup เดิม)
- ใช้ฐานเพลงที่ค้นหาได้ แปลง NCN/MIDI เป็น AAC-LC M4A และ Lyrics JSON แล้วอัปโหลดทีละเพลง
- ตรวจ Catalog เดิมใน XStageWeb; ใช้ไฟล์เดิมเมื่อ Hash ตรง; ซิงก์ต่อได้; ส่ง Catalog รุ่นใหม่แล้วอัปเดต current.json เป็นขั้นสุดท้าย
- Worker หลาย Process แยก SoundFont Handle ต่อ Process, MIDI Stream ใหม่ต่อเพลง
- ฝั่งเว็บใช้ OAuth drive.file และ Drive File IDs ของบัญชี Google ปัจจุบันบน GitHub Pages
- ไม่ลบเพลงต้นฉบับหรือไฟล์สำรองเก่าบน Drive; ไม่ส่ง SQLite/Queue/Settings ไป Drive

# v0.9.43 (2026-11-08)
- Windows Build gate now writes `build-tests-summary.json` with exact failed test IDs, errors and reasons; Install-Logged saves fresh diagnostics beside installation transcript and shows failures on-screen. Failing tests still block EXE installation.
- Google Drive visible Song Bundle sync reuses the source MD5 already computed in the SHA-256/MD5 manifest; source hashes and remote checksums are re-verified before publishing the web manifest.
- Snapshot verification requires SHA-256 entries for SQLite, settings, queue, and transfer metadata; missing mandatory proof fails closed.
- Remove the dormant automatic duplicate-hiding branch from manual duplicate scans; a report cannot change visibility.
- Add 0.9.43 regression tests and Windows verification command. Windows-native installer, NTFS delete, and full Drive restore remain unverified until Windows testing completes.

# v0.9.42 (2026-11-08)
- Native handle-verified permanent delete (NTFS, fail-closed), improved recycle preflight & partial journal.
- Preserve manual_hidden state across quick updates; unify visibility filters.
- Accurate per-batch success/fail counts; one SQLite backup per action batch; stale report ID/path guard.
- Drive media file SHA-256/size/MD5 manifest and prepublish remote integrity checks; shared directory cache.
- Read-only incomplete/unplayable category; remove disabled copy toggle; update release version gate.
- Windows and Drive restore limitations in RELEASE_0942_TH.md.

## v0.9.41 — 2026-11-08

- Disable automatic song copying and old quarantine actions; index source paths in place.
- Never auto-hide duplicate Song Bundles while importing or indexing.
- Add read-only categorized duplicate reports with optional full bundle SHA-256.
- Add explicit hide/exclude/recycle/permanent-delete Song Bundle actions, verification, journaling and confirmation.
- Keep legacy quarantine restore for old data.
- Google Drive media sync is visible-catalog-only and streams originals without bulk local media staging; manifest published last.
- Add 0.9.41 Windows regression script and tests; 55 obsolete historical tests marked skipped with rationale.

## v0.9.40 (2026-11-08)
- Index-backed exact numeric code lookup without a full in-memory song catalog; retain FTS/LIKE fallback and leading zeros.
- Numpad `*` + code + Enter inserts at the front of the waiting queue without interrupting playback; safe focus and pending-result handling.
- `Ctrl+Shift+H` opens the existing preview/confirmation UI for popular-history medley (no implicit queue mutation).
- Throttle visible peak-meter rendering to 80 ms and hidden polling to 250 ms.
- Add operator-shortcut and meter regression tests; retain all existing audio, MIDI, remote, backup and Fast Index architecture.
- Source release; native Windows audio/installer tests still required.

## v0.9.39 (2026-11-08)
- Add two-phase Fast Index: search-first `quick` + explicit exact SHA-256 verification `fast`.
- Persist per-path verification queue across restarts; never infer/auto-hide exact duplicates in `quick`.
- Scope missing/offline reconciliation to the selected folder; preserve IDs, favorites and manual edits.
- Avoid eager CSV reports, content hashing, and whole-database backups for append-only quick updates.
- Add GUI quick default and separate detailed verification action; prevent quick automatic shutdown/copy.
- Include Windows SQLite test connection fixes and more robust test discovery; new quick regression tests/benchmarks.
- Source release only: Windows-native EXE/audio/install tests still required.

## v0.9.38 (2026-11-08)
- Remote foreground polling keeps active connection; expired/offline clients still released.
- Bounded request lifecycle with retry protection and capped response cache.
- Durable `play_stats.sqlite3` ledger with backfill from existing history; 7/30/90/all-time popular medley.
- Drive backup/restore includes optional history and stats and validates SHA-256; backwards compatible.
- Bounded Python memory random-medley sampling for large libraries, plus tests and benchmark.
- Source release only: Windows-native validation still required.

## 0.9.37 — 8 พฤศจิกายน 2569
- เพิ่ม "เมดเลย์เพลงฮิตจากประวัติการเล่น" จัดอันดับจำนวนครั้งที่เล่นจริงจาก history.json ในเครื่อง (สูงสุด 500 รายการล่าสุด)
- เลือกช่วง ทั้งหมด/30 วัน/90 วัน, แสดงจำนวนครั้ง, รวมเพลงซ้ำตามชื่อ-ศิลปิน-คีย์ และไม่เลือกไฟล์หาย/เพลงในคิว
- เพิ่มชุดทดสอบ 12 กรณี และทดสอบหน้าต่างจริงด้วย Xvfb; รายงานตรวจระบบแต่ละฟังก์ชันอยู่ใน AUDIT_ALL_FUNCTIONS_0937_TH.md
- ไม่เปลี่ยนฐานเพลงหรือรูปแบบไฟล์ history; ยังต้อง Build และทดสอบ Windows ก่อนติดตั้งจริง

# X-Stage Karaoke v0.9.36 — 8 พฤศจิกายน 2569

- จำกัดการตรวจไฟล์หายนอกขอบเขตโฟลเดอร์ที่เลือก ไม่เปลี่ยนสถานะเพลงจาก USB/NAS ออฟไลน์โดยพลการ
- แก้ Copy to Songs ให้คัดลอกเข้า Songs แล้วบันทึกแถวใหม่ได้ในทุกนโยบายเพลงซ้ำ
- ปรับ cache SQLite แบบ conditional upsert: รอบไม่มีการเปลี่ยนแปลงไม่เขียน cache ซ้ำ
- ตรวจไฟล์เปลี่ยนก่อน COMMIT และตรวจทุกไฟล์ที่เลือกอีกครั้งเมื่อเปิด Auto Shutdown
- เมื่อสร้าง CSV/อัปเดต cache ไม่สำเร็จหลัง COMMIT ให้แจ้ง partial อย่างตรงไปตรงมา ห้ามปิดเครื่อง
- เพิ่มปุ่มสร้างรายงาน CSV ใหม่โดยไม่ต้องสแกนเพลงซ้ำ และทดสอบกรณีจริงของทั้งห้าจุด
- ดู RELEASE_0936_TH.md, QA_RESULTS_0936_TH.md และ WINDOWS_BUILD_0936_TH.md

# X-Stage Karaoke v0.9.35 — 8 พฤศจิกายน 2569

- แก้ Fast Update เก็บไฟล์ที่หายเป็น missing แบบย้อนกลับได้; กู้สถานะเมื่อไฟล์กลับมา
- รองรับเลื่อนสำเนาเพลงที่เหมือนจริงขึ้นเป็นเพลงหลัก พร้อม favorite, user_edited และ alias ID เก่า
- Migration แคชครั้งแรกตรวจ metadata ใหม่เพื่อไม่พลาดข้อมูล LRC เปลี่ยน
- Safe Rebuild ไม่ลบเพลงจากโฟลเดอร์อื่น และไม่ลบข้อมูลไฟล์หายทันที
- Auto Shutdown ผ่านเฉพาะ success เต็มรูปแบบ ไม่มี missing/failed/unsupported, มีเพลงให้สแกน และผ่าน quick_check
- Snapshot SQLite แบบหมุนเวียน 5 ชุด พร้อมตรวจและกู้คืนออฟไลน์; รักษาชื่อสำรองเก่าไม่ให้ถูกเขียนทับ
- ลดการสร้างรายงานซ้ำ, รายงานไฟล์หาย, ปรับหน้าจัดรายการค้นหาไทยโดยใช้ FTS5/trigram เมื่อรองรับ
- แนบ RELEASE_0935_TH.md, QA_RESULTS_0935_TH.md, WINDOWS_BUILD_0935_TH.md

# 0.9.34 — 8 พฤศจิกายน 2569

- หน้าสร้างรายการเพลงใหม่: Fast Update / Full Scan / Safe Rebuild โดยใช้แคชลายเซ็นไฟล์อย่างระมัดระวัง; โหมด Fast ข้ามการอ่านเนื้อหาไฟล์ที่ไม่เปลี่ยน และข้ามสำรอง/เขียนฐานเมื่อไม่มีรายการเปลี่ยน
- ตรวจเพลงซ้ำจริงจาก SHA-256 ของไฟล์เพลงพร้อมไฟล์ประกอบ เฉพาะกลุ่มที่ขนาดตรงกัน; ไม่รวมเพลงชื่อ/นักร้อง/คีย์เดียวกันแต่เนื้อหาต่างกัน
- ตัวเลือกซ่อนรายการซ้ำ (ค่าเริ่มต้น), แสดงทั้งหมด หรือเก็บทั้งหมดให้ทบทวน; รายงาน CSV เพลงซ้ำจริง, ชื่อซ้ำต่างเวอร์ชัน และรหัสชนกัน; ไม่มีการลบไฟล์ต้นฉบับ
- จัดชุดข้อมูลในฐานชั่วคราว บันทึก SQLite แบบ transaction เป็นชุด, รักษา ID เดิม เพลงโปรดและข้อมูลที่แก้เอง; Safe Rebuild ไม่แทนที่ฐานถ้าพบข้อผิดพลาดในการอ่าน
- เพิ่มตัวเลือกปิดเครื่อง Windows เมื่อสร้างรายการเพลงสำเร็จและตรวจสถานะปลอดภัย หลังนับถอยหลัง 60 วินาที กดยกเลิกได้; ปิดเป็นค่าเริ่มต้น และไม่บังคับปิดงานอื่น
- เพิ่มชุดทดสอบการสแกนเร็ว/เต็ม, เพลงซ้ำ, การยกเลิก, การเปลี่ยน LRC, รักษารหัส, คัดลอกไฟล์ และเงื่อนไขปิดเครื่อง
- ยังคงช่องทาง import เดิมและ API ของรุ่นเก่าสำหรับความเข้ากันได้; ดู `RELEASE_0934_TH.md` สำหรับขอบเขตที่ตรวจจริง

# 0.9.33

- แก้ข้อผิดพลาดเมื่อยกเลิกงานจัดการรายการเพลง และให้โปรแกรมปิดได้เมื่อจบการยกเลิก

# 0.9.32

- เพิ่มเมนูสุ่มเมดเล่ย์จากคลังเพลง จังหวะ เพลย์ลิสต์ หรือเพลงโปรด พร้อมดูและจัดลำดับชุดก่อนเข้าคิว
- เล่นเต็มเพลงต่อเนื่อง ข้ามช่วงเงียบหัวท้ายเมื่อวิเคราะห์ได้ และใช้กลองส่ง SoundFont กับ MIDI ที่มีจังหวะเข้าชัดเจน
- เพิ่มท้ายคิว เล่นเป็นชุดถัดไป หรือยกเลิกเฉพาะเพลงในชุดที่ยังรอเล่น

# 0.9.21 - 20261107

- แสดงเมนู **ซิงก์ X-Stage Karaoke Online…** เฉพาะในหมวดตั้งค่า
- นำเมนูสำรองข้อมูลทั่วไปออกจากเมนูผู้ใช้ เพื่อลดความซ้ำซ้อน
- คงระบบสำรองภายในสำหรับความปลอดภัยและการกู้คืนข้อมูลไว้ในโค้ด

# 0.9.20 - 20261107

- เพิ่มเมนู **ซิงก์ X-Stage Karaoke Online…** ในหมวดตั้งค่าและเครื่องมือ
- แสดงขั้นตอนล็อกอิน Google Drive Desktop และย้ำให้ใช้อีเมลเดียวกับเว็บ
- เปลี่ยนสถานะการทำงานจาก “สำรอง” เป็น “ซิงก์” ให้ตรงกับการใช้งานจริง

# 0.9.19 - 20261107

- เปลี่ยนชื่อหน้าเว็บและชื่อที่ผู้ใช้เห็นเป็น **X-Stage Karaoke Online**
- คงโครงสร้างโฟลเดอร์ `XStageKaraoke` ใน Google Drive เพื่อความเข้ากันได้กับข้อมูลเดิม
- เตรียมแพ็กเกจเว็บสำหรับ repository ใหม่ โดยไม่ลบข้อมูลเพลงหรือฐานข้อมูล

# 0.9.18 - 20261107

- ตัดเส้นทางเพลงซ้ำก่อนสร้าง Snapshot และป้องกันการคัดลอก Source ซ้ำ
- ใช้ `rel_path` โดยตรงบนเว็บ เพื่อรองรับโฟลเดอร์ย่อยชื่อ Songs
- ค้นหา Snapshot จากทุกโฟลเดอร์ XStageKaraoke ที่ผู้ใช้มีอยู่

# 0.9.17 - 20261107

- แก้ข้อความยืนยันกู้คืนให้ขึ้นบรรทัดใหม่ถูกต้อง
- ป้องกัน Snapshot ชนกันด้วย timestamp ความละเอียดสูงและเลขลำดับสำรอง
- กรองโฟลเดอร์เพลงซ้อนกันเพื่อไม่คัดลอกไฟล์ซ้ำ

# 0.9.16 - 20261107

- เพิ่มการยืนยันก่อนกู้คืนจาก Google Drive และป้องกันการกู้คืนระหว่างสำรองข้อมูล
- รอ/ยกเลิกงานสำรองอย่างปลอดภัยเมื่อปิดโปรแกรม
- รองรับหลายโฟลเดอร์เพลงและ escape พาธบนเว็บ player

# 0.9.15 - 20261107

- เพิ่ม Snapshot แบบเขียนไฟล์ชั่วคราวแล้วเปลี่ยนชื่อแบบ atomic
- ป้องกันการสำรองข้อมูลซ้ำและบล็อกการกู้คืนขณะกำลังเล่น/สแกน
- เพิ่ม rel_path ใน web-manifest เพื่อรองรับคลังเพลงที่ใช้ชื่อโฟลเดอร์ใดก็ได้
- ตรวจชื่อบัญชี Google ด้วยกฎชื่อสงวนของ Windows

# 0.9.14 - 20261107

- แก้ worker ย้ายคลังเพลงซ้ำและปรับ Cloud Backup เป็น background worker
- เพิ่มการเลือก Snapshot ล่าสุดและกรองชนิดไฟล์เสียงสำหรับเว็บ player

# 0.9.13 - 20261107

- เพิ่มเว็บ player สำหรับ GitHub Pages ด้วย Google OAuth/Drive manifest
- เพิ่ม cloud snapshot ต่อผู้ใช้โดยใช้ฐานข้อมูลเดิม

# 0.9.12 - 20261107

- เพิ่ม Local-first Google Drive Desktop snapshot ต่อผู้ใช้
- ใช้ schema ฐานข้อมูลเดิมและกู้คืนผ่าน recovery pipeline เดิม

# 0.9.11 - 2026-11-07

- เพิ่ม rollback การย้ายคลัง, ตรวจ collision และ preview แบบ worker
- เพิ่ม generation guard สำหรับ poll และ regression tests

# 0.9.10 - 2026-11-07

- ย้าย offsets, lyric_files, EQ, source_catalog และ index cache ตามพาธใหม่
- แยก poll AbortController จาก API อื่น
- เพิ่ม legacy_root/deduplicate และ regression tests

# 0.9.9 - 2026-11-07

- แก้ activeController และ AbortError ของ Mobile Remote
- แก้การเปรียบเทียบพาธ EQ แบบกลุ่มบน Windows
- อัปเดตรายการ song_folders และมุมมองหลังย้ายคลัง
- กรอง native/x64 DLL ออกจาก Source ZIP

# 0.9.8 - 2026-11-07

- เชื่อมต่อการย้ายรากคลังเพลงและย้าย EQ แบบกลุ่มเข้ากับหน้าจอจริง
- ใช้ PathProbe กลางสำหรับตรวจไฟล์ EQ และรองรับ Tooltip หลายจอ
- ปรับ reconnect ให้ยกเลิกคำขอเครือข่ายเดิมได้
- ทำ Source ZIP ให้มีโฟลเดอร์รากและกรองข้อมูลทดสอบ/ล็อกออก

# 0.9.7 - 2026-11-07

- แก้ safe-area และปุ่มเชื่อมต่อใหม่ของรีโมทมือถือ
- ปรับ Tooltip กันขอบจอและยกเลิก timer เมื่อ widget ถูกทำลาย
- กรองไฟล์ชั่วคราว/ไบนารีจาก source ZIP และเพิ่มการตรวจสอบข้ามระบบ
- เพิ่ม unit tests สำหรับ UI รุ่น 0.9.7

# 0.9.6 - 2026-11-07

- Tooltip lifecycle และขอบจอ
- Mobile reconnect และ safe-area
- อัปเดต test suite 790 รายการ

# 0.9.5 - 2026-11-07

- เพิ่ม Tooltip ให้ปุ่มควบคุมหลัก
- เพิ่ม touch target และ responsive layout สำหรับรีโมทจอเล็ก
- กันพื้นที่สถานะรีโมทกระโดดระหว่างอัปเดต

# 0.9.4 - 2026-11-07

- เพิ่ม startup hygiene แบบกักกันไฟล์กู้คืนค้าง
- เพิ่ม cancellable path probe สำหรับไดรฟ์ภายนอก/เครือข่าย

# 0.9.3 - 2026-11-07

- เพิ่มรายละเอียด OS ใน cleanup journal
- รอ SoundFont worker ปิดจริงก่อนคืนทรัพยากร
- เพิ่ม batch relocate สำหรับรากคลังเพลงและค่า EQ แบบ atomic

# 0.9.2 - 2026-11-07

- รวมตัวตรวจ cleanup journal ให้ใช้ implementation เดียว
- เพิ่ม SQLite busy timeout และ foreign key enforcement ในฐานข้อมูลหลัก
- ปรับปรุงการตรวจ recovery งานเบื้องหลัง

# 0.9.1 - 2026-11-07

- เพิ่มการตรวจพบงานลบเพลงที่ค้างจากการปิดผิดปกติหรือไฟดับ
- แสดงแผนและสถานะ journal ให้ผู้ใช้ตรวจและกู้คืนก่อนทำงานลบต่อ
- เพิ่ม regression tests สำหรับ crash recovery ของงานลบ

## 0.9.0 — 2026-11-06

- Add title/artist/original-key duplicate policy, type-specific completeness gate and immutable review plans for explicitly confirmed permanent deletion with verified backups/recovery. Fix all six findings in the 0.8.2 completeness audit.

## 0.8.2 — 2026-11-06

- Register remembered legacy catalog locations once and after successful imports; fix database-only rebuild arguments.

## 0.8.1 — 2026-11-06

- Remove Search and Manage Songs buttons from the bottom transport bar.

## 0.8.0 — 2026-11-06

- Add explicit import copy/reference and title/artist duplicate policies, verified managed song bundles, stable-ID replacement and duplicate status. Rename volume display to ระดับเสียง.

# 0.7.3 — 2026-11-06

- Share settings validation and strict JSON parsing across startup, saves and all restore paths.
- Continue application resource cleanup after save/cleanup failures and report collected errors.
- Load selected SoundFont details asynchronously with stale-result cancellation.
- Reject stale cached queue/settings/history writes using content revisions.
- Report partial playlist indexing/queue persistence results explicitly; retain existing queue rollback.

# 0.7.2 — 2026-11-06

- Reject duplicate JSON keys without silently overwriting prior values.
- Prevalidate complete playlists before adding files to the song index; keep legacy version-1 behavior.
- Select CPython 3.13 x64 for locked builds before setup; retain incompatible existing environments.

# 0.7.1 — 2026-11-06

- Reuse verified corrupt-JSON copies within a bounded per-process cache; preserve fresh originals for explicit restores.
- Roll back diagnostics setup after failures and finish remaining cleanup after shutdown errors.
- Make diagnostics close idempotent; respect later hook/level changes and preexisting host fault handlers.

# 0.7.0 — 2026-11-06

- Add history restore from the history window and recovery when corrupted history is opened.
- Reuse the owning Tk window for recovery dialogs and reload history cache after restore.
- Reject restoration when target data changes during confirmation or backup; preserve original/candidate copies.

# 0.6.1 — 2026-11-06

- Preserve malformed playback history and roll back failed history mutations.
- Catch history initialization errors in playback hooks; report manual history errors before opening a dialog.
- Validate release manifest schema, required executable, SHA256, duplicate keys and unsafe paths.
- Align log-viewer fallback with per-Data diagnostics; always release Data lock after cleanup failures.

# 0.6.0 — 2026-11-06

- Add explicit settings/queue JSON recovery with validation and preserved originals.
- Reject malformed persisted queue entries; roll back in-memory mutations on save failure.
- Bound SoundFont metadata loading to one worker and one pending latest request; add cancellation and restore selection after async loading.
- Add session IDs, isolate log directories by Data, and record recording/recovery/metadata lifecycle events.
- Pin the build dependency set, validate source/EXE versions and environment, and produce a SHA256 release manifest.

## 0.5.86 — ตรวจระบบและเติม Log รีโมท

- บันทึก traceback เมื่อ GET/POST ของรีโมทผิดพลาดโดยไม่เติม request body, query หรือ Authorization ลงข้อความ Log
- แก้หมวด SoundFont และ PLAYER ให้ครอบคลุมโมดูลหลัก
- เพิ่ม regression tests 3 รายการ ดู AUDIT_0586_TH.md สำหรับผลตรวจและข้อจำกัด

## 0.5.85 — Log viewer, resizable EQ, borderless singer display

- Tools context-menu log viewer: bounded read-only tail, file selection, refresh and open-folder actions. Runtime log category tags, shared log location with SoundFont.
- Visible lower-right EQ resize grip; preserve chosen height, keep control/meter minimum and screen bounds, suspend auto-hide during resize.
- Singer display starts borderless; fullscreen entry/exit retains controls from the main window.
- Remove song code and duration from the shared on-screen metadata line, keeping catalogue data and playback progress unchanged.

## 0.5.84 — Stable SoundFont tab geometry

- Remove fit/recenter on each SoundFont tab change. Keep the user window size and position; retain initial work-area fit and overflow scrolling.
- Include 0.5.83 local logs and hidden-modal recovery.

## 0.5.83 — Local runtime diagnostics and SoundFont window recovery

- Rotating runtime logs, session IDs, UI and background exception hooks, native fault tracebacks, and 15-second heartbeat watchdog (at most three stall stacks per session). No telemetry/upload.
- Log SoundFont window lifecycle, metadata reads and audition native loading/cleanup. Add Open Log Folder button.
- Release a hidden SoundFont window grab; restore minimized/withdrawn existing window; clean up partially constructed dialogs on error.
- Original user freeze not reproduced on Windows; instrumentation is for identifying its cause, not a claim that every freeze is fixed.

## 0.5.82 — Windows temporary-path build fix

- Fix offline-package test comparing a Windows 8.3 TEMP alias against its resolved Unicode path. Verify canonical path and actual file identity.
- Retain the build test gate and all component hash checks; test tampering of installer, source archive, and license separately.
- No audio or SoundFont behavior changes.

## 0.5.81
- Commit pending per-font gain before collect/save and on selection change; reject invalid input instead of silently dropping it.
- Move audition validation, synth initialization, note playback and cleanup to a single-owner background thread; cancellation prevents late note playback.
- Add MIDI note/range/major-chord audition controls and stop-before-close behavior.
- Add conservative background MIDI/SF2 bank/program coverage reports with CSV export and explicit limitations for unknown/fallback/LSB cases.
- Prompt on unsaved settings and retain browser view in the current app session. Merely selecting another font is not treated as a settings edit.
- Add cancellation, cleanup, gain/save, dirty-state, restore and coverage regressions. Windows hardware verification remains pending.

## 0.5.80
- Redesign SoundFont settings as a branded Sound Studio with fixed save/close controls and clear backend status.
- Add a searchable all-bank preset browser and exact-preset audition from the same loaded file; temporary audition mappings are never saved.
- Add follow-song Bank/Program mode, bypassing but retaining legacy instrument overrides. Explicit mapping saves re-enable overrides.
- Preserve all-preset/default-bank loading and forward MIDI bank/program messages unchanged; add regressions using native API doubles.
- Decode valid UTF-8 preset names before legacy Latin-1 fallback. Restore settings on save failure.
- No new instrument samples are bundled; actual sound depends on the supplied SoundFont and the song's bank/program data. Native Windows/audio verification remains pending.

## 0.5.79
- Unify song source management, indexing progress and catalog names into one reusable workspace.
- Collapsible sources, fixed footer actions, dark visual hierarchy, progress counters and latest processed rows.
- Independent read-only background catalog search with stale-result protection, 100-row pages, details/edit/favorite controls and explicit 5,000-result cap.
- Reuse the window across jobs; reset cancellation/progress without discarding the catalog browser; preserve source files and existing incremental import behavior.
- Verify catalog refresh and window lifecycle/busy/cancel/reopen with tests. Native Windows DPI and hardware validation remain outstanding.

## 0.5.78
- Reorganize the EQ footer into preset/comparison, sound controls and per-song/file controls; inline intensity percentage and responsive panel arrangement.
- Limit displayed band gain to one decimal, with staggered labels on narrow layouts; preserve actual DSP values.
- First open now maps, fits, raises and focuses the EQ like reopen; both entry points share one window. Add a two-second auto-hide grace after showing.
- Add first-open/reopen/destroyed-window regressions. Windows focus/high-DPI behavior still needs native validation.

## 0.5.77
- Fix the Windows build blocker in test_child_command_preserves_spaces_and_thai: compare the script path in the host platform format instead of requiring POSIX separators.
- Add Windows drive, UNC and POSIX path regression cases, including Thai text, spaces and frozen/source command arguments.
- Runtime audio/player behavior and build test gating are unchanged. Reported failure was a test expectation mismatch, not a failed native audio check.

## 0.5.76
- Add a single local system report: component checks, output device enumeration and explicitly user-reported Windows checklist results. No automatic audio-pass claim.
- Add component-check activity indicator, report export and staged repair status/error records.
- Add per-song EQ search, versioned backup/import with conflict choice and pre-import recovery copy, and background non-destructive missing-file checks.
- Fix progressbar cleanup after closing diagnostic windows.
- Actual Windows/audio/installer verification remains outstanding; see VERIFY_0576_TH.md.

## 0.5.75
- Debounce wheel/key/Input setting writes while keeping audio changes immediate and per-song save explicit.
- Ramp BYPASS/FLAT using effective audible gains; preserve the bypassed curve and handle rapid reversal.
- Keep EQ visible while its song-manager child window is open.
- Measure and wrap controls independently per row; fit height to controls and monitor work area.
- Windows audio and high-DPI certification remain outstanding.

## 0.5.74
- Repair invalid download caches after validation; preserve invalid offline originals.
- Add nonblocking component inspection and explicit close/repair/reopen workflow.
- Honest per-song EQ processor/save status, manual file relocation, explicit headroom action.
- Re-clamp the borderless EQ rack to the current monitor work area.
- Windows native playback, UAC and high-DPI validation remain outstanding.

# 0.5.73

- Installer automatically prepares missing Python x64, Python packages, Visual C++ runtime and official BASS/BASSMIDI/BASS FX; verifies PE architecture, native API loading and frozen imports before reporting success.
- Download retries/cache/offline lookup, publisher validation for installers, transcript and dependency reports.
- Per-song 31-band EQ recall by normalized file path; explicit remember/forget, global default preserved, live drag updates and song-switch cancellation.
- Windows 10/11 x64 target only; Windows installation/audio tests still pending.

# 0.5.72

- Eight original X-Stage presets, intensity, composite headroom compensation, independent A/B and named user presets.
- Selected EQ band mouse wheel adjustment, 0.5 dB steps; bounded parameter ramps with manual interruption.
- Borderless movable rack, single - docking button, no pin; responsive preset control row.
- RBJ response respects octave bandwidth for graphic EQ headroom calculations.
- Windows native audio and installer verification remain pending.

# 0.5.71

- Graphic EQ 31 fixed 1/3-octave bands, stereo linked, compact hardware rack and logo.
- Per-band Windows loopback RMS LEDs; vertical L/R sample peak, peak hold and clip indication.
- Dock/restore and optional pin; bottom transport edge reveal and automatic hiding.
- Transactional music EQ apply, legacy preset preservation and native handle cleanup.
- Source Preview; Windows audio/device validation remains pending.

# X-Stage 0.5.70 — EQ X-Stage / Single-window rack

ชุดนี้ปรับซอร์สจาก 0.5.70 Setup Preview กลับเป็น EQ เฉพาะเพลง X-Stage
ไม่มี EXE เก่ารวมอยู่ ต้องสร้าง EXE ใหม่บน Windows ก่อนติดตั้ง

## ใช้งาน
- คลิกขวา → เครื่องมือ → EQ X-Stage
- หน้าต่างเปิดกว้างเต็มพื้นที่ทำงานของจอ โดยเว้นพื้นที่ระบบ Windows
- สไลเดอร์ 8 แบนด์ กราฟ แบนด์ที่เลือก Preamp/Output และ Preset อยู่หน้าเดียว ไม่มีแท็บ
- เลือกหมายเลขแบนด์เพื่อแก้ความถี่/ชนิด/Q หรือ S; โหมดขั้นสูงเปิดรายละเอียด
- ปรับแล้วกดใช้ค่า EQ เพื่อฟัง A/B และ Bypass เป็นค่าร่างจนกดใช้ค่า
- ปุ่มจอคาราโอเกะหรือ Esc ซ่อน EQ โดยไม่หยุดเพลง และรักษาค่าร่าง
- เปิดจากเมนู EQ อีกครั้งจะคืนหน้าต่างเดิม ปุ่มปิด EQ ปิดจริงและเตือนค่าที่ยังไม่ใช้
- จอเล็กหรือ DPI สูงสามารถเลื่อนเนื้อหาได้ ปุ่มหลักตรึงด้านล่าง

## ขอบเขตเสียงและการย้ายจาก EQ Windows
- EQ ใช้กับเพลง BASS/SoundFont และเพลงท้ายที่กำลัง crossfade ไม่ได้เป็น Master Bus รวม FX/คีย์บอร์ดทุกแหล่ง
- Windows MIDI หรือ backend ที่ไม่ผ่าน BASS ไม่รองรับ EQ ชุดนี้
- มิเตอร์ LED ยังวัดเสียงรวม Windows ของเอาต์พุตเริ่มต้น ไม่ใช่มิเตอร์เฉพาะ X-Stage
- ผู้ใช้ใหม่ไม่ต้องติดตั้ง Equalizer APO เพื่อใช้ EQ เพลง
- หากตั้ง eq_scope=windows ไว้ กดใช้ค่าเพื่อปิดเฉพาะชุด EQ APO ที่ X-Stage เคยเขียน ก่อนเปิด EQ เพลง
- ไม่แก้ EQ จากโปรแกรมอื่น/Peace ไม่ถอนการติดตั้ง APO
- ถ้าปิดชุด APO เดิมไม่ได้ จะรายงานข้อผิดพลาดและไม่บันทึกการเปลี่ยนโหมด
- ถ้าบันทึกไม่สำเร็จ จะพยายามคืนค่า APO และการตั้งค่าก่อนหน้า

## ติดตั้ง
แตก ZIP ลงโฟลเดอร์ใหม่ เปิด Install-to-D.cmd บน Windows ตัวติดตั้งจะสร้าง EXE ก่อน
หรือเปิดซอร์สนี้ด้วย Codex บน Windows และรัน Build-Windows.cmd
อย่าคัดลอกไฟล์ Python ทับโฟลเดอร์ App แล้วใช้ EXE เดิม เพราะ EXE มีโค้ดฝังอยู่
ใช้ตัวติดตั้งเพื่อสำรองและรักษาฐานข้อมูล/คิว/การตั้งค่าเดิม

## ผลตรวจ
500 tests: 494 passed, 6 skipped (Linux, 19.426 วินาที)
ตรวจ UI ด้วย Tk/Xvfb: ใช้ค่า, ซ่อน/เปิดกลับพร้อมค่าร่าง, หน้าต่าง 1920x1080/800x600, footer, cleanup ผ่าน
ตัวอักษรภาษาไทยในสภาพแวดล้อม Linux ยังแสดงไม่ถูกต้อง จึงยังไม่ยืนยันฟอนต์/การจัดวางภาษาไทยบน Windows
ยังไม่ทดสอบ APO, BASS จริง, UAC, เสียงลำโพง, DPI Windows และยังไม่สร้าง EXE ใหม่


# 0.5.70 — First-run setup and safe program updates

See SETUP_0570_TH.md.

# 0.5.69 — EQ เสียงรวม Windows ผ่าน Equalizer APO

## การติดตั้งครั้งแรก
1. เปิด คลิกขวา > เครื่องมือ > EQ เสียงรวม Windows > แท็บ Windows
2. กดดาวน์โหลด Equalizer APO จากโครงการทางการ ติดตั้งรุ่นปัจจุบัน x64 (ต้องรองรับ LSC/HSC Q ตั้งแต่ 1.2.1)
3. เปิด Device Selector/Configurator เลือกอุปกรณ์เล่นเสียงที่ต้องการ ติดตั้ง APO และรีสตาร์ต Windows หากตัวติดตั้งร้องขอ
4. กดเชื่อม X-Stage ครั้งแรก ยอมรับ UAC แล้วรอหน้าต่างแจ้ง Connected
5. กดตรวจสอบอีกครั้ง เลือกอุปกรณ์เดียวกัน ปรับ EQ แล้วกดใช้ค่า
6. ทดลองเพลงจากเบราว์เซอร์ แล้วลด Preamp -6 dB เพื่อยืนยันว่าเสียงเปลี่ยน ก่อนคืนค่าใช้งาน

## สิ่งที่เปลี่ยน
- แผง EQ เดิมส่ง filter ไปยัง Equalizer APO ที่ประมวลผลเสียงรวม Windows จริง ไม่เล่น loopback ซ้ำ
- ผูกกับ GUID อุปกรณ์ที่เลือกและ post-mix; รวมโปรแกรมที่ผ่าน audio processing ของ endpoint นั้น
- เก็บชุดค่าตามอุปกรณ์ แต่เปิดใช้งานหนึ่งอุปกรณ์ที่เลือกต่อครั้ง
- LED loopback ติดตามอุปกรณ์ที่เลือก; ไม่ได้ยืนยันว่า APO กำลังประมวลผล
- ปิด EQ BASS เดิมสำหรับเพลงปัจจุบัน/หาง crossfade และข้าม EQ เพลงในเพลงถัดไปเมื่อใช้ scope Windows
- Bypass ส่งไฟล์ที่ไม่มี filter/preamp ของ X-Stage; ยังต้องกดใช้ค่า
- EQ รวมยังทำงานหลังปิด X-Stage เพราะทำงานใน Windows APO

## การรักษาค่าเดิมและสิทธิ์
Setup-System-EQ.ps1 สำรอง config.txt พร้อมเวลา ก่อนเพิ่มบล็อก Include ด้านบน
ไฟล์ของ X-Stage อยู่ใน config/XStage/xstage-eq.txt
ให้สิทธิ์ Modify เฉพาะโฟลเดอร์ XStage แก่ผู้ใช้ที่เรียก setup ไม่เปิดสิทธิ์ทั้งโฟลเดอร์ APO
ไม่ลบ filter เดิมของ Equalizer APO / Peace ดังนั้น filter เดิมยังรวมผลกับชุด X-Stage
การ Bypass ไม่ปิด filter ของโปรแกรมอื่น และไม่ถอน APO
ถ้าต้องการถอนการเชื่อมต่อ ให้ลบเฉพาะบล็อก # X-STAGE SYSTEM EQ BEGIN ถึง END ใน config.txt ด้วยสิทธิ์ผู้ดูแล
อย่านำ backup เก่าทับทั้งไฟล์หากมีแก้ไขค่าอื่นหลังจากนั้น
เขียนค่าด้วยไฟล์ชั่วคราวแล้วแทนที่; หากบันทึก settings ล้มเหลวพยายามคืนไฟล์และ EQ เดิม พร้อมรายงานถ้าคืนค่าไม่สำเร็จ

## ขอบเขตจริง
- ต้องติดตั้งและเปิด APO บนอุปกรณ์จริงก่อน การตรวจพบไฟล์ไม่ยืนยันเสียงผ่าน APO
- ASIO, Exclusive/raw หรือ driver บางแบบอาจไม่ผ่าน APO
- ไม่รวมอุปกรณ์ที่ไม่ได้เลือก และไม่ใช่ EQ ไมค์ที่ต่อ mixer ภายนอก
- ไม่รับประกันมิเตอร์เป็นจุดวัดหลัง APO ทุกลำดับ driver หรือสัมพันธ์กับ knob hardware/SPL
- ไม่มี Limiter, true-peak, หรือการรับประกันไม่มีเสียงคลิกขณะเปลี่ยนค่า
- กราฟยังจำลอง 48 kHz; ต้องทดสอบ filter/เสียงจริงกับ sample rate ของอุปกรณ์

## ตรวจสอบ
478 tests: ผ่าน 472 ข้าม 6, 20.022 วินาที; compileall ผ่าน
ตรวจ serializer ทุกชนิด, endpoint scope, Bypass, ป้องกัน config injection, คืนค่าไฟล์/settings และรักษา config เดิม
Tk Linux smoke check: หน้าปกติ/เล็กและแท็บ Windows ผ่าน; ฟอนต์ไทย Linux ยังไม่ใช้ยืนยัน Windows
ยังไม่ได้รัน PowerShell setup, APO หรือเสียงจริงบน Windows และยังไม่ได้สร้าง EXE

อ้างอิงทางการ:
https://sourceforge.net/p/equalizerapo/wiki/Documentation/
https://sourceforge.net/p/equalizerapo/wiki/Configuration%20reference/

# 0.5.68 — แผง EQ แบบเครื่องเสียงและ LED Windows Mix

- แผงสไลเดอร์จริง 8 ช่อง มีความถี่ ค่า Gain และสเกล dB
- แท็บแผง EQ / กราฟ / แบนด์ / ระดับเสียง / Preset และปุ่มหลักตรึงท้าย
- ปรับค่าจากช่องตัวเลขและสไลเดอร์ให้แสดงตรงกัน; ตัวกรอง Cut/Notch ไม่เปิดสไลเดอร์ Gain
- LED L/R อ่าน sample peak จาก Windows default-speaker WASAPI loopback ทุกโปรแกรมที่ออกอุปกรณ์นั้น
- แสดง dBFS, peak hold 1 วินาที, ไฟเตือนระดับแตะ/เกิน 0 dBFS ค้าง 1 วินาที
- ไฟเตือนไม่ใช่ true-peak meter และไม่สามารถยืนยันการ clip ที่เกิดก่อนจุดวัด
- ระดับนี้เป็นสัญญาณดิจิทัล ไม่ใช่ SPL/เสียงทางกายภาพ และไม่ได้รวมเสียงคนละ output endpoint
- ชื่ออุปกรณ์ปรากฏบนมิเตอร์ ตรวจการเปลี่ยนลำโพงเริ่มต้นประมาณทุก 1 วินาทีขณะได้รับเฟรม
- รับเสียงเฉพาะเมื่อแผงมิเตอร์แสดงอยู่ ไม่บันทึกไฟล์เสียงหรือส่งข้อมูลออก
- เมื่อไม่มีข้อมูลหรือมีข้อผิดพลาดแสดงสถานะ ไม่มีไฟจำลอง
- EQ ยังปรับเฉพาะเพลง X-Stage ไม่ใช่ system-wide EQ; ขอบเขต audio engine อื่นเหมือน 0.5.67

ทดสอบ 471 รายการ ผ่าน 465 ข้าม 6; Tk Linux smoke check ที่หน้าต่างปกติและขนาดเล็กผ่าน
ยังไม่ได้ยืนยันฟอนต์ไทย/เสียง loopback และอุปกรณ์ Windows จริง; ต้องทดสอบก่อนใช้งานสด
ทดสอบเพิ่มเติม: เปิดเพลงจากเบราว์เซอร์ขณะ X-Stage หยุด LED ต้องขึ้น, ปิดเสียงแอปต้นทางต้องลด,
เปลี่ยน output default ต้องแสดงอุปกรณ์ใหม่, ปิด EQ ต้องหยุด worker, เปิดกลับต้องเริ่มใหม่
ต้องติดตั้ง SoundCard ตาม requirements.txt และ Windows endpoint ต้องรองรับ loopback

# 0.5.67 — หน้าต่าง EQ เพลง 8 แบนด์

- กราฟผลรวมแบบ logarithmic และจุดแบนด์ลากได้; เลือกปรับทีละแบนด์
- โหมดง่าย/ขั้นสูง, 6 ชนิดตัวกรอง, Preamp/Output, Headroom แบบกดสั่ง
- ชุดร่าง A/B, Undo, Flat, คืนค่า และนำเข้า/ส่งออก Preset JSON ที่ตรวจรูปแบบ
- ปุ่มท้ายตรึงอยู่กับหน้าต่าง และเนื้อหาปรับความกว้างตาม viewport
- เชื่อม BASS FX biquad ต่อสตรีมเพลง ตรวจ ctypes ABI และ rollback เมื่อส่งค่าไม่สำเร็จ
- ขอบเขตจำกัด EQ เพลง: ยังไม่มี Master Bus รวม, Limiter, RTA หรือเลือก Pre/Post recording
- ตรวจรายละเอียดและข้อจำกัดที่ VERIFY_0567_TH.md

# 0.5.66 — ตรึงปุ่มบันทึกเสียงให้เข้าถึงได้

- ย้ายปุ่มเริ่ม/จบบันทึกออกจากเนื้อหาที่เลื่อนได้ไปยัง footer ด้านล่างที่สงวนพื้นที่ก่อน content
- ปรับหน้าต่าง EQ และตรวจระบบเสียงในลักษณะเดียวกัน ปุ่มใช้ค่า ทดสอบ และบันทึกรายงานไม่อยู่ท้ายพื้นที่เลื่อน
- ซ่อนช่องระดับไมค์/ดนตรีในโหมดอุปกรณ์เดียว แสดงเมื่อเลือกผสมเสียงเท่านั้น
- แก้การติดตาม Spinbox ที่อยู่ในแถวย่อย ให้ปิดการแก้ระดับเสียงขณะบันทึกและคืนสถานะถูกต้องเมื่อจบ
- ตรวจโค้ด SoundFont, เมดเล่ย์, รีโมท, งานนำเข้า, FX และทดสอบประสิทธิภาพเสียง: มีปุ่มหลักใน footer แล้ว
- ทดสอบ callback/โครงสร้าง widget อัตโนมัติ ยังไม่ได้ตรวจภาพ Windows จริง

# 0.5.65 — จัดหน้าต่างและตารางให้ปรับตามพื้นที่

- หน้าต่าง DialogWindow ปรับข้อความที่กำหนด wraplength ให้ตามความกว้างหน้าต่าง และคืนความกว้างเมื่อขยายกลับ
- SoundFont Mapping ย้ายช่องเลือกเสียงเข้าพื้นที่เลื่อนได้ ท้ายหน้าต่างมีเฉพาะปุ่ม จัดกล่องเลือกเสียงแยกชัด พร้อมตารางเลื่อนสองแกน
- ตาราง SoundFont, เพลงซ้ำ, แทรกคิว และประวัติเพิ่มแถบเลื่อนแนวตั้ง/แนวนอน
- ปุ่มเมดเล่ย์ใช้แถบที่ขึ้นแถวใหม่ได้ รีโมทจัดปุ่มใหม่ทันทีเมื่อปรับขนาด
- แถบปุ่มส่วนกลางคำนวณใหม่เมื่อมีปุ่มเพิ่มหรือข้อความเปลี่ยน แม้จำนวนคอลัมน์เดิม
- ช่องระดับเสียงไมค์/ดนตรีแยกเป็นสองแถว ลดการเบียดบนจอแคบ
- ความสูงแถวค้นหา ตารางหลัก SoundFont และงานนำเข้า อิงความสูงฟอนต์เพื่อรองรับภาษาไทยและ DPI
- MIDI input ใช้หน้าต่างส่วนกลางที่จำกัดขนาดตามจอ ปรับช่องเลือกให้ยืดตามพื้นที่
- ยังไม่ได้ตรวจภาพบน Windows จริงหรือรับรองทุก DPI โปรดอ่าน UI_AUDIT_0565_TH.md

# 0.5.64 — รีเฟรชเสียง / ตรวจเพลงเตรียมไว้ / เลือก Preset จริง

- บันทึกหน้าระบบเสียงแล้วปิดเสียงทดลองเก่า และทิ้งเฉพาะคิวโหลดรอเพื่อใช้ค่าใหม่ เพลงปัจจุบันและหาง Crossfade ยังเล่นต่อ
- ก่อนรับ deck ตรวจรหัส คีย์ ความเร็ว พาธ เวลาแก้ไข ขนาดไฟล์ การตั้งค่า และสถานะปิดทำนอง หากไม่ตรงจะโหลดตามปกติ
- เพิ่มรายการ Bank/Preset จาก metadata ของ SF2 ในหน้าจับคู่กลุ่ม GM ส่งค่า source/destination ด้วย BASS_MIDI_FONTEX
- เลือก Preset เฉพาะใช้เสียงเดียวกันทั้งกลุ่ม ไม่ใช่การกำหนดราย Program แบบอิสระ
- แบบตามหมายเลข GM ใช้เฉพาะ preset ที่มีจริงใน SF2 หมายเลขที่ขาดปล่อยให้ชุดสำรองทำงาน ไม่บังคับใช้ preset แรก
- SFZ ไม่แสดงรายการ Bank/Preset ยังใช้รูปแบบจับคู่เดิม
- ตรวจ preset ที่เลือกก่อนเปิดเสียง ปฏิเสธรายการที่หายหรือไม่ถูกต้อง เก็บ mapping แบบเดิมได้
- ยังไม่ได้ทดสอบ Windows GUI, เสียงจริง, MIDI input และ EXE; การตรวจ preload เป็น metadata ไม่ใช่ hash เนื้อหา

# 0.5.63 — SoundFont Mapping ส่งถึงตัวเล่นจริง

- แก้ BassSynth ให้ส่ง instrument_fonts ไปยัง BASS_MIDI_StreamSetFonts: กลุ่ม GM ที่เลือกมีลำดับก่อนชุดเสียงสำรอง และแยกชุดกลอง Bank 128
- ครอบคลุมเพลงหลัก เพลงโหลดล่วงหน้า/กลองเมดเล่ย์ และคีย์บอร์ดที่ใช้ BassSynth
- ตรวจ mapping ที่อ้างไฟล์ถูกนำออกก่อนเปิดอุปกรณ์เสียง พร้อมทดสอบคืนทรัพยากรเมื่อ native API ล้มเหลว
- บันทึกใช้ค่าของกลุ่มที่กำลังเลือกโดยตรง ไม่ต้องกดใช้กับกลุ่มก่อนบันทึก
- เมื่อบันทึก เปลี่ยนเฉพาะเพลงถัดไป: ทิ้ง deck ที่รอโหลด เปิดใหม่ด้วยค่าใหม่ และปิด synth ทดลองเพื่อใช้ค่าใหม่เมื่อเล่นโน้ตครั้งถัดไป ไม่ปิดเพลงหลักหรือเพลงที่อยู่ในช่วง Crossfade
- ยังเป็นการจับคู่ตามกลุ่ม GM ไม่ใช่เลือก source Bank/Preset อิสระรายเครื่องดนตรี
- Native BASS อาจใช้ preset แรกเมื่อไม่มีหมายเลขตรงตามกลุ่ม จึงควรเลือก SF2 ที่มีเสียง GM ของกลุ่มนั้น
- ยังไม่ได้ตรวจ Windows GUI/EXE/เสียงจริง ไม่รับรองรอยต่อไร้ช่องว่างทุกอุปกรณ์

# 0.5.62 — โหมดเล่นคีย์บอร์ดชัดเจนและรายงานรอยต่อเพลง

- เพิ่มตัวเลือก เล่นคีย์บอร์ด / ค้นหาเพลง บนแผง เมื่อเล่น ตัวอักษรที่ไม่ได้เป็นโน้ตจะไม่หลุดไปค้นหา
- คลิกแป้นหรือเลือกเล่นคีย์บอร์ดเพื่อเข้าโหมดเล่น กด Esc / เลือกค้นหา / ย้ายโฟกัสเพื่อกลับโหมดค้นหา และปล่อยโน้ตจากแป้นคอมพิวเตอร์
- บันทึกเหตุการณ์ขอเริ่มเพลง เริ่มเล่น ล้มเหลว จบเพลง ขอโหลดล่วงหน้า และโหลดพร้อม/ล้มเหลว เก็บล่าสุด 200 เหตุการณ์ในหน่วยความจำ
- เมดเล่ย์ / ต่อเพลง มีปุ่ม รายงานการต่อเพลง… ส่งออก JSON พร้อมรุ่น ระบบปฏิบัติการ backend และตัวเลือกเมดเล่ย์ ไม่ส่งรายงานออกเครือข่ายอัตโนมัติ
- รายงานเป็นเวลาการทำงานของซอฟต์แวร์ ไม่ใช่ผลวัดเสียงจากลำโพง ยังไม่ได้ทดสอบ Windows GUI/เสียง/MIDI จริง
- คงการแก้ใช้เพลงที่โหลดรอไว้จาก 0.5.61 ไม่เพิ่มการรับรองว่า gapless ทุกไฟล์

# 0.5.61 — แก้เพลงที่โหลดล่วงหน้าถูกทิ้งเมื่อจบเพลง

- จบเพลงตามปกติหรือ Mark Out แบบไม่ซ้อนเสียง ใช้ deck ของคิวถัดไปที่พร้อมแล้ว ไม่ปิดทิ้งแล้วโหลดซ้ำ
- โหลดล่วงหน้าเมื่อเปิดเมดเล่ย์ได้ทั้งแบบ Crossfade และแบบต่อธรรมดา สำหรับ MIDI/SoundFont และ WAV/MP3 ผ่าน BASS
- ตรวจรายการคิว คีย์ และความเร็วก่อนรับ deck และล้างสถานะชั่วคราวแม้เริ่มเพลงไม่สำเร็จ
- รักษาตัวเลือกเปิด/ปิดเมดเล่ย์เดิม: เปิดได้ที่เมนูเมดเล่ย์ / ต่อเพลง หากต้องการซ้อนเสียงให้เปิด Crossfade และตั้ง Fade มากกว่า 0
- เพิ่มการทดสอบจบแล้วเล่นต่อ 3 เพลง โดยตรวจว่าไม่โหลดซ้ำและปิดเฉพาะเครื่องเล่นเก่า
- ยังไม่ได้ตรวจ Windows/อุปกรณ์เสียงจริง ไม่ยืนยันว่าแก้สาเหตุการหยุดบนเครื่องผู้ใช้ได้ทุกกรณี

# 0.5.60 — แผงตรึง / เล่นคอร์ด / MIDI input / Crossfade

- ปุ่ม × กว้าง 28 พิกเซลชิดขวา ไม่ยืดตามแถว; ปุ่มตรึงแยกข้างกัน พื้นที่คงเหลือแสดงโน้ต
- ปุ่มตรึงค้างแผงไว้ ยกเลิกแล้วซ่อนเมื่อเมาส์ออก; F4 ยังเปิดค้าง/ซ่อน
- คลิกแป้นให้โฟกัส แล้วใช้ A W S E D F T G Y H U J K O L P เล่น MIDI60–75 พร้อมกันเป็นคอร์ด ปล่อยหยุดโน้ต Esc ออกจากโหมดเล่นกลับไปค้นหา ใช้แป้นภาษาอังกฤษ
- เสียงทดลองใช้ SoundFont ที่ตั้งไว้เมื่อมีไฟล์ พร้อมเพลงได้ผ่านสตรีมแยก; หากไม่ตั้ง SoundFont ใช้ Microsoft GS แต่ไม่ทดลองร่วมเพลงที่ออก Windows MIDI
- MIDI IN เลือกอุปกรณ์ WinMM รับ Note On/Off, velocity, sustain, pitch bend ส่งเข้าเสียงทดลองเดียวกัน ไม่รองรับ SysEx/MIDI Clock และไม่บันทึก MIDI
- เมดเล่ย์เพิ่มตัวเลือกโหลดล่วงหน้า/Crossfade สำหรับ MIDI ผ่าน BASS SoundFont และ WAV/MP3 ผ่าน BASS FX เพลงเก่ากับใหม่มีเสียงซ้อนช่วง Fade
- คงกลอง: วนหนึ่งห้องกลองล่าสุดที่มีโน้ตจากไม่เกินสี่ห้องก่อนจุดต่อ MIDI แล้วปิดกลองของเพลงใหม่ชั่วคราว เปลี่ยนความเร็วตาม BPM ภายในขอบเขต 50–150%; ไม่ใช่ Arranger/Fill และไม่ใช่ beat-matching สองเพลงเต็มรูปแบบ
- วิดีโอ/Windows MIDI หรือเพลงถัดไปโหลดไม่ทันใช้การต่อคิวเดิม การโหลดล่วงหน้าลดเวลารอยต่อ แต่ยังไม่รับรอง sample-accurate gapless หรือความหน่วงจริงบน Windows
- ยังไม่ได้ทดสอบการฟังเสียง อุปกรณ์ MIDI และหน้าต่างจริงบน Windows

# 0.5.59 — จำนวนแป้นอัตโนมัติตามพื้นที่จอ

เริ่มต้นโหมดอัตโนมัติ: ใช้ 128 แป้นเมื่อพื้นที่แป้นขาวไม่น้อยกว่า 15 logical pixels ต่อแป้น มิฉะนั้นใช้ 61 แป้น คำนึงถึง DPI และปรับเมื่อย่อ/ขยายหน้าต่าง เลือก 61/128 เองได้และจำโหมดใหม่ ไม่ใช้ค่าเริ่มต้นตายตัวเดิม

# 0.5.58 — ความกว้างแผงคีย์บอร์ดตามพื้นที่ว่าง

แผงลอยกึ่งกลางด้านบน เว้นพื้นที่ด้านซ้ายและขวา ลดความกว้างตามหน้าต่าง และจัดปุ่มลงแถวถัดไปเมื่อพื้นที่ไม่พอ โดยไม่เลื่อนจอเดิม

# 0.5.57 — คีย์บอร์ดลอยกึ่งกลางขอบบน

- แสดงคีย์บอร์ดด้านหน้าจอที่กึ่งกลางชิดขอบบน ไม่มีไตเติลบาร์
- ใช้ความกว้างกระชับตามแถบปุ่ม ไม่ขยายเต็มจอ และจำกัดไม่เกินหน้าต่าง
- เปิด/ปิดแผงโดยไม่เปลี่ยนขนาดหรือเลื่อนพื้นที่เพลง คิว ค้นหา และเนื้อร้อง
- คง 61/128 แป้น, −Oct/+Oct, Fx1–10, เลือกเครื่องดนตรี, โน้ตสีแดง และ F4

## 0.5.56 — 61/128 แป้นและพื้นที่แยก

- ค่าเริ่มต้น 61 แป้น C2–C7 เลือก 128 แป้นได้ จำจำนวนและช่วงเสียงใน settings
- −Oct/+Oct เลื่อนช่วงครั้งละ 12 ครึ่งเสียงในโหมด 61 แป้น ไม่เปลี่ยนคีย์เพลง; โหมด 128 แป้นปิดปุ่มเลื่อน
- แป้นที่เล่นยังเป็นสีแดง แสดงลูกศรในชื่อโน้ตหากมีโน้ตนอกช่วงที่มองเห็น
- ใช้แผง pack แยกเหนือ surface ของหน้าหลัก ทำให้จอร้อง/วิดีโอ/ค้นหา/คิวใช้พื้นที่ที่เหลือและไม่ถูกแผงทับ ซ่อนแล้วคืนพื้นที่ จอร้องแยกไม่ถูกลดพื้นที่
- Hover ขอบบนรอ 300ms และตรวจตำแหน่งซ้ำก่อนเปิด; F4 เปิดค้าง/ซ่อน

## 0.5.55 — FX และเครื่องดนตรีอยู่แถวเดียวกัน

- ย้าย Fx1–Fx10, เลือกแชนเนล, เลือกเครื่องดนตรี, ชื่อโน้ต และปิดแผง มาไว้แถวเดียวด้านบน
- ลด padding และขนาดปุ่ม FX ให้กะทัดรัด พื้นที่ชื่อโน้ตขยายตามพื้นที่ที่เหลือ
- คงการแสดงโน้ตจากเพลง MIDI ตามการเล่นจริงเป็นสีแดง รวมโน้ตที่ทดลองด้วยเมาส์; ไม่เปลี่ยนจังหวะหรือส่งโน้ตของเพลงซ้ำ
- F4 และเปิดแผงด้วยเมาส์ยังทำงานเหมือนเดิม

## 0.5.54 — Fx1–10 และคีย์บอร์ดเล่นเสียง

- FX 10 ปุ่มขนาดเล็ก Fx1–Fx10 อ่าน 01–10.wav หรือ .mp3 ใน SoundFx ข้าง Data (ค่าติดตั้งปกติ D:\newKaraoke\Karaoke\SoundFx); ไม่แก้หรือทับเสียงของผู้ใช้ ถ้ามีทั้งสองเลือก WAV ก่อน รองรับนามสกุลตัวใหญ่ ไฟล์ยาวได้ไม่เกิน 60 วินาที
- ตัวติดตั้งสร้างโฟลเดอร์ SoundFx ว่าง ให้ใส่ไฟล์ของคุณเอง ไม่ได้นำเสียง FX เก่ามาเปลี่ยนชื่อหรือสร้างเสียงเพิ่ม 10 เสียง
- แสดงชื่อโน้ตที่กำลังเล่นในพื้นที่ควบคุมด้านบน ลบปุ่มหยุด FX เพิ่มรายการเลือกเครื่องดนตรี GM ที่ใช้บ่อย 18 เสียง
- คลิกค้าง/ลากเมาส์เล่นโน้ตจริง ปล่อยหรือเลื่อนออกหยุดเสียง C4=MIDI60 ทุกแป้นครึ่งเสียง คงคีย์จริงของแป้น ไม่ transpose ตามเพลง
- เสียงทดลองใช้ Microsoft GS Wavetable Synth ของ Windows แยกจาก SoundFont; หากไม่พบ synth จะแจ้งข้อผิดพลาด ไม่เปลี่ยนไปใช้อุปกรณ์ MIDI ภายนอก
- ขณะเพลงเล่นผ่าน Windows MIDI จะบล็อกการทดลองเพื่อไม่เปลี่ยนโปรแกรม/ตัดโน้ตของเพลง ใช้ทดลองระหว่างเพลงผ่าน SoundFont ได้; ปิดเสียงทดลองก่อนเริ่มเพลงใหม่
- F4 เปิดแผงค้าง/ซ่อน ชี้เมาส์เปิดแบบซ่อนอัตโนมัติได้เดิม สีโน้ตยังเป็นแดง ปิดแผงแล้วปล่อยเสียงทดลอง แต่ FX เล่นต่อจนจบ
- เล่นด้วยเมาส์ครั้งละหนึ่งโน้ต ไม่ใช่ polyphonic computer-keyboard input; ยังไม่มี MIDI input/velocity จากคีย์บอร์ดจริง

## 0.5.53 — คีย์บอร์ดซ้อนด้านบนและ FX

- ชี้เมาส์ขอบบน 28 พิกเซลของหน้าหลักเพื่อเปิดแผง เมื่อไม่มีหน้าค้นหาหรือคิวซ้อนอยู่ เลื่อนเมาส์ออก 0.5 วินาทีเพื่อซ่อน หรือกด ×
- ใช้ Frame ภายในหน้าหลัก ไม่มี title bar ไม่มีคำบรรยายบรรทัดล่าง แสดงครบ MIDI 128 โน้ตพอดีความกว้าง ไม่ต้องเลื่อน
- โน้ตที่เล่นเป็นสีแดง #ff354b; เลือกทุกแชนเนลหรือ 1–16 ได้
- FX 4 ปุ่มกระจายเต็มแถวด้านบน ใช้ไฟล์จากเมนูเอฟเฟกต์เดิม ความดัง 60% มีหยุด FX; ซ่อนแผงแล้วเสียง FX เล่นต่อจนจบ
- เป็นคีย์บอร์ดดู MIDI ไม่ใช่คีย์บอร์ดคลิกเล่นโน้ต

## 0.5.52 — หน้าต่างคีย์บอร์ด MIDI

- คลิกขวา → คีย์บอร์ด MIDI… เปิดหน้าต่างแยก เลือกทั้งหมดหรือแชนเนล 1–16 และเลื่อนแนวนอนดูโน้ต MIDI 0–127
- ไฮไลต์โน้ตที่ส่งสำเร็จหลัง transpose/mute/solo; Ch10 กลองไม่ transpose; แสดงชื่อโน้ต C4=60
- ติดตาม Note On/Off, velocity zero, Sustain, all sound off/reset; ล้างเมื่อพัก หยุด เปลี่ยนคีย์ seek และจบเพลง
- เก็บสถานะด้วย lock สั้น ไม่มี Tk call จากเธรดเสียง; UI อ่านสถานะทุก 33ms เฉพาะเปิดหน้าต่าง อาจไม่แสดงโน้ตสั้นมากระหว่างเฟรม
- เป็น read-only monitor ไม่ส่งเสียงด้วยเมาส์ ไม่มี piano roll timeline และไม่วิเคราะห์โน้ตจาก MP3/วิดีโอ
- โน้ตที่ขยับไม่ยืนยันว่าได้ยินเสียงจริงหรือฮาร์ดแวร์ปกติ

## 0.5.51 — รายละเอียดเพลงมุมซ้ายบนใหญ่ขึ้น

- ชื่อเพลง 16 → 20 พิกเซล ศิลปินและรายละเอียด 13 → 16 พิกเซล
- ปรับระยะบรรทัดเป็น y=87/119/147 และคงการตัดข้อความยาวให้พอดีพื้นที่

## 0.5.50 — ยกเลิกแล้วต่อคิวทันที

- กดยกเลิกเพลงที่กำลังเล่น: ปิดเพลงเดิม บันทึกประวัติ interrupted แล้วเริ่มเพลงแรกในคิวทันที ไม่รอนับถอยหลัง 5 วินาที
- เมื่อจบเพลงต่อคิวตามลำดับจนหมด คิวว่างแล้วล้างชื่อเพลงและเนื้อร้อง
- แยกการหยุดภายใน advance=False สำหรับลัดคิวและข้อผิดพลาดระบบเสียง ไม่ให้เริ่มหัวคิวแทรกหรือวนซ้ำ คงคิวเมื่อระบบเสียงล้มเหลว
- การต่อคิวเป็นการเล่นเพลงถัดไปต่อเนื่อง เวลาโหลดไฟล์/SoundFont ยังขึ้นกับเครื่อง ไม่รับรอง gapless; การ fade/mark-out ยังใช้ค่าหน้าเมดเล่ย์เดิม

## 0.5.49 — โลโก้ใหม่และ Enter ระหว่างค้นหา

- เปลี่ยน assets/xstage-logo.jpg เป็นภาพใหม่จากผู้ใช้โดยคงไฟล์ต้นฉบับ สร้าง ICO 7 ขนาดจากภาพเดียวกัน ใช้กับหน้าต่าง จอร้อง เกี่ยวกับโปรแกรม หน้ารีโมท และทางลัด
- พื้นหลังเวทีเป็นภาพคนละไฟล์ ยังคงภาพเวทีเดิม
- รับ Enter/Ctrl+Enter ขณะรอผลค้นหา แทนการทิ้งคำสั่ง; ส่งงานค้นหาที่รอ idle ทันที และทำคำสั่งครั้งเดียวเมื่อผล revision ล่าสุดพร้อม
- เปลี่ยนคำค้นหรือปิดหน้าค้นหาแล้วล้างคำสั่งค้าง ไม่เล่นผลเก่า ไม่ทำงานเมื่อไม่มีผลค้นหา
- ยังค้นหาบน worker เพื่อไม่บล็อกหน้าจอ ไม่เปลี่ยนเงื่อนไข Enter เล่นเมื่อว่าง/เพิ่มคิวเมื่อมีเพลง หรือการโหลด SoundFont
- ต้องติดตั้งใหม่และเริ่มโปรแกรมใหม่เพื่อโหลดโลโก้ใหม่ทุกจุด

## 0.5.48 — แก้ build test บน Windows ที่มีพาธชื่อย่อ

- จาก build-tests(3).log: test_frozen_assets_fall_back_to_bundle เปรียบเทียบ TEMP ชื่อย่อ 8.3 (7738~1) กับชื่อภาษาไทยเต็ม ทั้งที่เป็นตำแหน่งเดียวกัน
- ปรับ fixture ให้ resolve พาธก่อนทดสอบ สอดคล้องกับการ resolve ตำแหน่ง EXE ใน branding.asset; ไม่ข้ามการทดสอบและไม่เปลี่ยนพฤติกรรมโปรแกรม
- จำลองพาธ alias บน Linux: ทดสอบรุ่นเดิมล้มเหลว 1 จุด รุ่นแก้ผ่าน; ไม่ใช่การทดสอบ Windows 8.3 จริง
- คงการแก้ไอคอนและทางลัดรุ่น 0.5.47 ทั้งหมด ต้องแตก ZIP และรัน Install-to-D.cmd ใหม่

## 0.5.47 — แก้ไอคอนโลโก้ว่าง

- แปลงโลโก้เดิมเป็น ICO แบบ 32-bit DIB 7 ขนาด 16–256 พิกเซล แทน PNG-only ICO; ตรวจทุกเฟรมว่าไม่โปร่งใสหรือว่าง
- ตั้ง iconbitmap ทั้งหน้าต่างปัจจุบันและค่าเริ่มต้นหน้าต่างย่อย หากโหลดไม่ได้ให้ใช้ภาพโลโก้สำรอง และเก็บ reference ภาพไว้
- ค้นหา assets ข้าง EXE และในโฟลเดอร์ bundle ของ PyInstaller พร้อมรวม assets ใน build
- ตัวติดตั้งสร้าง X-Stage Karaoke.lnk ในโฟลเดอร์ติดตั้ง พร้อม IconLocation ชี้โลโก้โดยตรง ไฟล์ CMD เดิมยังใช้ได้แต่ไม่มีไอคอนกำหนดเอง
- ปิดโปรแกรมเดิม แตก ZIP แล้วรัน Install-to-D.cmd ใหม่ เปิดจาก X-Stage Karaoke.lnk; หากปักหมุดทางลัดเก่า ให้ถอนหมุดแล้วปักหมุดทางลัดใหม่
- ผลทดสอบ 410 รายการ ผ่าน 404 ข้าม 6 ไม่ได้สร้าง EXE หรือทดสอบหน้าต่างบน Windows จริง

## 0.5.46 — แก้ Error 0x100000001 ขณะตรวจเสียง

- แก้ลำดับเริ่ม SoundCard 0.4.6: รุ่นเดิมเรียก CoInitializeEx ก่อน import ทำให้ import เริ่ม COM ซ้ำ ได้ S_FALSE=1 แล้วไลบรารีรายงานเป็น Error 0x100000001
- โหลด SoundCard ครั้งแรกบนเธรดใหม่ และคืน reference ที่ไลบรารีสร้างบนเธรดเดียวกัน จากนั้นจัดการ COM แยกตามอายุงานเสียงแต่ละเธรด
- ใช้วิธีเดียวกันกับตรวจลำโพง บันทึกไมค์ผสมดนตรี และรับเสียงสำหรับมือถือ รองรับ STA ที่เปิดไว้แล้วโดยไม่ปิด COM ของส่วนอื่น
- ไม่กลืนข้อผิดพลาด HRESULT จริง เพิ่ม traceback และประเภทข้อผิดพลาดในรายงาน JSON และบันทึกโปรแกรม
- คืน/รอเธรดเสียงทดสอบแม้การอ่าน loopback ล้มเหลว
- จำลองด้วยคลาส COM จาก SoundCard 0.4.6 ที่ดาวน์โหลดมาตรวจ: ลำดับเดิมเกิด Error 0x100000001 ลำดับใหม่โหลดสำเร็จและคืน reference ครบ
- ยังไม่ได้ทดสอบ Windows/อุปกรณ์เสียงจริง จึงไม่ถือว่ารับรองไดรเวอร์หรือฮาร์ดแวร์ของเครื่องผู้ใช้แล้ว

## 0.5.45 — คิว/ประวัติ ช่องเสียง SoundFont FX เมดเล่ย์ และไอคอน

- เพิ่มแทรกเพลงตามตำแหน่งคิว และประวัติ 500 รายการที่นำกลับเข้าคิวได้ พร้อมคีย์/ผู้ร้อง/ความเร็ว
- เพิ่มช่องเสียงต้นฉบับซ้าย/ขวาสำหรับ BASS FX และคำสั่งช่อง/แทร็กเสียง MCI เมื่อ codec รองรับ
- เลือก SoundFont ตาม 16 กลุ่ม GM Bank 0 และชุดกลอง Bank 128; นำไฟล์ออกแล้วล้างเฉพาะ mapping ที่อ้างไฟล์นั้น
- เพิ่มแผง FX 4 ปุ่มพร้อมเสียงสังเคราะห์ต้นฉบับ เลือกไฟล์เองได้ และหยุด/จำกัดเสียงซ้อน
- เพิ่มเมดเล่ย์ Mark Out ตามห้อง MIDI, Fade out/in และคง BPM ภายในช่วง 50–150%; ยังไม่ใช่ Crossfade/Keep Rhythm เต็มรูปแบบ
- ใช้โลโก้เป็นไอคอน Tk ทุกหน้าต่าง และเพิ่ม ICO หลายขนาดในขั้นตอนสร้าง EXE
- เมนูใหม่รวมที่ เครื่องมือ → คิวและการแสดง ดู PERFORMANCE_GUIDE_TH.md
- ASIO/VST/DMX ยังไม่รวม และยังไม่ได้ทดสอบ Windows GUI/เสียงจริงหรือสร้าง EXE จากสภาพแวดล้อมนี้

## 0.5.44 — เพิ่มระบบเสียงและปิดช่องว่างเมนูที่ทำได้ในรุ่นนี้

- WAV/MP3 ใช้ BASS FX เพื่อปรับคีย์แยกจากความเร็ว รวมคิวแยกรายเพลงและรีโมทเมื่อมี native DLL พร้อม; Setup-Audio.ps1 เพิ่มดาวน์โหลด BASS FX x64
- เพิ่มเครื่องมือ → ปรับเสียง EQ 3 ย่าน สำหรับ SoundFont/BASS FX บันทึกค่าและคืนค่าเดิมได้
- เพิ่มบันทึกไมค์ผสมเสียงลำโพง Windows เป็น stereo WAV พร้อมระดับเสียง เวลา รายงาน clipping และหยุดเมื่อบัฟเฟอร์/อุปกรณ์ผิดปกติ
- เพิ่มเครื่องมือ → ตรวจระบบเสียง ตรวจ DLL และทดสอบเสียง output ผ่าน Windows loopback พร้อมส่งออกรายงาน
- ป้องกันเล่นเพลง/เริ่มบันทึกระหว่างตรวจ output; ตรวจรูปแบบไฟล์และคืนทรัพยากรเมื่อโหลดล้มเหลว
- แก้ version resource ของ EXE ให้ตรงกับเลขรุ่น และทำ tests ของความสามารถปรับคีย์ไม่ขึ้นกับ DLL ที่ผู้ใช้ติดตั้งไว้
- รวมกู้คืนข้อมูล รีโมทแบบแบ่งหน้า และการแก้ CP874 ของรุ่นก่อนหน้า
- ชุดทดสอบ 382 รายการ ผ่าน 376 ข้ามตามแพลตฟอร์ม 6 ไม่มี failures/errors; ทดสอบรีโมทใน Chromium ผ่าน
- ยังไม่ใช่ฟังก์ชันครบทุกระบบ: ASIO/VST/audio bus, medley/fill/electone, DMX/ตู้หยอดเหรียญ และตัวถอดรหัสเฉพาะยังไม่รองรับ
- ยังไม่ได้รัน Windows GUI/เสียงจริง/สร้าง EXE ดู AUDIO_TOOLS_TH.md และ WINDOWS_CHECK_TH.md ก่อนใช้หน้าเวที

## 0.5.43 — แก้ Build บน Windows ภาษาไทย

- แก้ tests/test_restore.py ให้อ่าน settings.json และ queue.json ด้วย UTF-8 อย่างชัดเจนทั้ง 4 จุด
- สาเหตุจาก log: Python 3.13 บนเครื่องใช้ CP874 เป็นค่าเริ่มต้น ทำให้อ่านข้อมูลภาษาไทยในไฟล์ UTF-8 ไม่ได้ เกิด UnicodeDecodeError ใน 2 tests
- จำลอง Path.read_text ที่ใช้ CP874 เมื่อไม่ระบุ encoding: รุ่นเดิมเกิด errors=2 ตรงกับรายงาน รุ่นแก้ผ่าน restore tests ทั้ง 5
- ชุดทดสอบเต็ม 367 รายการ: ผ่าน 361 ข้าม 6 ไม่มี errors/failures ไม่ปิดหรือข้าม tests ที่เคยล้มเหลว
- ไม่ต้องเปลี่ยนชื่อบัญชี Windows ภาษาเครื่อง หรือรุ่น Pythonเพื่อแก้ข้อผิดพลาดนี้
- การแก้นี้อยู่ในไฟล์ทดสอบ โค้ดกู้คืนจริงระบุ UTF-8/UTF-8-SIG ไว้แล้ว
- ยังไม่ได้สร้าง EXE หรือทดสอบ Windows GUI/เสียงจริงจากสภาพแวดล้อมนี้

## 0.5.42 — กู้คืนข้อมูลและจัดหน้าต่าง SoundFont

- เครื่องมือ → กู้คืนข้อมูล: ตรวจ SQLite/settings/queue และแสดงจำนวนก่อนยืนยัน เตรียมไฟล์แยก แล้วใช้ตอนเปิดโปรแกรมครั้งถัดไป
- ต้องหยุดเพลง การบันทึก รีโมท และงานสร้างรายการก่อน พร้อมปิด X-Stage หน้าต่างอื่นทั้งหมด
- เก็บสำรองข้อมูลปัจจุบันใน Data/restore-safety-... ก่อนแทนข้อมูล ย้อนกลับเมื่อเขียนล้มเหลวหรือกู้คืนถูกขัดจังหวะ
- คืนฐานข้อมูล คิว และการตั้งค่า ไม่รวมไฟล์เพลง SoundFont หรือ DLL ซึ่งต้องอยู่ตำแหน่งเดิม
- SoundFont แยก 4 แท็บ: ชุดเสียง / คุณภาพ / เอฟเฟกต์ / ทดสอบ ลดขนาดตั้งต้น ข้อความปรับบรรทัดตามความกว้าง ปุ่มจัดแถวตามพื้นที่
- ย้ายการวัดประสิทธิภาพและทดลองเสียงไปแท็บทดสอบ ระบุชัดว่าการวัดสังเคราะห์ PCM ไม่ใช่ latency ที่ลำโพง
- ผ่าน 361 จาก 367 tests; ข้าม 6 ไม่มี failures/errors
- ยังไม่ได้ตรวจรีโมท Windows GUI หรือเสียง/บันทึกเสียงบนเครื่องจริง ไม่มีช่องทางเข้าถึงเครื่อง Windows ในเซสชันนี้ ดู WINDOWS_CHECK_TH.md สำหรับขั้นตอนตรวจ

## 0.5.41 — แบ่งหน้าตั้งค่ารีโมทตามพื้นที่

- วัดความสูงของหัวข้อและตัวเลือกจริง แล้วย้ายทั้งกลุ่มไปหน้าถัดไปเมื่อพื้นที่ไม่พอ
- ปุ่มถัดไปและย้อนกลับเลื่อนหน้าตั้งค่า ก่อนเปิดรีโมทในหน้าสุดท้าย พร้อมแสดงเลขหน้าตั้งค่า
- คำนวณหน้าใหม่เมื่อย่อหรือขยายหน้าต่าง โดยคงตัวแปรค่าตั้งเดิม
- หัวข้อเพิ่มเติมแยกเป็นกลุ่มย่อยเพื่อแบ่งหน้าได้ และซ่อนกลุ่มที่ไม่เกี่ยวกับสถานะปัจจุบัน
- ตัวเลือกอนุมัติเรียงแนวตั้ง แถบปุ่มท้ายหน้าต่างตัดขึ้นแถวใหม่เมื่อหน้าต่างแคบ
- ปรับหน้าต่างให้พอดีเนื้อหาโดยไม่เกินพื้นที่จอ หากหัวข้อเดียวสูงเกินพื้นที่ทั้งหน้า จะอยู่หน้าเดี่ยวและเลื่อนดูได้
- รวมหน้าแรกมือถือพร้อมโลโก้จากรุ่น 0.5.40
- ทดสอบ 362 รายการ: ผ่าน 356 ข้าม 6 ยังไม่ได้ทดสอบหน้าต่างจริงบน Windows

## 0.5.40 — หน้าแรกรีโมทมือถือพร้อมโลโก้

- เพิ่มโลโก้ X-Stage เดิมในหน้าเชื่อมต่อและหน้าใส่ชื่อผู้ร้อง ส่งภาพจากเครื่องหลักโดยตรง ไม่ใช้ CDN
- จัดหน้าโทนกรมท่า ฟ้าเขียว พร้อมช่องรหัสขนาดใหญ่ ปุ่มเต็มความกว้าง และหัวข้อที่อ่านง่าย
- แสดงโลโก้ขนาดย่อ 384 พิกเซล เก็บผลไว้ในหน่วยความจำ ไม่แปลงภาพซ้ำทุกคำขอ
- เพิ่มปุ่ม Enter บนช่องรหัสเพื่อเชื่อมต่อ และปรับช่องกรอกสำหรับคีย์บอร์ดมือถือ
- ตรวจหน้าแรกใน Chromium ที่ 280, 320, 390, 430, 768 และ 844 พิกเซล ไม่พบแนวนอนล้น
- ทดสอบ 359 รายการ: ผ่าน 353 ข้าม 6 และทดสอบลำดับการใช้งานผ่านเบราว์เซอร์สำเร็จ ยังไม่ได้ทดสอบโทรศัพท์จริงหรือ Windows EXE

## 0.5.39 — ฟอนต์และตัวเลือกรีโมท

- ใช้ฟอนต์ Tahoma 12 pt สำหรับค่าตั้ง ปุ่ม และรายการรออนุมัติ เพิ่มพื้นที่กดและระยะบรรทัด
- ตัวเลือกเปิด/ปิดใช้ช่องสี่เหลี่ยม พร้อมเครื่องหมายถูกชัดเจนเมื่อเปิด
- วิธีอนุมัติและรูปแบบ QR ใช้เรดิโอวงกลม เลือกได้หนึ่งค่าในกลุ่ม
- ตัวเลือก QR เรียงแนวตั้งเพื่อให้ข้อความอ่านครบในหน้าต่างแคบ
- เครื่องหมายรองรับการขยายตาม Tk scaling และแสดงสถานะปิดใช้งานด้วยสีจาง
- คงการซ่อนปุ่มตามสถานะและ “ตั้งค่าเพิ่มเติม” ของรุ่นก่อน
- ทดสอบ 359 รายการ: ผ่าน 353 ข้าม 6 ยังไม่ได้ตรวจหน้าต่างจริงบน Windows

## 0.5.38 — ตั้งค่ารีโมทแบบกระชับ

- ตัดคำบรรยายและค่าทางเทคนิคออกจากหน้าหลัก ใช้หัวข้อสั้นและโทนสีเดียวกัน
- คงลำดับ เชื่อมต่อ → ตั้งค่า → พร้อมใช้งาน
- แสดงปุ่มเปิดสิทธิ์เฉพาะเมื่อตรวจพบว่าถูกปฏิเสธสิทธิ์ ซ่อนเมื่อพร้อมใช้งานหรือกำลังจัดการสิทธิ์
- ซ่อนปุ่มหยุดเมื่อรีโมทยังไม่ทำงาน และซ่อนแผงอนุมัติเมื่อไม่มีคำขอค้าง
- ย้ายพอร์ต จำนวนผู้ใช้ และสิทธิ์เพิ่มเติมไปยัง “ตั้งค่าเพิ่มเติม” ซึ่งพับไว้เริ่มต้น
- ซ่อนช่องกำหนดจำนวนผู้ใช้เมื่อใช้แบบอัตโนมัติ และซ่อนพอร์ตขณะรีโมททำงาน
- คงการตั้งค่า QR การอนุมัติ และเสียงมือถือ โดยบอกในชื่อสวิตช์ว่าเสียงรวมโปรแกรมอื่น
- ทดสอบ 359 รายการ: ผ่าน 353 ข้าม 6 ไม่มีข้อผิดพลาด ยังไม่ได้ทดสอบหน้าต่างจริงบน Windows

## 0.5.37 — เมนู รายละเอียดโปรแกรม และความจุรีโมท

- ลบ “ค้นหาเพลง…” จากเมนูคลิกขวา → ตัวเลือก การพิมพ์ค้นหาและคีย์ลัดยังทำงานตามเดิม
- รายละเอียดโปรแกรมใช้หน้าต่างพร้อมโลโก้ และแก้ชื่อเป็น “เทศบาลนครสงขลา จ.สงขลา”
- แสดงคุณภาพสัญญาณ Wi-Fi และความเร็วรับ/ส่งลิงก์จาก Windows พร้อมความหน่วงไปกลับที่มือถือรายงานจากคำขอสถานะจริง
- ประเมินจำนวนผู้ใช้แบบเผื่อภาระตามลิงก์ สัญญาณ การอนุญาตเสียง และความหน่วง ปรับได้อัตโนมัติ หรือผู้ดูแลกำหนดเอง 1–100 เครื่องในขั้นที่ 2
- จำนวนแนะนำเป็นสูตรประมาณ ไม่ใช่ผลทดสอบความจุเราเตอร์หรือความเร็วอินเทอร์เน็ตที่รับประกัน เมื่อไม่มีข้อมูลลิงก์เริ่มที่ 10 เครื่อง หรือ 5 เครื่องเมื่ออนุญาตเสียง
- ผู้ใช้เต็มจะแจ้ง “กรุณารอสักครู่” แล้วลองใหม่ทุก 5 วินาทีขณะที่หน้าเชื่อมต่ออยู่ด้านหน้า ไม่ได้รับประกันลำดับ FIFO สำหรับผู้ที่รอเข้า
- ไม่ใช้งานเกิน 5 นาทีจะยกเลิกเซสชัน การ poll สถานะไม่ต่ออายุ การแตะ/พิมพ์หรือเปิดจอร้องสดในหน้าที่มองเห็นจะต่ออายุทุก 15 วินาที
- เปิดจอร้องสดทิ้งไว้ด้านหน้าถือว่ายังดูอยู่ ระบบแยกไม่ได้ว่าผู้ใช้มองหน้าจอจริงหรือไม่
- ลดเพดานผู้ใช้ไม่ตัดผู้ที่กำลังใช้งานอยู่ แต่หยุดรับรายใหม่จนมีช่องว่าง ปิดหน้าตั้งค่าแล้วยังประเมินใหม่เป็นระยะ
- การหมดอายุเซสชันไม่ลบคำขอหรือเพลงที่อยู่ในคิว ผู้ที่เชื่อมต่อใหม่ได้เซสชันใหม่และไม่ถือสิทธิ์แก้คำขอของเซสชันเดิม
- ยังไม่ได้ตรวจ WLAN metrics หรือหน้าต่างจริงบน Windows

## 0.5.36 — ลดเมนูที่ซ้ำกับการใช้งานบนจอ

- นำหมวด “รายการเพลง (จำนวน)” และเมนูย่อยของหมวดนี้ออกจากเมนูคลิกขวา
- ไม่ลบข้อมูลเพลงหรือคิว เปิดคิวด้วย F10 เลือกคิวด้วยลูกศร ค้นหาและเพิ่มเพลงด้วยวิธีเดิมได้
- เมนูจัดการข้อมูลเพลงยังอยู่สำหรับนำเข้าและดูแลคลัง
- รวมระบบเสียงมือถือที่เครื่องหลักอนุญาตได้ ปุ่มลำโพงมือถือ และเต็มจอจาก 0.5.35
- เสียงมือถือใช้ลำโพงเริ่มต้นของ Windows จึงรวมเสียงโปรแกรมอื่นด้วย และมีความหน่วง; ยังไม่ได้ทดสอบ WASAPI บน Windows จริง

## 0.5.35 — สิทธิ์เสียงมือถือและหน้าจอปรับขนาด

- เครื่องหลัก: รีโมทมือถือ → ขั้นที่ 2 → อนุญาตเสียงบนมือถือ ค่าเริ่มต้นปิดทุกครั้งที่เริ่มรีโมทใหม่
- เมื่ออนุญาต ปุ่มลำโพงปรากฏบนมือถือ ผู้ใช้ต้องแตะเองเพื่อเริ่มเสียง แตะอีกครั้งเพื่อปิด เมื่อเครื่องหลักไม่อนุญาตจะซ่อนปุ่มและปิดเสียง
- ส่งเสียงจากลำโพงเริ่มต้นของ Windows ด้วย WASAPI loopback ผ่าน SoundCard จึงรวมเสียงโปรแกรมอื่นที่ใช้อุปกรณ์เดียวกัน ไม่เปิดไมโครโฟนและไม่บันทึกไฟล์เสียง
- ควรให้ X-Stage ใช้อุปกรณ์เสียงเดียวกับลำโพงเริ่มต้น หากใช้อุปกรณ์ MIDI ภายนอก/เอาต์พุตอื่นเสียงอาจไม่อยู่ในสตรีม เปลี่ยนอุปกรณ์แล้วให้ปิดและเปิดสิทธิ์เสียงใหม่
- เสียงสเตอริโอ PCM 24 kHz ส่งเป็นช่วงสั้นผ่าน LAN มีความหน่วงจากเครือข่ายและเบราว์เซอร์ ไม่รับประกันตรงกับจอร้องแบบไร้ความหน่วง
- ปิดเสียงเมื่อขาดการเชื่อมต่อ ออกจากระบบ สลับแอป หรือถูกถอนสิทธิ์ การอนุญาตอีกครั้งไม่เปิดลำโพงมือถือเอง
- แสดงข้อผิดพลาดหากเปิดอุปกรณ์เสียงไม่ได้หรือเบราว์เซอร์ไม่รองรับ
- ปุ่มเต็มจออยู่ด้านบนใช้ได้ทุกหน้า รวมปุ่มเดิมในจอร้องสด หากเบราว์เซอร์ไม่รองรับจะแนะนำเพิ่มเว็บไว้หน้าจอโฮม
- ปรับหน้าให้พอดีทั้งแนวตั้ง/แนวนอน รองรับพื้นที่ขอบจอ ปุ่มย้ายแถวได้บนจอแคบ และชื่อเพลงยาวตัดบรรทัด
- ทดสอบ Chromium ด้วยเสียง PCM สังเคราะห์และจอ 280–1024 พิกเซล ยังไม่ได้ทดสอบจับเสียง WASAPI หรือมือถือจริง

## 0.5.34 — ขอเพลงบนมือถือและเริ่มคิวแรกอัตโนมัติ

- กดเชื่อมต่อแล้วเปิดหน้าใส่ชื่อผู้ขอ กดเริ่มขอเพลงจึงเข้าสู่หน้าค้นหา จำชื่อไว้และเปลี่ยนได้จากปุ่มชื่อด้านบน
- ล้างคำค้นและผลค้นหาเมื่อเครื่องหลักยืนยันรับคำขอสำเร็จเท่านั้น กรณีเน็ตหลุดเก็บคำค้น/คำขอไว้ให้ส่งซ้ำด้วยรหัสคำขอเดิมเพื่อไม่เพิ่มซ้ำ
- คิวของฉันแสดงเฉพาะรออนุมัติ อยู่ในคิว และกำลังเล่น ซ่อนเพลงที่สิ้นสุด ยกเลิก หรือถูกปฏิเสธ โดยไม่ลบประวัติบนเครื่องหลัก
- ดึงลงเมื่ออยู่บนสุดของหน้าเพื่อรีเฟรช หรือกดปุ่ม ↻ ไม่ออกจากระบบและไม่ส่งคำขอซ้ำ ปัดซ้ายขวาสลับหน้าได้ตามเดิม
- ตัวเลือก QR บนจอร้องเป็น 3 แบบชัดเจน: ปิด / แสดงตลอด / แสดงเฉพาะช่วงรอเพลง
- เมื่อเครื่องว่างและมีเพลงเข้าคิว นับถอยหลัง 5 วินาทีบนจอร้องและจอร้องสดมือถือแล้วเล่นคิวแรก (คำขอรออนุมัติยังไม่เข้าคิวจนกว่าจะอนุมัติ)
- เปลี่ยนเพลงแรกระหว่างนับเริ่มนับใหม่ คิวว่างยกเลิกการนับ กดหยุดยกเลิกการเริ่มอัตโนมัติของรายการนั้นได้ ไม่เริ่มซ้ำทุกเฟรมเมื่อระบบเสียงเปิดไม่สำเร็จ
- ไม่ขัดเพลงที่กำลังเล่นหรือพัก เมื่อเพลงจบและมีคิวถัดไปยังเล่นต่อทันที
- มือถือไม่มีเสียงเหมือนเดิม

## 0.5.33 — ตั้งค่ารีโมททีละขั้นตอน

1. เชื่อมต่อ Wi-Fi และตรวจสิทธิ์: แสดงชื่อ Wi-Fi/IP พร้อมปุ่มเชื่อมต่อ ตรวจซ้ำ เปิดสิทธิ์ และคืนค่า รอจนพร้อมจึงกดถัดไปได้
2. ตั้งค่ารับคำขอ: เลือกอนุมัติอัตโนมัติ/เอง จำนวนเพลงรอ สิทธิ์ผู้ร้อง ผู้ดูแล การแสดง QR และพอร์ต แล้วกดบันทึกและเปิดรีโมท
3. พร้อมใช้งาน: แสดงชื่อ Wi-Fi, QR, รหัสผู้ร้อง และรายการรออนุมัติ กดเสร็จสิ้นเพื่อปิดหน้าตั้งค่าโดยรีโมทยังคงทำงาน

- แสดงเฉพาะหน้าปัจจุบัน พร้อมเลขขั้นตอน แถบความคืบหน้า และปุ่มด้านล่างที่อยู่นอกพื้นที่เลื่อน
- เปิดสิทธิ์เสร็จไม่ข้ามไปเปิดรีโมทเอง ต้องตั้งค่าขั้นที่ 2 ให้เสร็จก่อน
- หากเปิดพอร์ตไม่สำเร็จจะอยู่ขั้นตั้งค่าให้แก้และลองใหม่ หาก Wi-Fi หลุดก่อนเปิดรีโมทจะกลับขั้นแรก
- หากรีโมททำงานอยู่แล้ว เปิดหน้าต่างครั้งถัดไปจะแสดงขั้นพร้อมใช้งาน; ย้อนกลับแก้ตัวเลือกได้ หยุดรีโมทก่อนเปลี่ยนพอร์ต
- Wi-Fi หลุดขณะเปิดรีโมทจะซ่อน QR และแสดงสถานะรอเชื่อมต่อ เมื่อกลับมาจะอัปเดต QR ตาม IP ปัจจุบัน
- ปุ่มเปิดสิทธิ์ยังต้องยืนยัน UAC ใน Windows ตามเดิม

## 0.5.32 — แก้ไฟล์เปิดสิทธิ์ Wi-Fi หายหลังติดตั้ง

- สาเหตุ: ตัวติดตั้งคัดลอก tools ไป Source แต่ไม่ได้คัดลอกไป App ซึ่ง EXE ใช้ค้นหา tools/Repair-XStage-WiFi.ps1
- แก้ให้ตัวติดตั้งคัดลอก tools ไป App ด้วย พร้อมตรวจไฟล์ก่อนเริ่มคัดลอกและหลังติดตั้ง; ขั้นตอน build ตรวจไฟล์ก่อนรายงานสำเร็จ
- ไม่เปลี่ยนพฤติกรรมการขอ UAC หรือการแก้สิทธิ์ และไม่ลบ Data หรือไฟล์เพลง
- ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วรัน Install-to-D.cmd โดยเลือกตำแหน่งติดตั้งเดิม จากนั้นเปิดโปรแกรมและกดเปิดสิทธิ์อ่าน Wi-Fi
- ทดสอบ Linux 338 รายการ: ผ่าน 332 ข้าม 6 ไม่มีข้อผิดพลาด ยังไม่ได้รันตัวติดตั้ง PowerShell/UAC บน Windows จริง

## 0.5.31 — แก้ชุดทดสอบพาธบน Windows

- แก้การเปรียบเทียบพาธไฟล์ข้าง EXE ให้ใช้พาธเต็มจากโฟลเดอร์ชั่วคราวจริง รวมชื่อภาษาไทย ช่องว่าง และ apostrophe
- แก้การตรวจอาร์กิวเมนต์ PowerShell ให้รองรับตัวคั่นพาธของระบบ ไม่บังคับเครื่องหมาย / บน Windows
- เพิ่มกรณีพาธ Windows ที่มีอักษรไดรฟ์และ UNC โดยตรวจว่า -File ได้รับพาธครบเป็นอาร์กิวเมนต์เดียว
- คงขั้นตอนหยุด build เมื่อทดสอบไม่ผ่าน ไม่มีการข้ามการทดสอบเพื่อสร้าง EXE
- ผลบน Linux: 335 รายการ ผ่าน 329 ข้าม 6 ไม่มี failures/errors; ยังไม่ได้ทดสอบ Windows/UAC/Registry จริง
- แตก ZIP รุ่นนี้ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd หากยังล้มเหลว โปรดส่ง build-tests.log ทั้งไฟล์

## 0.5.30 — ปุ่มเปิดสิทธิ์อ่าน Wi-Fi ในหน้าต่างรีโมท

- เพิ่มปุ่ม “เปิดสิทธิ์อ่าน Wi-Fi” สำหรับเครื่องส่วนตัว และ “คืนค่าสิทธิ์เดิม” ในหน้าต่างรีโมท
- กดปุ่มแล้วชุด PowerShell ที่มากับโปรแกรมขอสิทธิ์ผู้ดูแลผ่าน UAC; ไม่ต้องเปิดไฟล์แยก
- แก้เฉพาะค่าตำแหน่งที่ตั้งและบริการ Geolocation ตามรายการที่กำหนด; เปิดสิทธิ์ตำแหน่งระดับเครื่อง/ผู้ใช้/แอปเดสก์ท็อป ไม่ใช่สิทธิ์เฉพาะ X-Stage
- สำรองค่าทั้งหมดก่อนแก้ใน %ProgramData%\XStage-WiFi-Repair\<User SID> พร้อม log; เมื่อเกิดข้อผิดพลาดจะพยายามคืนค่าและรายงานหากคืนค่าไม่ครบ
- ปุ่มคืนค่านำค่าก่อนการรันล่าสุดกลับมา ไม่แก้ Firewall, Antivirus, รหัสผ่าน Wi-Fi หรือสิทธิ์หมวดอื่น
- รักษา SID ของผู้ใช้เดิมเมื่อยกระดับผ่าน UAC เพื่อไม่แก้สิทธิ์ของบัญชีผู้ดูแลคนอื่นแทน
- แก้หัวข้อเมื่ออ่าน SSID ไม่ได้ให้ระบุว่า Windows ปิดสิทธิ์ ไม่แสดงว่า Wi-Fi ไม่ได้เชื่อมต่อ
- หากกดเปิดรีโมทขณะสิทธิ์/เครือข่ายยังไม่พร้อม จะรอและเปิดต่ออัตโนมัติหนึ่งครั้งเมื่อพร้อม; กดหยุดหรือปิดหน้าต่างยกเลิกการรอ
- ไม่มีการเปิดบริการรีโมทเพียงเพราะกดปุ่มซ่อมสิทธิ์ หากยังไม่ได้สั่งเปิดรีโมทไว้

วิธีใช้: ปิดโปรแกรมรุ่นเก่า ติดตั้งรุ่นนี้ เปิดหน้าต่างรีโมท กด “เปิดสิทธิ์อ่าน Wi-Fi” และกด Yes ที่ UAC จากนั้นรอชื่อ Wi-Fi/IP
หากโปรแกรมยังไม่ได้รับสิทธิ์ ให้ปิดเปิด X-Stage ใหม่; หากจำเป็นรีสตาร์ต Windows หนึ่งครั้ง ไม่มีการรีสตาร์ตเครื่องให้อัตโนมัติ
หากนโยบาย Local Group Policy หรือโปรแกรมปรับแต่งความเป็นส่วนตัวยังใช้ค่าปิดสิทธิ์อยู่ อาจถูกตั้งกลับ ชุดแก้ไขจึงไม่รับประกันแก้ได้ทุกเครื่อง ให้ใช้ log ระบุสาเหตุต่อไป
ชุด PowerShell นี้ตรวจไวยากรณ์และทบทวนขอบเขตการแก้ไขแล้ว แต่ยังไม่ได้รันแก้ Registry/UAC บน Windows จริงในสภาพแวดล้อมทดสอบนี้

เอกสารอ้างอิงการตั้งค่า:
https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/cannot-set-timezone-automatically
https://learn.microsoft.com/en-us/azure/virtual-desktop/redirection-configure-location
https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-admx-sensors
https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-admx-locationprovideradm

## 0.5.29 — ตรวจชื่อ Wi-Fi ของเครื่องหลักอัตโนมัติ

- แสดงชื่อ Wi-Fi (SSID) ที่เครื่องหลักเชื่อมต่อจริง ไม่ต้องพิมพ์เอง และไม่ใช้ชื่อเก่าที่บันทึกไว้
- QR ใช้ IPv4 จากอะแดปเตอร์ Wi-Fi ตัวเดียวกัน ไม่เลือก IP ของ LAN/VPN หรือ 127.0.0.1
- ไม่พบอะแดปเตอร์ / ไม่ได้เชื่อมต่อ / ยังไม่ได้รับ IP: แจ้งสถานะแยกกันและให้เชื่อมต่อ Wi-Fi ก่อนเปิดรีโมท
- มีปุ่มเปิดหน้าตั้งค่า Wi-Fi ของ Windows และตรวจสอบอีกครั้ง
- ตรวจเบื้องหลังทุก 5 วินาที ไม่เรียกตรวจเครือข่ายบนเธรดเล่นเพลง; หากหลุดจะซ่อน QR เดิม เมื่อเปลี่ยน Wi-Fi/IP จะสร้าง QR ใหม่ แม้ปิดหน้าต่างตั้งค่าแล้ว
- ไม่เปลี่ยนหรือต่อ Wi-Fi ให้เอง ไม่อ่านรหัสผ่าน Wi-Fi และไม่ตั้งชื่อจากการคาดเดา
- Windows บางรุ่นต้องอนุญาตสิทธิ์ตำแหน่งเพื่ออ่าน SSID หากถูกปฏิเสธจะแจ้งข้อจำกัดให้ทราบ แทนการแจ้งว่าไม่มี Wi-Fi
- เครื่องหลักที่ต่อสาย LAN อย่างเดียวจะถูกแจ้งให้เชื่อมต่อ Wi-Fi ตามโหมดนี้ ไม่สามารถทราบชื่อ Wi-Fi ของเราเตอร์จากสาย LAN ได้ด้วยวิธีนี้

วิธีใช้: เปิดหน้าต่างรีโมท → รอชื่อ Wi-Fi/IP แสดง → ให้มือถือเชื่อมต่อชื่อนั้น → เปิดรีโมทและสแกน QR
ไม่ต้องมีอินเทอร์เน็ต แต่เครือข่ายต้องอนุญาตให้อุปกรณ์ติดต่อกันและ Windows Firewall ต้องอนุญาตโปรแกรม

## 0.5.28 — รีโมทมือถือและจอร้องสดไม่มีเสียง

- รหัสสุ่ม 6 หลัก แยกผู้ร้อง/ผู้ดูแล; QR สร้างในเครื่อง ไม่มีบริการภายนอก
- ค้นหาเพลง / คิวเพลง / จอร้องสด: ปัดซ้าย–ขวาหรือแตะแท็บ; เก็บคำค้นและตำแหน่งหน้าเดิม
- เนื้อร้องพร้อมไฮไลต์ตามเวลาเพลง ปรับขนาด แนวตั้ง/แนวนอน เต็มจอเมื่อเบราว์เซอร์รองรับ; ไม่มีเสียง ไม่มีปุ่มเปิดเสียง
- ผู้ร้องระบุชื่อ ตั้งคีย์แยกต่อรายการ ดูสถานะ/ลำดับคิว ยกเลิกและเปลี่ยนคีย์ก่อนเริ่มเล่นตามสิทธิ์
- เลือกอนุมัติอัตโนมัติตามลำดับรับคำขอ หรืออนุมัติเอง; การเปลี่ยนโหมดมีผลเฉพาะคำขอใหม่ คำขอค้างยังรออนุมัติ
- แยกสวิตช์รับคำขอ / รีโมทควบคุม / แสดง QR บนจอร้อง / แสดงเฉพาะช่วงไม่มีเพลง
- จำโหมดอนุมัติ การรับคำขอ สิทธิ์แก้ไข และจำนวนเพลงรอไว้สำหรับครั้งถัดไป
- ปิดรีโมทควบคุมเป็นค่าเริ่มต้น; ปิดสิทธิ์แล้วตัดการเชื่อมต่อผู้ดูแลเดิม ต้องใส่รหัสใหม่เมื่อเปิดอีกครั้ง
- ป้องกันคำขอซ้ำแม้ผลตอบกลับหาย เก็บคำขอที่ยังไม่ยืนยันในมือถือเพื่อลองส่งซ้ำหลังรีโหลด
- จำกัดเพลงรอ 1–20 ต่อการเชื่อมต่อ (เริ่มต้น 3); จำกัดการลองรหัสผิดและคำสั่งถี่
- เปลี่ยนรหัสตัดการเชื่อมต่อเดิม แต่ไม่ลบเพลงที่รับเข้าคิวแล้ว

### วิธีใช้งาน
เปิดเมนูเครื่องมือ → รีโมทมือถือผ่าน Wi-Fi → รอ Wi-Fi/IP ที่ตรวจพบ → เปิดรีโมท
ชื่อ Wi-Fi ตรวจอัตโนมัติตั้งแต่รุ่น 0.5.29; มือถือและเครื่องหลักต้องอยู่เครือข่ายเดียวกัน และ Windows Firewall ต้องอนุญาตแอปบนเครือข่ายส่วนตัว
เลือกวิธีอนุมัติจากสองตัวเลือกในหน้าต่างเดียวกัน ผู้ดูแลอนุมัติ/ปฏิเสธผ่านตารางบนเครื่องหลักได้แม้ปิดรีโมทควบคุมมือถือ
หากเปิดรีโมทควบคุม ให้รหัสผู้ดูแลเฉพาะผู้ที่ได้รับอนุญาต รหัสนี้ไม่ขึ้นจอร้อง
QR ผู้ร้องอยู่ในหน้าต่างเครื่องหลักเสมอเมื่อเปิดบริการ; จอร้องแสดงเมื่อเปิดสวิตช์เท่านั้น

### ขอบเขตการใช้งาน
ใช้ภายใน LAN ที่ไว้ใจได้ ไม่ควรเปิดพอร์ตออกอินเทอร์เน็ต; ผู้ที่เห็น QR/รหัสผู้ร้องจะเข้าระบบขอเพลงได้
จอร้องมือถือแสดงข้อมูลเนื้อร้อง MIDI/KAR/EMK/LRC ที่โปรแกรมอ่านได้ ไม่ใช่การถ่ายทอดภาพหน้าจอหรือวิดีโอคาราโอเกะ
ความตรงจังหวะขึ้นกับ Wi-Fi/เครื่องมือถือ; ใช้การปรับเทียบเวลาและหยุดคาดการณ์เมื่อการเชื่อมต่อขาด ไม่รับประกันความหน่วงเป็นศูนย์
การติดตาม/แก้ไขคำขอผูกกับการเชื่อมต่อในเบราว์เซอร์เดิม รีโหลดแล้วยังคงอยู่ แต่หลังออกจากระบบ เปลี่ยนรหัส หรือหยุด/เปิดบริการใหม่ ต้องเชื่อมต่อใหม่ และจัดการคิวเดิมผ่านผู้ดูแล
จำนวนเพลงรอจำกัดต่อการเชื่อมต่อ ไม่ใช่การยืนยันตัวบุคคล; เปลี่ยนเบราว์เซอร์/เชื่อมต่อใหม่ถือเป็นการเชื่อมต่อใหม่
เต็มจอและการซ่อนแถบเบราว์เซอร์ขึ้นกับเบราว์เซอร์มือถือ ใช้หน้าเว็บได้แม้ไม่รองรับเต็มจอ

## รุ่น 0.5.27 — แก้ลูกศรไม่ทำงานเมื่อเปิด Num Lock บน Windows

สาเหตุที่พบในโค้ด: ตัวกรอง modifier เดิมใช้ bit 0x8 เป็น Alt ซึ่งใช้ได้กับ X11 แต่ Tk บน Windows ใช้ bit นี้เป็น Num Lock จึงกันลูกศร Insert/Delete และการเปิดค้นหาจากการพิมพ์เมื่อเปิด Num Lock

- แยกการตรวจ Ctrl/Alt/Shift ตามระบบ Windows ใช้ ALT_MASK 0x20000 ไม่ถือ Num Lock เป็น Alt
- ลูกศรขึ้น/ลงค้นหา ซ้าย/ขวาเลือกคิว ใช้ได้โดยไม่ต้องปิด Num Lock; Caps Lock, Scroll Lock และ extended-key flag ไม่ถูกนำมาเป็นตัวกันลูกศร
- รักษาการกดค้าง/สลับทิศ Alt+ขึ้น/ลงปรับคีย์ และ Insert/Delete สำรอง ตามเดิม
- กำหนดสถานะลูกศรเริ่มต้นชัดเจนตอนเปิดโปรแกรม
- รักษาการตั้งคีย์อิสระต่อรายการและ Enter ลัดคิวโดยไม่เปลี่ยนลำดับเพลงรออื่นจาก 0.5.26

ทดสอบทั้งชุด 284 รายการ: ผ่าน 278 ข้าม 6 ไม่มีข้อผิดพลาด เพิ่ม 7 tests สำหรับสถานะปุ่ม Windows/Num Lock และตรวจชุดคีย์บอร์ด 29 tests ซ้ำโดยจำลอง sys.platform=win32: ผ่านทั้งหมด ตรวจทั้ง Num Lock เปิด/ปิด ลูกศรสี่ทิศ การกดค้างแล้วสลับทิศ การค้นหาจากการพิมพ์ และปุ่มสำรอง

ข้อจำกัด: เป็นการทดสอบโค้ดและเหตุการณ์จำลองบน Linux ไม่ใช่การกดคีย์บอร์ดจริงหรือการเล่นเสียงบน Windows

ติดตั้ง: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ตรวจเลขรุ่น 0.5.27 หลังติดตั้ง ชุดนี้เป็น Source Preview ต้องทดสอบและ build บน Windows ก่อนติดตั้ง

## รุ่น 0.5.26 — คีย์อิสระต่อรายการคิว และรักษาคิวเมื่อลัดเพลง

- คีย์แยกต่อครั้งที่เพิ่มเพลง ไม่เป็นค่าประจำเพลง: เพลงเดียวกันเข้าคิวหลายครั้งสามารถเป็น +2, -1, 0 สำหรับคนร้องต่างกันได้ เมื่อเพิ่มเข้าคิวหรือเปิดเล่นสำเร็จ ค่าร่างในหน้าค้นหากลับเป็น 0 พร้อมอัปเดตรายละเอียด หากเปิดไม่สำเร็จยังเก็บค่าร่างไว้
- Alt+ขึ้น/ลงปรับคีย์รายการคิวที่เลือกได้ ทั้งแผงคิวบนจอและตาราง F10 บันทึกเฉพาะรายการนั้น ไม่กระทบรายการเพลงเดียวกันอื่นหรือเพลงที่เล่นอยู่ ดูชื่อผู้ร้องและคีย์ในแผงคิว และใช้แก้คิวเพื่อกรอกชื่อผู้ร้องได้
- Enter ลัดคิว: ยกเลิกเพลงเดิมแล้วเปิดรายการที่เลือก นำออกจากคิวเฉพาะรายการนั้นหลังเปิดเล่นสำเร็จ คิวรอที่เหลือคงลำดับเดิม จบเพลงที่ลัดมาจะกลับไปเล่นหัวคิว ไม่ลบไฟล์เพลงหรือข้อมูลคลัง หากเปิดไม่สำเร็จเก็บทุกรายการไว้ ไม่ไล่ข้ามรายการอื่น
- Enter, Ctrl+Enter, F5 เริ่มเล่น และเมนูเพิ่มผลค้นหาเข้าคิว ใช้ค่าคีย์ร่างเดียวกันก่อนเริ่มรายการใหม่
- การต่อคิวอัตโนมัติ: ไฟล์หาย/ไม่รองรับ หรือข้อผิดพลาดการอ่าน MIDI ที่จำแนกได้จึงข้ามพร้อมบันทึก สาเหตุระบบเสียง/ซาวด์ฟอนต์/ข้อผิดพลาดที่ยังจำแนกไม่ได้ ให้หยุดและรักษาคิวที่ยังไม่เล่นไว้ แล้วแสดงเหตุผลเพื่อแก้ก่อนกดเล่นใหม่ ใช้แนวทางระมัดระวัง: ไฟล์สื่อบางชนิดที่เปิดไม่ได้อาจหยุดรักษาคิวแทนข้าม เพราะแยกจากปัญหา codec/อุปกรณ์ไม่ได้แน่นอน
- F10 เลือกแถวเดิมหรือแถวแรกและย้ายโฟกัสเข้าตาราง การรีเฟรชรักษาแถวที่เลือกและปรับขอบเขตหากแถวท้ายถูกลบ
- ตัวแก้ไข LRC ประทับเวลาได้เฉพาะตัวเล่นและเพลงที่เปิดแก้ไข ปิดปุ่มเมื่อเปลี่ยนเพลง พร้อมตรวจซ้ำตอนกด ป้องกันเอาเวลาเพลงใหม่ไปใส่เพลงเก่า
- รวมการกรองสถานะ Alt ของ Windows เพิ่มเติมในลูกศรและ Insert/Delete ป้องกันคีย์ผสมหลุดไปเป็นคำสั่งธรรมดา
- ปรับคีย์ได้เฉพาะ .mid/.midi/.kar/.emk ตรวจในหน้าค้นหา คิวและรีโมต ไฟล์เสียง/วิดีโอไม่แสดงผลการปรับคีย์ที่ตัวเล่นทำไม่ได้ เมื่อเปิดสื่อเหล่านี้ปรับค่าคีย์เป็น 0

ตัวอย่างลัดคิว: A(+2) → B(0) → A(-1) → C(0) เลือก A รายการที่สามแล้ว Enter: เล่น A(-1) ทันที คิวคงเหลือ A(+2) → B(0) → C(0)

ตรวจ 277 tests: ผ่าน 271 ข้าม 6 ไม่มีข้อผิดพลาด เพิ่ม 17 tests และปรับกรณีทดสอบเดิมให้แยกความผิดพลาดของไฟล์กับระบบเสียง ตรวจคิวเพลงซ้ำที่มีคีย์ต่างกัน การบันทึก/อ่านคิว การลัดเฉพาะรายการ การเริ่มจากหัวคิวหลังจบ การเปิดลัดไม่สำเร็จไม่กระทบคิว F5/Enter/เมนู คีย์สื่อที่ไม่รองรับ F10 และ LRC

ข้อจำกัด: ทดสอบบน Linux ด้วยเหตุการณ์ วิดเจ็ต และอุปกรณ์จำลอง ยังไม่ได้ตรวจคีย์บอร์ด เสียง Core Audio และหน้าต่างจริงบน Windows รุ่นนี้ไม่ได้เปลี่ยนพฤติกรรมย้ายอุปกรณ์เสียงของ stream ที่เปิดอยู่

ติดตั้ง: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ชุดนี้เป็น Source Preview ต้องทดสอบและ build บน Windows ก่อนติดตั้ง

## รุ่น 0.5.25 — Alt + ลูกศร เพิ่ม/ลดคีย์

- Alt + ลูกศรขึ้น เพิ่มคีย์ 1 ครึ่งเสียง; Alt + ลูกศรลง ลดคีย์ 1 ครึ่งเสียง จำกัด -12 ถึง +12
- เก็บ Insert เพิ่มคีย์ / Delete ลดคีย์ เป็นปุ่มสำรอง ใช้ได้ทั้งจอหลักและจอร้อง
- ในหน้าค้นหาจะปรับคีย์เฉพาะเพลงที่เลือกและส่งค่าไปกับรายการคิว ไม่กระทบเพลงที่กำลังเล่น บนจอเล่นเพลงเมื่อไม่มีค้นหา/แผงเลือกคิวจะปรับ MIDI ปัจจุบัน
- ลูกศรโดยไม่กด Alt ยังเลือกผลค้นหาและเลื่อนคิวตามเดิม ไม่เปลี่ยนคีย์ ไม่แย่งปุ่มจากช่องแก้ไขข้อมูลทั่วไป และเว้นชุด Ctrl/Shift ไว้
- รวมการแก้ลูกศรค้างแล้วสลับโหมด การกด Enter ยกเลิกเพลงเก่าแล้วเล่นคิวที่เลือก และการซิงก์เสียง Windows จากรุ่นก่อน

ตรวจ 260 tests: ผ่าน 254 ข้าม 6 ไม่มีข้อผิดพลาด เพิ่ม 3 tests ตรวจ Alt+ขึ้น/ลง การตั้งคีย์เฉพาะเพลงที่ค้นหา และการไม่รบกวนช่องแก้ไข/คีย์ผสมอื่น ตรวจรูปแบบสถานะ Alt ทั้ง 0x8 และ 0x20000 ด้วยเหตุการณ์จำลอง รันบน Linux ยังไม่ได้ทดสอบคีย์บอร์ดและเสียงจริงบน Windows

ติดตั้ง: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ชุดนี้เป็น Source Preview ต้องทดสอบและ build บน Windows ก่อนติดตั้ง

## รุ่น 0.5.24 — เปลี่ยนปุ่มปรับคีย์เป็น Insert / Delete

- ยกเลิกปุ่ม -/+ และ Numpad -/+ สำหรับปรับคีย์ เปลี่ยนเป็น Insert เพิ่มคีย์ และ Delete ลดคีย์ ครั้งละ 1 ครึ่งเสียง จำกัด -12 ถึง +12
- ในหน้าค้นหา: ปรับคีย์เพลงที่เลือกโดยไม่กระทบเพลงที่กำลังเล่น แสดงค่าปรับคีย์ในรายละเอียด เมื่อกด Enter เพิ่มคิว/เล่น หรือ Ctrl+Enter เล่นทันที จะใช้ค่านี้ด้วย แต่ละเพลงจำค่าแยกกันระหว่างเปิดโปรแกรม
- ในจอเล่นเพลงเมื่อไม่ได้เปิดค้นหาหรือเลือกคิว: Insert/Delete ปรับคีย์ของเพลง MIDI ปัจจุบันทันที
- ในช่องค้นหา Delete ใช้ลดคีย์ ให้ใช้ Backspace เมื่อต้องการลบตัวอักษร ช่องแก้ไขข้อมูลอื่นและ Shift/Ctrl/Alt ยังทำงานตามเดิม ไม่เพิ่มคำสั่งลบเพลง/ย้ายคิวของ eXtreme ที่อยู่นอกขอบเขตงานนี้
- รวมรุ่น 0.5.23: ลูกศรใหม่เปลี่ยนโหมดได้แม้อีกปุ่มค้าง และ Enter ในคิวยกเลิกเพลงเดิมก่อนเล่นรายการที่เลือก

อ้างอิงการจับคู่ Insert/Delete ในหน้าค้นหาจากตารางคีย์ลัดบนเว็บไซต์ eXtreme:
https://karaoke-soft.com/smf/index.php?topic=36456.125
เป็นการปรับเฉพาะคีย์ลัดเพิ่ม/ลดคีย์ ไม่ได้เปลี่ยนคีย์ลัดทุกคำสั่งของโปรแกรมให้เหมือน eXtreme

ตรวจ 257 tests: ผ่าน 251 ข้าม 6 ไม่มีข้อผิดพลาด ตรวจการผูกปุ่มใหม่ การแยกคีย์เพลงที่เลือกออกจากเพลงปัจจุบัน และค่าที่ส่งเข้าคิว รันบน Linux ด้วยตัวเล่น/เหตุการณ์จำลอง ยังไม่ได้ทดสอบคีย์บอร์ดและเสียงจริงบน Windows

ติดตั้ง: ปิดโปรแกรม แตก ZIP ใหม่ แล้วเปิด Install-to-D.cmd ชุดนี้เป็น Source Preview ต้อง build บน Windows ก่อนติดตั้ง

## รุ่น 0.5.23 — ลูกศรเปลี่ยนโหมดทันที และ Enter เล่นคิวที่เลือก

- ขึ้น/ลงเลือกผลค้นหา ซ้าย/ขวาเปิดและเลือกคิวได้ทันทีแม้ช่องค้นหาเปิดอยู่ โดยขวาเลื่อนลง ซ้ายเลื่อนขึ้นตามเดิม คำค้นยังคงอยู่
- เมื่อกดลูกศรใหม่ขณะอีกปุ่มค้างอยู่ ให้ปุ่มใหม่ทำงานทันที สัญญาณกดซ้ำจากปุ่มเก่าจะถูกพักจนกว่าจะปล่อยและกดใหม่ ป้องกันขึ้น/ลงที่ค้างอยู่ดึงกลับไปโหมดค้นหา ไม่ต้องรอปล่อยปุ่มเดิมก่อนสลับ
- กดซ้ำจากปุ่มที่กำลังใช้งานยังเลื่อนรายการตามปกติ ออกจากหน้าต่างแล้วล้างสถานะปุ่มค้าง ไม่รบกวนลูกศรในช่องแก้ไขข้อมูลอื่นหรือ Ctrl/Alt
- Enter ในคิวบนจอ: จับรายการที่เลือก ยกเลิกตัวเล่นเดิม แล้วเริ่มรายการนั้นทันที ไม่รอเพลงเดิมจบ ไม่มีเวลาหน่วงที่เพิ่มเอง แต่ยังใช้เวลาเปิดไฟล์/โหลดเสียงตามชนิดไฟล์และเครื่อง
- หน้าต่างคิว F10 เพิ่ม Enter เพื่อยกเลิกเพลงเดิมและเล่นรายการที่เลือกเช่นเดียวกัน ป้องกัน Enter ค้างสั่งข้ามหลายรายการ ส่วน Enter ในผลค้นหายังเพิ่มเข้าคิวตามเดิมเมื่อมีเพลงเล่นอยู่
- คิวที่เปิดไม่ได้ยังใช้กติกาข้ามพร้อมบันทึกเหตุผลจากรุ่นก่อน

ทดสอบ 255 รายการ: ผ่าน 249 ข้าม 6 ไม่มีข้อผิดพลาด เพิ่ม 11 tests ตรวจปุ่มค้างแล้วสลับทิศ การไม่เด้งกลับ การปล่อย/กดใหม่ การเสียโฟกัส และลำดับยกเลิกเพลงก่อนเล่นคิว Tests จำลองเหตุการณ์บน Linux ยังไม่ได้ตรวจการกดค้างจริงบน Windows และไม่ได้ทดสอบเสียงจริงในรุ่นนี้

ติดตั้ง: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ชุดนี้เป็น Source Preview ต้อง build บน Windows ก่อนติดตั้ง

## รุ่น 0.5.22 — ระดับเสียงสัมพันธ์กับ Windows

- ล้อเมาส์บนจอเพลงและจอร้องปรับเสียงหลักของอุปกรณ์เล่นเสียงเริ่มต้น Windows ครั้งละ 5 จุดเปอร์เซ็นต์ อ่านค่าจริงก่อนเพิ่ม/ลดทุกครั้ง รองรับการปรับด้วยแถบเสียงและรีโมตด้วย
- อ่านระดับเสียงและสถานะปิดเสียงจาก Windows ทุก 400 ms เพื่ออัปเดตแถบเสียง เมื่อเริ่มโปรแกรมอ่านค่าปัจจุบันอย่างเดียว ไม่เปลี่ยนเสียงหลักตามค่าที่เคยบันทึก
- ตัวเล่นเพลงใช้ gain 100% เมื่อเชื่อม Windows volume สำเร็จ เพื่อไม่ลดเสียงซ้ำทั้งในโปรแกรมและเสียงหลัก แต่ยังคงระดับเสียงรายช่อง MIDI/มิกเซอร์เดิม
- ปรับค่าเป็นบวกจะยกเลิก mute และค่า 0 จะปิดเสียง อ่านค่ากลับหลังเขียน ไม่ใช้ค่าคาดเดา หากอุปกรณ์หายจะแจ้งเมื่อปรับเสียงและลองอ่านใหม่ เมื่อ Windows เปลี่ยนอุปกรณ์เริ่มต้น ตัวควบคุมอ่านจากอุปกรณ์ใหม่
- แถบแสดงเสียงระบุ “เสียง Windows” ตัวเลขนี้เป็นเสียงหลักของอุปกรณ์เริ่มต้น ไม่ใช่เสียงแยกแอปใน Volume Mixer จึงมีผลกับแอปอื่นบนอุปกรณ์นั้นด้วย หากเลือกให้ตัวเล่นใช้อุปกรณ์อื่น ต้องตั้งอุปกรณ์เริ่มต้น Windows ให้ตรงกัน การเปลี่ยนอุปกรณ์เริ่มต้นไม่ได้ย้าย stream เพลงที่เปิดอยู่โดยอัตโนมัติ
- หากสร้างตัวเชื่อม Windows ไม่สำเร็จ แสดงข้อความและใช้ตัวควบคุมเสียงภายในเดิม การเลื่อนรายการค้นหา/คิวไม่ปรับเสียงเช่นเดิม

ตรวจ 244 tests: ผ่าน 238 ข้าม 6 ไม่มี error/failure เพิ่ม 11 tests ตรวจการอ่าน/เขียน ระดับเสียงจากภายนอก การอ่านก่อนหมุนล้อ ขอบเขตและ mute อุปกรณ์หาย การปล่อย COM และการป้องกันเขียนวนกลับ Tests ใช้ Windows API จำลองบน Linux ยังไม่ได้ทดสอบเสียงและการเชื่อม Core Audio กับ Windows จริง

ตรวจรับบน Windows: เปิดเพลง แล้วเทียบค่าบนแถบโปรแกรมกับเสียงหลัก Windows; หมุนขึ้น/ลงครั้งละ 5%; ปรับจาก Windows และรอประมาณ 0.4 วินาที; ทดลอง mute แล้วเพิ่มเสียง; เปลี่ยนอุปกรณ์เริ่มต้นและตรวจค่าอีกครั้ง ระดับรายแอปใน Windows Volume Mixer ยังเป็นตัวควบคุมแยกต่างหาก

ติดตั้ง: ปิดโปรแกรม แตก ZIP ใหม่ แล้วเปิด Install-to-D.cmd ชุดนี้เป็น Source Preview ต้อง build บน Windows ก่อนติดตั้ง

เอกสาร API ที่ใช้ตรวจสอบ:
https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolume
https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-getdefaultaudioendpoint

## รุ่น 0.5.21 — คีย์ลัดลด/เพิ่มคีย์เสียง

- ปุ่ม - ลดคีย์ 1 ครึ่งเสียง ปุ่ม + เพิ่มคีย์ 1 ครึ่งเสียง (บนแป้นหลักโดยทั่วไป Shift+=) รองรับปุ่มลบ/บวกบน Numpad ด้วย
- ใช้กับเพลง MIDI ปัจจุบันทั้งจอหลักและจอร้อง จำกัด -12 ถึง +12 ครึ่งเสียง อัปเดตช่องคีย์และรายละเอียดบนจอ
- เมื่อพิมพ์ในช่องค้นหาที่เปิดอยู่ ช่องกรอกข้อมูล หรือตัวแก้ไขเนื้อร้อง เครื่องหมายยังพิมพ์ได้ตามปกติ ไม่แย่ง Ctrl/Alt และไม่เปลี่ยนคีย์ของเพลงในคิวล่วงหน้า
- แก้การรับปุ่มจากช่องค้นหาที่ซ่อนไว้ เพื่อให้คีย์ลัดทำงานโดยไม่เปิดการค้นหาอัตโนมัติ

ทดสอบทั้งหมด 233 รายการ: ผ่าน 227 ข้าม 6 ไม่มีข้อผิดพลาด เพิ่ม 6 tests ตรวจคีย์ลัด ขอบเขตค่า ช่องพิมพ์ จอร้อง และการผูกปุ่ม Numpad การทดสอบปุ่มใช้เหตุการณ์/ตัวเล่นจำลอง ยังไม่ได้ตรวจคีย์บอร์ดและเสียงจริงบน Windows ผลทดสอบ GUI รุ่นก่อนเป็นข้อมูลย้อนหลัง

ติดตั้ง: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ชุดนี้เป็น Source Preview ต้องทดสอบและ build บน Windows ก่อนติดตั้ง

## รุ่น 0.5.20 — มิกเซอร์ คิวเพลง LRC และรีโมต

- มิกเซอร์ที่เปิดค้างไว้ติดตามตัวเล่น MIDI เพลงใหม่ อัปเดตค่าช่องเสียงและชิ้นกลองทุกครั้งที่เปลี่ยนเพลง ปุ่มหยุดเสียงค้างใช้เพลงปัจจุบัน ยกเลิกตัวจับเวลาเมื่อปิดหน้าต่าง
- เล่นคิวแล้วเปิดไฟล์ไม่ได้: ข้ามรายการนั้นและลองเพลงถัดไป ไม่เปิดหน้าต่างแจ้งเตือนค้าง หากไม่มีเพลงที่เล่นได้ให้ล้างจอเป็นว่าง รายการที่ข้ามถูกนำออกจากคิว แต่ไม่ลบไฟล์เพลงหรือรายการในคลัง บันทึกชื่อ รหัส และเหตุผลใน data/newKaraoke.log ของโปรแกรม (หรือโฟลเดอร์ --data-dir ที่กำหนด)
- ตัวแก้ไข LRC เพิ่มปุ่ม “บันทึกและใช้กับเพลงนี้” บันทึก UTF-8 และผูกไฟล์กับเพลงที่เปิดแก้ไข ถ้าเพลงนั้นยังเล่นอยู่จะใช้ทันที ถ้าคิวเปลี่ยนไปแล้วจะใช้เมื่อเล่นเพลงเดิมครั้งถัดไป ไม่เปลี่ยนเนื้อร้องของเพลงใหม่ ปุ่มบันทึกเป็น… ยังบันทึกไฟล์อย่างเดียว
- รีโมตผู้ควบคุมเพิ่มช่องระดับเสียง 0–100%, คีย์ -12 ถึง +12 ครึ่งเสียง และความเร็ว 50–150% พร้อมปุ่มใช้ค่า อ่านค่าปัจจุบันจากเครื่องเล่นและไม่ทับค่าที่ยังพิมพ์ไม่เสร็จ รหัสผู้ขอเพลงไม่มีสิทธิ์ใช้คำสั่งเหล่านี้ คีย์เสียงและความเร็วขึ้นกับความสามารถของตัวเล่น/ชนิดไฟล์เดิม

ตรวจทั้งชุด 227 tests: ผ่าน 221 ข้าม 6 ไม่มี error/failure เพิ่ม 12 tests ครอบคลุมคิวข้ามไฟล์ผิดพลาดและการบันทึกคิว มิกเซอร์เปลี่ยนตัวเล่น LRC ผูกเพลงเดิม และรีโมตแยกสิทธิ์/ตรวจค่าตัวเลข ตรวจ JavaScript syntax และจำลอง DOM/fetch ยืนยันปุ่มส่งค่าตัวเลขกับการรักษาค่าที่ยังไม่กดใช้

ข้อจำกัดการทดสอบ: รันบน Linux ใช้ตัวเล่นและวิดเจ็ตจำลองในเทสต์มิกเซอร์ ยังไม่ได้ตรวจหน้าต่าง/เสียงจริงบน Windows ในรุ่นนี้ ข้าม 4 Windows Uniscribe, 1 native BASS และ 1 Windows Recycle Bin ผล GUI รุ่นก่อนหน้าด้านล่างเป็นข้อมูลย้อนหลัง ไม่ใช่การรันทดสอบ GUI ใหม่ของ 0.5.20

ติดตั้ง: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ซึ่งทดสอบและ build บน Windows ก่อนติดตั้ง ชุดนี้เป็น Source Preview ไม่มี EXE ที่ build สำเร็จแนบมา ตรวจรุ่น 0.5.20 ในรายละเอียดโปรแกรมหลังติดตั้ง

## รุ่น 0.5.19 — รายละเอียดผู้พัฒนา

หน้าต่าง คลิกขวา → รายละเอียดโปรแกรม แสดงหมายเลขรุ่นจากโปรแกรมโดยอัตโนมัติ และข้อความ:

X-Stage Karaoke รุ่น 0.5.19

ผู้พัฒนาโปรแกรม
ครูไพรัช  อินควรชุม
รร.เทศบาล 1(ถนนนครนอก)
ทน.สงขลา

ตรวจเรียกหน้าต่างผ่าน messagebox จำลองแล้ว ข้อความและหมายเลขรุ่นตรงตามกำหนด การเปลี่ยนแปลงนี้แก้เฉพาะข้อความและรุ่น ไม่ได้รันทดสอบทั้งชุดซ้ำ ผล 215 tests ด้านล่างเป็นของรุ่น 0.5.18

## รุ่น 0.5.18 — ล้อเมาส์เพิ่ม/ลดเสียง

บนพื้นที่จอเล่นเพลงทั้งจอหลักและจอร้องแยก หมุนล้อขึ้นเพิ่มเสียง หมุนลงลดเสียง ครั้งละ 5% จำกัด 0–100% ใช้ระดับเสียงของโปรแกรมและตัวเล่นเดิม ไม่เปลี่ยนเสียงหลักของ Windows แสดงระดับเสียง 1.6 วินาทีและเลื่อนต่อได้แม้ชี้บนป้ายระดับเสียง รองรับการสะสม delta จากล้อความละเอียดสูง

เมื่อชี้บนผลค้นหา คิว หรือหน้าต่างตั้งค่า ล้อเมาส์ยังเลื่อนรายการตามเดิม ไม่เพิ่ม/ลดเสียง

ตรวจ 215 tests: ผ่าน 209 ข้าม 6 ไม่มีข้อผิดพลาด ทดสอบส่ง MouseWheel จริงใน Tk บน Linux ยืนยันว่าปรับครั้งเดียวต่อหนึ่งสเต็ปทั้งสองจอ ป้ายแสดง/ซ่อนได้ และเลื่อนผลค้นหาไม่กระทบเสียง การทดสอบ GUI ปิดส่วนวาดอักษรเวทีที่ต้องใช้ Windows ยังไม่ได้ทดสอบเสียงออกอุปกรณ์จริงบน Windows

ติดตั้ง: ปิดโปรแกรม แตก ZIP แล้วเปิด Install-to-D.cmd ตรวจรุ่น 0.5.18 ชุดนี้เป็น Source Preview ต้อง build บน Windows

## รุ่น 0.5.17 — เล่นคิวต่อเนื่อง คิวแนวตั้ง และค้นหาต่อเนื่อง

- เมื่อได้รับสถานะจบเพลง จะเริ่มเพลงถัดไปในคิวโดยไม่เพิ่มเวลารอ ไม่ใช้ค่า auto_next เก่าที่เคยปิดไว้ การเปิดไฟล์และโหลดชุดเสียงยังใช้เวลาตามเครื่อง จึงไม่ใช่การเล่นต่อแบบ gapless
- หากคิวหมด ปิดตัวเล่น ล้างเพลงปัจจุบัน เนื้อร้อง ชื่อเพลง และค่าการเล่น เหลือพื้นหลัง โลโก้ และนาฬิกา
- แผงเลือกคิวบนจอเปลี่ยนเป็นแถวแนวตั้ง แสดงเพลงก่อนหน้า เพลงที่เลือก และเพลงถัดไป ลูกศรขวาลง ลูกศรซ้ายขึ้น Enter เล่นรายการที่เลือก
- ช่องค้นหาตัวอักษร 25 pt จาก 17 pt ขยายความกว้างและลดกรอบให้กลมกลืนกับแผงพื้นหลังสีเข้ม
- ลูกศรขึ้น/ลงเลือกผลค้นหา เลื่อนตารางให้เห็นเพลงที่เลือก อัปเดตรายละเอียด เก็บคำค้นเดิม และคืนโฟกัสพร้อมเคอร์เซอร์ท้ายคำสำหรับพิมพ์ต่อ

ตรวจสอบ: 210 tests ผ่าน 204 ข้าม 6 ไม่มีข้อผิดพลาด ตรวจ Tk บน Linux เพิ่มเติมว่าคิวเรียงแนวตั้ง ทิศทางลูกศรถูกต้อง พิมพ์ผ่าน native Entry ต่อท้ายคำได้ และจบคิวว่างแล้วตัวเล่นกับเนื้อร้องถูกล้าง โดยปิดส่วนวาดอักษรเวทีที่ต้องใช้ Windows ยังไม่ได้ตรวจเสียงหรือฟอนต์จริงบน Windows

ติดตั้ง: ปิดโปรแกรม แตก ZIP ไปยังโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ตรวจรุ่นเป็น 0.5.17 ชุดนี้เป็น Source Preview และต้อง build บน Windows

## รุ่น 0.5.16 — หน้าต่างพอดีจอและหน้าจอร้องเพลงใหม่

- หน้าต่างจากเมนูคลิกขวาปรับให้พอดีพื้นที่ใช้งานของจอ มีแถบเลื่อนเมื่อเนื้อหาเกิน รองรับเมาส์และเลื่อนไปยังช่องที่กด Tab เข้าถึง
- ปุ่มหลักของซาวด์ฟอนต์ ทดสอบเสียง มิกเซอร์ คิวเพลง และความคืบหน้าแยกอยู่ด้านล่าง จัดเป็นแถวเมื่อพื้นที่แคบ
- แก้ข้อผิดพลาดตอนปิดหน้าจัดการเพลง และป้องกันแถบเลื่อนสลับไปมาจนหน้าต่างค้าง
- เวลามุมขวาบนเป็นนาฬิกาเครื่องแบบ 24 ชั่วโมง HH:MM:SS เวลาเดินเพลงยังดูได้ในแผงควบคุมการเล่น
- เพิ่มโลโก้ภาพที่ผู้ใช้ส่งไว้หน้าชื่อโปรแกรม และเพิ่มชื่อเพลง ศิลปิน รหัส ชนิดไฟล์ คีย์ จังหวะ ความยาว ตามข้อมูลที่มี พร้อมแสดงคีย์ที่ปรับจริง
- พื้นหลังเลือกได้สองแบบเท่านั้น: ภาพเวที X-STAGE ที่แนบมากับชุดโปรแกรม หรือไม่มีรูป ภาพอื่นที่เคยเลือกไว้จะไม่ถูกนำมาใช้
- เนื้อร้องเริ่มต้น 84 พิกเซลอ้างอิง Full HD (จากเดิม 56) ปรับตามความสูงจอ ยกขึ้นหนึ่งบรรทัด และย่อเมื่อข้อความยาวเพื่อไม่ให้ล้นหรือชนแผงข้อมูล ค่ารุ่นเก่าที่ต่ำกว่า 84 ปรับครั้งเดียว หลังจากนั้นผู้ใช้ปรับเองได้
- รูปทั้งสองแนบใน assets และคัดลอกทั้งตอน build และติดตั้ง ไม่ต้องเลือกไฟล์รูปภายหลัง

การติดตั้ง: ปิดโปรแกรม แตก ZIP ไปยังโฟลเดอร์แยก แล้วเปิด Install-to-D.cmd เพื่อติดตั้งทับ ตรวจรุ่นเป็น 0.5.16 ข้อมูลเพลงเดิมยังอยู่ การปรับขนาดเนื้อร้องอยู่ที่ คลิกขวา → ตัวเลือก → ตัวอักษร / สีเนื้อร้อง

การตรวจสอบ: 206 tests ผ่าน 200 ข้าม 6 ไม่มีข้อผิดพลาด ตรวจเปิดและย่อหน้าต่าง 13 แบบด้วย Tk บน Linux/Xvfb ที่ 1366×768 และย่อหน้าต่างเป็น 640×460 โดยปิดส่วนวาดตัวอักษรเวทีที่ต้องใช้ Windows และจำลองรายการอุปกรณ์เสียง การตรวจนี้ไม่ใช่การรับรองรูปลักษณ์ฟอนต์ไทย DPI หลายจอ หรือเสียงจริงบน Windows ชุดนี้เป็น Source Preview ต้อง build บน Windows ก่อนใช้งาน

## รุ่น 0.5.15 — แก้เนื้อร้อง EMK/NCN เป็นอักขระเพี้ยน

พบจากไฟล์ตัวอย่าง T0026.emk ว่ามีไบนารี OPT 1.50 หลังเครื่องหมายจบข้อความ 0x1A โปรแกรมรุ่นก่อนอ่านส่วนนี้เป็นเนื้อร้อง รุ่นนี้หยุดอ่านที่เครื่องหมายจบข้อความก่อนถอดรหัส ทั้งในการเล่นและการนำเข้ารายการเพลง พร้อมเปลี่ยนรุ่นแคชข้อมูลเพื่ออ่านข้อมูลใหม่เมื่อสร้างรายการครั้งถัดไป

ตรวจไฟล์ตัวอย่างแล้วเหลือเนื้อร้อง 4 บรรทัด โดยเวลาและจังหวะทุกตัวอักษรตรงกับ 4 บรรทัดแรกของรุ่นเดิม ไม่แก้ไขไฟล์เพลงต้นฉบับและไม่บรรจุเพลงตัวอย่างในชุดแจก

ทดสอบ 194 รายการ: ผ่าน 188 ข้าม 6 ไม่มีข้อผิดพลาด บน Linux ยังไม่ได้ทดสอบ GUI/เสียงจริงบน Windows และไม่มี EXE ที่คอมไพล์แล้วในชุดนี้

ติดตั้ง: ปิดโปรแกรม แตก ZIP แล้วเปิด Install-to-D.cmd เมื่อติดตั้งสำเร็จตรวจรุ่น 0.5.15 และเปิด T0026 อีกครั้ง หากรายละเอียดในคลังเดิมมีข้อความเพี้ยนให้สั่งสร้างรายการเพลงใหม่เพื่อปรับข้อมูลแคช

# X-Stage Karaoke 0.5.14 — แก้เส้นทางไฟล์ตอนนำเข้า catalog

จาก build-tests(1).log ของ 0.5.13:
test_rebuild_repairs_filename_preserves_id_favorites_queue_search_cache
ล้มเหลวด้วย UNIQUE constraint failed: songs.path แล้วเกิด WinError 32 ตอน cleanup
เป็นข้อผิดพลาดหลักและข้อผิดพลาดตามมาจาก test เดียวกัน

## สาเหตุและการแก้
upsert_catalog เดิมใช้เพียง normcase แต่ Inspector/SongPlan ใช้ Path.resolve + normcase
เส้นทาง Windows แบบชื่อย่อ 8.3 กับชื่อเต็มจึงอาจเป็นคนละ key ในฐานข้อมูล
ปรับ upsert_catalog ให้ใช้ canonical เช่นเดียวกับส่วนอ่านเพลงและสร้างรายการ
เพิ่มการทดสอบ relative path ที่มี .. กับ direct path และจำลองการ resolve ชื่อย่อ Windows
ตรวจว่าเป็นรายการเดียว รักษา ID และเพลงโปรด แล้ว rebuild อ่าน metadata ได้
ชุดทดสอบเดิมใช้ closing กับ SearchReader เพื่อปิด connection แม้ assert/rebuild ล้มเหลว
ไม่ข้าม tests และไม่เปลี่ยน UNIQUE constraint หรือใช้ INSERT IGNORE เพื่อกลบ error

## ตรวจสอบ
190 tests: ผ่าน 184 ข้าม 6 บน Linux
เพิ่ม 2 tests เส้นทางไฟล์สองรูปแบบและการ resolve ชื่อย่อ
ยังไม่ได้บิลด์ EXE หรือทดสอบบน Windows จริงในสภาพแวดล้อมนี้
รายงานที่ผู้ใช้ส่งเป็น Python 3.13 และ Windows tests ตัวอื่นผ่าน
ยังไม่ใช่หลักฐานว่าชื่อภาษาไทยเองผิด หรือจำเป็นต้องเปลี่ยนชื่อบัญชี Windows

## ติดตั้ง
แตก ZIP 0.5.14 ลงโฟลเดอร์ใหม่ แล้วเปิด Install-to-D.cmd ในโฟลเดอร์นั้น
ไม่ใช้ตัวติดตั้งจาก 0.5.13
ถ้ายังมี error ให้ส่ง build-tests.log ของ 0.5.14
แพ็กเกจยังเป็น Source Preview ซึ่งบิลด์ EXE บนเครื่อง Windows หลัง tests ผ่าน


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.13 — แก้ครบ 3 errors จาก build-tests.log

จาก log Windows/Python 3.14 ที่ผู้ใช้ส่ง:
1. test_existing_schema_migrates: old.db ถูกเปิดค้าง → WinError 32 ตอน cleanup
2. test_move_and_restore_whole_ncn_bundle: อ่าน manifest UTF-8 ด้วย cp874 → UnicodeDecodeError
3. test_file_changed_during_hash_is_not_linked_using_stale_content:
   songs-index-cache.sqlite3 ถูกเปิดค้าง → WinError 32 ตอน cleanup

## แก้ไข
- ใช้ contextlib.closing ครอบ SQLite connection ของชุดทดสอบทั้งสองจุด
  รักษา transaction context เดิมไว้ด้วย; with connection อย่างเดียวไม่ได้ปิด connection
- ระบุ encoding='utf-8' ในทุกจุดอ่าน JSON manifest/report ของ test_duplicates
- แก้เมนูสำรองข้อมูลให้ปิด connection ฐานข้อมูลปลายทางด้วย closing เช่นกัน
- ไม่ซ่อน error, ไม่เพิ่ม skip, ไม่ละเว้น cleanup และไม่ปิด build test gate
- ยังคงคุณสมบัติทั้งหมดจาก 0.5.12 รวมการทดสอบ SoundFont

## ตรวจสอบ
188 tests: ผ่าน 182 ข้าม 6 บน Linux
รันทั้ง 3 กรณีอีกครั้งโดยจำลอง Path.read_text ค่าเริ่มต้น cp874
เก็บ reference ของ SQLite connections ไว้ทั้งหมดเพื่อไม่พึ่ง garbage collection
ตรวจว่า execute หลังจบงานต้องแจ้ง connection closed: ผ่านครบ 3 กรณี
ตรวจเมนูสำรองข้อมูล: ปิด source/destination แล้ว และฐานสำรองยังอ่าน schema ได้
ยังไม่ได้บิลด์ EXE หรือรัน Windows/Python 3.14 จริงที่นี่
log จากเครื่องผู้ใช้ยืนยันชุดทดสอบ Windows Uniscribe ทั้งสี่รายการผ่านในรุ่นก่อน

## ติดตั้ง
แตก ZIP รุ่นนี้ลงโฟลเดอร์ใหม่ เปิด Install-to-D.cmd
ใช้ไฟล์จาก 0.5.13 ไม่ใช่ตัวติดตั้งในโฟลเดอร์รุ่นเก่า
ถ้ามีข้อผิดพลาดใหม่ ส่ง build-tests.log จากโฟลเดอร์ 0.5.13
แพ็กเกจเป็น Source Preview ต้องให้ Windows สร้าง EXE หลัง tests ผ่าน

เอกสาร SQLite context manager:
https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.12 — แก้โฟลเดอร์ทดสอบชนกันบน Windows

ข้อความที่ได้รับจากรุ่น 0.5.10:
test_catalog_goal_and_processed_rows_match_active_record_count
FileExistsError [WinError 183] เมื่อสร้าง Data

สาเหตุ: setUp สร้าง data/songs.db แล้ว test สร้าง Data
Windows ทั่วไปไม่แยกตัวพิมพ์เล็กใหญ่ จึงเป็นโฟลเดอร์เดียวกัน
แก้ให้ฐานข้อมูลทดสอบอยู่ app-state/songs.db แยกจาก Data ของ legacy catalog
ไม่ได้แก้หรือลบข้อมูลเพลงของผู้ใช้ และไม่ได้ปิดหรือข้ามการทดสอบที่ล้มเหลว

เพิ่ม tools/run_build_tests.py ให้ build.ps1 รันชุดทดสอบทั้งหมด
พร้อมบันทึกรายชื่อ tests และ traceback ลง build-tests.log (UTF-8)
ยังหยุดการสร้าง EXE เมื่อมี test ล้มเหลว
บันทึก Python version และระบบปฏิบัติการไว้สำหรับวินิจฉัยด้วย

## วิธีติดตั้งใหม่
แตก ZIP รุ่น 0.5.12 ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ไม่เรียกตัวติดตั้งในโฟลเดอร์ 0.5.10 เดิม
หากยังล้มเหลว ส่ง build-tests.log ในโฟลเดอร์ Source Preview ที่เพิ่งแตก
ข้อความเดิมบอก errors=4 แต่ให้ traceback มาเพียงตัวเดียว
รุ่นนี้แก้ตัวที่มีหลักฐานแล้ว อีกสามตัวยังไม่สามารถระบุสาเหตุได้
ยังไม่สรุปว่าเกี่ยวกับ Python 3.14 และยังไม่ได้ทดสอบ Windows/Python 3.14 จริง

## ตรวจสอบ
รันชุดทดสอบทั้งหมดผ่าน runner ใหม่: 188 tests ผ่าน 182 ข้าม 6 บน Linux
ทดสอบกรณีที่รายงานซ้ำโดยจำลอง mkdir ที่ตรวจชื่อแบบไม่แยกตัวพิมพ์: ผ่าน
ผลนี้ไม่ใช่การทดสอบระบบไฟล์ Windows จริง
รวมคุณสมบัติทดสอบ SoundFont จากรุ่น 0.5.11
ไม่มี Windows EXE ที่สร้างสำเร็จในแพ็กเกจ Source Preview นี้


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.11 — ทดสอบกำลังสังเคราะห์เสียงจริง

## วิธีใช้งาน
1. ยกเลิกเพลงปัจจุบันด้วย F7
2. เปิดตั้งค่า SoundFont เลือกชุดเสียงและระดับเสียงที่ต้องการใช้
3. แท็บคุณภาพและเอฟเฟกต์ → ทดสอบประสิทธิภาพเสียงจริง
4. รอโหลดและทดสอบครบ 3 ระดับ มีร้อยละ สถานะ เวลา และปุ่มยกเลิก
5. ดูค่าที่ผ่าน แล้วกดใช้ค่าที่ผ่านการทดสอบ
6. กดบันทึกสำหรับเพลงถัดไปในหน้าตั้งค่า

การทดสอบไม่ส่งเสียงออกลำโพง แต่สังเคราะห์ข้อมูล PCM จริงด้วย BASSMIDI
และ SoundFont ที่เลือกบนเครื่องที่เปิดโปรแกรม ไม่ใช้คะแนนสเปกแทนผลวัด
เครื่องมือนี้ยังไม่ได้รันทดสอบบนเครื่องผู้ใช้ผ่านแชต

## งานที่วัด
48 kHz stereo float32, บล็อกละ 480 เฟรม (10 ms)
ทดสอบ Sinc16 /512 voices, Sinc8 /256 voices, Linear /128 voices
ส่งโปรแกรม GM 0–127 กระจายใน 9 กลุ่ม รวมช่องกลอง
ส่ง 128 note-on ต่อกลุ่ม (จำนวน sample voices จริงขึ้นกับ layers ใน SoundFont)
กลุ่มละ 50 บล็อก รอบแรกดูช่วงโหลด sample ครั้งแรก รอบสองวัดช่วงต่อเนื่อง
รวมเสียงเสมือน 9 วินาทีต่อระดับ (27 วินาทีครบสามระดับ)
เวลาจริงขึ้นกับเครื่องและการโหลดชุดเสียง อาจเร็วหรือช้ากว่านี้
วัดเวลาคำสั่ง render และการส่งเหตุการณ์ต้นกลุ่มด้วย perf_counter
แยกเวลาเปิดชุดเสียงและเวลาแรกโหลดออกจากเกณฑ์ต่อเนื่อง
ตรวจ PCM ครบ มีค่าจำกัด และตรวจพบสัญญาณเสียงก่อนให้ผ่าน
ผลเก็บค่า peak ด้วย แต่ไม่ใช้การซ้อนโน้ตทดสอบเป็นเกณฑ์ความไพเราะ/ความดังเพลงจริง

## การเลือก
บล็อกเสียง 10 ms ต้องใช้เวลาเฉลี่ยไม่เกิน 3.5 ms,
เปอร์เซ็นไทล์ 95 ไม่เกิน 5 ms และค่าสูงสุดไม่เกิน 9 ms
เลือกคุณภาพสูงสุดที่ผ่านจากสามชุดค่าที่ทดสอบ
เกณฑ์เผื่อกำลังนี้เป็นนโยบายของโปรแกรม ไม่ใช่ใบรับรองจากผู้ผลิต
หากไม่มีระดับใดผ่าน ไม่เปลี่ยนค่าเดิม
ค่าที่กดใช้เป็นโหมดกำหนดเอง เพื่อไม่ให้การประเมินสเปกเขียนทับ
ผู้ใช้ยังต้องกดบันทึกก่อนนำไปใช้กับเพลงถัดไป
ระดับบัฟเฟอร์ 100/150/200 ms เป็นค่าตั้งต้น ไม่ใช่ผลวัด latency จริง
จำนวน voices ต่ำอาจตัดเสียงค้างของเพลงหนาแน่น

## รายงานและการยกเลิก
บันทึก JSON ใน data/audio-reports พร้อมเวลา สเปก รายการชุดเสียง
เอฟเฟกต์ เวลาโหลด ค่าเฉลี่ย/95%/สูงสุด เกณฑ์ และค่าที่แนะนำ
หากบันทึกรายงานไม่ได้ จะแจ้ง แต่ยังดูผลในหน้าต่างได้
ยกเลิกแล้วไม่ใช้ผลบางส่วน รอ native call ปัจจุบันคืนก่อนปิดและคืนทรัพยากร
ระหว่างรอโหลดครั้งใหญ่ ปุ่มยกเลิกอาจต้องรอจน BASS คืนการควบคุม
ไม่มี Tk calls จาก worker; หน้าต่างยังแสดงเวลาที่ผ่านไป
ไม่อ่านบันทึกผลเก่ามาใช้เองอัตโนมัติ

## ขอบเขตที่ยังไม่ได้วัด
นี่เป็น offline synthesis throughput ไม่ใช่ CPU usage % ของทั้งเครื่อง
ไม่วัดเสียงจากลำโพง/ไมโครโฟน, device latency, DPC, underrun ของไดรเวอร์
ไม่ครอบคลุมทุก bank, ทุกเพลง, ทุก pitch/velocity, ภาระ GUI และโปรแกรมอื่นทุกสถานการณ์
ค่ารอบแรกไม่ใช่ cold disk benchmark เพราะ Windows อาจแคชไฟล์ไว้
จึงไม่รับรองว่าเสียงจริงจะไม่กระตุก แม้ผลสังเคราะห์ผ่าน
ควรทดลองฟังเพลงเดิมหลังใช้ค่า และทดสอบใหม่เมื่อเปลี่ยน SoundFont หรือเครื่อง

## ผลตรวจรุ่นนี้
188 tests: ผ่าน 182 ข้าม 6
เพิ่ม 8 tests: เลือกระดับจากเวลาเรนเดอร์, ขอบเขตผ่าน, สัญญาณเงียบ,
ยกเลิก, PCM เสีย/native error, แยกโหลดครั้งแรก, GM ครบ/ความคืบหน้า,
นำผลไปใช้โดยไม่บันทึก/ไม่เปิด auto กลับเอง
การทดสอบอัตโนมัติใช้ native จำลอง ยังไม่ได้รัน BASS จริง/GUI Windows
และไม่ได้สร้าง Windows EXE ในสภาพแวดล้อมนี้

อ้างอิง BASS:
https://www.un4seen.com/doc/bass/BASS_ChannelGetData.html
https://www.un4seen.com/doc/bassmidi/BASS_MIDI_StreamCreate.html


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.10 — คุณภาพเสียงอัตโนมัติจากสเปก

## เปิดใช้งาน
ตั้งค่า SoundFont → คุณภาพและเอฟเฟกต์ → เลือกคุณภาพอัตโนมัติตามเครื่อง (แนะนำ)
หรือกด “ตรวจสเปกใหม่” แล้วบันทึกสำหรับเพลงถัดไป
การติดตั้งเดิมคงค่ากำหนดเอง จนกว่าจะเปิดอัตโนมัติครั้งแรก
โหมดที่บันทึกมีผลทั้งทดลองเสียงและเล่นเพลง
ประเมินใหม่ก่อนสร้างระบบเสียงแต่ละเพลง ไม่เปลี่ยนค่ากลางเพลง
กดโปรไฟล์สำเร็จรูปหรือปิดอัตโนมัติเพื่อกำหนดเองได้

## สิ่งที่ใช้ประเมิน
- ชื่อ CPU เพื่อแสดงข้อมูล และจำนวน logical threads เป็นตัวคัดระดับเบื้องต้น
- RAM ทั้งหมดและ RAM ที่ว่างขณะประเมิน (Windows GlobalMemoryStatusEx)
- ขนาดไฟล์ SoundFont รวม เป็นตัวบ่งชี้แรงกดดันหน่วยความจำ ไม่ใช่ RAM ที่ต้องใช้จริง
- SFZ อ้างอิง sample ภายนอก จึงไม่ใช้ขนาดไฟล์ข้อความสรุปว่าใช้ RAM น้อย
- ไม่อ่าน sample ทั้งหมด ไม่ส่งข้อมูลเครื่องออกเครือข่าย

## เกณฑ์รุ่นนี้
ระดับสูง: อย่างน้อย 8 threads, RAM 15 GiB (เผื่อเครื่อง 16 GB กันพื้นที่ hardware),
RAM ว่างอย่างน้อย max(4 GiB, ขนาดชุดเสียง × 1.5 + 1 GiB)
และข้อมูลขนาดชุดเสียงครบ → Sinc 16 / 512 voices / 100 ms
ระดับเผื่อความเสถียร: Sinc 8 / 256 voices / 150 ms
ระดับทรัพยากรจำกัด: ต่ำกว่า 4 threads หรือ RAM ต่ำกว่า 4 GiB
หรือ RAM ว่างต่ำกว่า max(2 GiB, ขนาดชุดเสียง × 1.5 + 1 GiB)
→ Linear / 128 voices / 200 ms
อ่าน RAM ไม่ได้: ใช้ระดับเผื่อความเสถียรและแจ้งเหตุผล
SFZ/ไฟล์อ่านไม่ได้: ไม่เลือกขั้นสูงโดยอาศัยขนาดที่ไม่ครบ

## ข้อจำกัด
เกณฑ์เหล่านี้เป็นค่าตั้งต้นที่ผู้พัฒนากำหนด ไม่ใช่มาตรฐานคะแนนประสิทธิภาพ CPU
ไม่ได้วัดความเร็วต่อคอร์ ความร้อน power plan ภาระ CPU จริง ความซับซ้อนของทุก preset
หรือ latency/underrun ของไดรเวอร์ จึงไม่รับรองว่าค่านี้เป็นคุณภาพสูงสุดที่เล่นลื่น
การยืนยันต้องฟังและทดสอบเพลงกับ SoundFont จริงบนเครื่องนั้น
ลดจำนวน voices อาจทำให้โน้ตยาวบางเสียงถูกตัดเมื่อเพลงใช้เสียงหนาแน่น
เพิ่มบัฟเฟอร์เพิ่มความหน่วงของการตอบสนอง อาจต้องปรับชดเชยเนื้อร้อง
คุณภาพของเสียงยังขึ้นกับตัว SoundFont และชุดลำโพง
การ์ดจอไม่ได้ใช้ในการสังเคราะห์ BASSMIDI ของโปรแกรมนี้
ระบบยังรักษาการเติมบัฟเฟอร์ทุก 10 ms จากรุ่น 0.5.9

## ตรวจสอบ
180 tests: ผ่าน 174 ข้าม 6; เพิ่ม 9 tests ด้านการประเมินและการส่งค่าถึง API เสียง
ครอบคลุม RAM ไม่พอ, ข้อมูลตรวจไม่ได้, SFZ, ชุดเสียงขนาดใหญ่,
ประเมินใหม่, รักษา manual, ปุ่มโหมด, โครงสร้าง Windows API แบบจำลอง
ยังไม่ได้ทดสอบเสียง/หน้าต่าง/Windows API จริงบน Windows หรือสร้าง EXE
แพ็กเกจนี้เป็น Source Preview

อ้างอิง:
https://learn.microsoft.com/en-us/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex
https://www.un4seen.com/doc/bassmidi/BASS_ATTRIB_MIDI_SRC.html


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.9 — แก้การเติมบัฟเฟอร์ SoundFont

พบในโค้ดเดิม: จำกัดบัฟเฟอร์เล่นสดที่ 40–200 ms (ค่าเริ่มต้น 80 ms)
แต่ไม่ได้กำหนด BASS_CONFIG_UPDATEPERIOD ซึ่งค่าเริ่มต้นของ BASS คือ 100 ms
ค่าบัฟเฟอร์ต่ำกว่ารอบเติมทำให้เสี่ยงเสียงขาดช่วง เป็นข้อผิดพลาดที่แก้ได้จากโค้ด
ยังไม่ยืนยันว่าเป็นสาเหตุทั้งหมดบนเครื่องผู้ใช้

## สิ่งที่แก้
- ตั้งรอบเติมเสียง 10 ms และความจุบัฟเฟอร์ 500 ms ก่อนสร้าง live MIDI stream
- ความยาวใช้งานจริงยังเป็นค่าที่เลือก 40–200 ms ไม่ได้เพิ่มความหน่วงเป็น 500 ms
- ใช้กับทั้งเล่นเพลงและทดลองเสียง และกับค่าที่บันทึกจากรุ่นเก่า
- รักษาคุณภาพ จำนวนเสียง และรายการ SoundFont ที่ผู้ใช้ตั้งไว้
- เพิ่มโปรไฟล์ “เน้นเสียงต่อเนื่อง”: Sinc 8 / 256 voices / 150 ms
- หากตั้งค่าระบบเสียงไม่สำเร็จ แจ้งข้อผิดพลาดและคืนทรัพยากร
- ไม่เปลี่ยนการตั้งค่าบัฟเฟอร์เล่นสดเมื่อถอดเสียง offline

## วิธีลอง
ติดตั้ง/บิลด์ Source Preview รุ่นนี้ตามขั้นตอนเดิม แล้วเปิดโปรแกรมใหม่
ลองเพลงเดิมและ SoundFont เดิมก่อน โดยใช้ค่าคุณภาพเดิมเพื่อเทียบผล
หากยังสะดุด เปิดตั้งค่า SoundFont → คุณภาพ → เน้นเสียงต่อเนื่อง
กดบันทึกสำหรับเพลงถัดไป แล้วเริ่มเพลงใหม่
บัฟเฟอร์ 150 ms เพิ่มเวลาตอบสนองเสียงเมื่อเทียบกับ 80 ms
อาจต้องปรับชดเชยเนื้อร้องตามที่ใช้งานจริง

หากยังสะดุด ขอชื่อ/ขนาด SoundFont, เพลงตัวอย่าง, CPU/RAM และอุปกรณ์เสียง
พร้อมระบุว่าสะดุดตลอดเพลงหรือเฉพาะเริ่มเพลง/เปลี่ยนเครื่องดนตรี
การโหลดตัวอย่างเสียงระหว่างเล่นเป็นอีกสาเหตุที่เป็นไปได้
รุ่นนี้ยังไม่ได้เพิ่มการโหลด SoundFont ทั้งไฟล์เข้าหน่วยความจำ

## ทดสอบ
171 tests: ผ่าน 165 ข้าม 6 ไม่มีข้อผิดพลาด
เพิ่มทดสอบลำดับการกำหนดค่าก่อนสร้าง stream ทุกค่าบัฟเฟอร์
ทดสอบคืนทรัพยากรเมื่อตั้งค่าล้มเหลว และแยก offline ออกจาก live
เป็นการทดสอบโค้ดและ native API จำลองบน Linux
ยังไม่ได้ฟังเสียงจริงบน Windows และไม่ได้สร้าง Windows EXE
ไม่รับรองว่าอาการกระตุกบนเครื่องผู้ใช้หายจนกว่าจะได้ผลทดสอบจริง

เอกสารผู้ผลิต:
https://www.un4seen.com/doc/bass/BASS_CONFIG_UPDATEPERIOD.html
https://www.un4seen.com/doc/bass/BASS_ATTRIB_BUFFER.html
https://www.un4seen.com/doc/bass/BASS_CONFIG_BUFFER.html
https://www.un4seen.com/doc/bassmidi/BASS_MIDI_FontLoad.html


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.8 — อัปเดตเฉพาะเพลงใหม่หรือที่เปลี่ยน

## วิธีใช้งานที่แนะนำ
F2 → ที่เก็บเพลง → เพิ่มโฟลเดอร์ → แท็บสร้างรายการ
เลือก “อัปเดตเฉพาะเพลงใหม่ / ที่เปลี่ยน (แนะนำ)” สำหรับใช้งานประจำ
เลือก “ตรวจทั้งคลังและอ่านรายละเอียดใหม่” เมื่อต้องการตรวจละเอียด ย้ายคลัง หรือสงสัยข้อมูลผิดปกติ
เพิ่มไฟล์เพลงทันทีและเชื่อมคลังเดิมใช้ขั้นตอนตรวจล่วงหน้าแบบเดียวกัน

## การทำงานปกติ
1. นับตำแหน่งไฟล์ไม่ซ้ำและกำหนดเป้าหมาย
2. เทียบตำแหน่ง ขนาด เวลาแก้ไข ตัวระบุไฟล์ และข้อมูลการเปลี่ยนแปลงของไฟล์/ไฟล์ประกอบ
3. ไฟล์เดิมที่ข้อมูลครบ รุ่นตัวอ่านตรงกัน และลายเซ็นไม่เปลี่ยน: ใช้ข้อมูลเดิม ไม่อ่านเนื้อหาหรือรายละเอียดซ้ำ
4. ไฟล์ใหม่หรือที่เปลี่ยน: ตรวจชนิด/ขนาดและ SHA-256 เทียบผลตรวจที่บันทึกไว้ก่อนอ่านรายละเอียด
5. ถ้าเหมือนรายการเดิมจริง: เก็บรายการหลักและตำแหน่งสำเนา ไม่สร้างเพลงซ้ำในผลค้นหา
6. อ่านรายละเอียดและเพิ่ม/อัปเดตเฉพาะรายการที่จำเป็น
7. สรุปผลและบันทึก CSV ครบทุกรายการที่ดำเนินการ

ไม่มีการตรวจเนื้อหาทั้งคลังซ้ำโดยอัตโนมัติหลังจบทุกงานแล้ว
การตรวจเพลงซ้ำทั้งคลังยังเปิดได้จากแท็บเพลงซ้ำเมื่อต้องการ

## ผลลัพธ์ห้ากลุ่ม
- เดิมไม่เปลี่ยน: ใช้รายการเดิม อาจตรวจเพียงข้อมูลไฟล์ หรือยืนยันด้วย SHA-256 เมื่อเวลาเปลี่ยนแต่เนื้อหาเหมือนเดิม
- เพิ่มใหม่: ไม่มีรายการเดิมและเนื้อหาไม่ซ้ำ
- อัปเดต: ตำแหน่งเดิมแต่รายละเอียด/ไฟล์เปลี่ยน หรือจำเป็นต้องอ่านใหม่
- ซ้ำกับรายการเดิม: ตำแหน่งอื่นหรือรายการอื่นมีเนื้อหาและไฟล์ประกอบเหมือนกัน ใช้รายการหลักเดิม
- อ่านไม่ได้: ไฟล์หาย เสีย ไม่ครบเงื่อนไข หรือไม่รองรับ โดยมีรายละเอียดในรายงาน
ตัวเลขซ้ำในรอบนี้หมายถึงรายการที่นำเข้าเป็นสำเนา ไม่ใช่จำนวนสำเนาทั้งหมดในคลัง
รายการหลักที่เลือกเก็บอาจอยู่ในกลุ่มอัปเดต ส่วนสำเนาแสดงแยกในหน้าตรวจเพลงซ้ำ

## รักษาข้อมูลเดิม
- อัปเดตตำแหน่งเดิมโดยรักษา ID คิว เพลงโปรด และข้อมูลที่ผู้ใช้แก้เอง
- ให้ความสำคัญกับรายการหลักที่ผู้ใช้เลือก คิว/เพลงกำลังเล่น ข้อมูลแก้ไข และเพลงโปรด
- ชื่อหรือรหัสเหมือนกันแต่เนื้อหาต่างกัน เก็บเป็นคนละเวอร์ชัน ไม่เขียนทับ
- ข้อมูลใหม่ที่อ่านได้ดีกว่าสามารถเติมชื่อ/ศิลปินที่ขาดในรายการหลักได้ โดยไม่ทับข้อมูลแก้ไขของผู้ใช้
- ถ้าไฟล์หลักเปลี่ยนเนื้อหาและมีสำเนาเดิมที่ยังตรวจได้ จะย้ายความสัมพันธ์ของกลุ่มเก่าไปชุดที่ยังเหมือนเดิม
- ไม่ลบแถวรายการเก่า และไม่มีการย้ายหรือลบไฟล์อัตโนมัติ

## เงื่อนไขที่ต้องตรวจใหม่
- ไฟล์หรือไฟล์ประกอบเปลี่ยน เช่น LYR/CUR/LRC/SNF
- ชื่อเพลงหรือศิลปินยังไม่ครบ หรือไฟล์ยังไม่พร้อมเล่น
- มีการเปลี่ยนรุ่นตัวอ่านรายละเอียด (ไม่ใช่ทุกครั้งที่เปลี่ยนหน้าตาโปรแกรม)
- เลือกโหมดตรวจทั้งคลัง
NCN ต้องเทียบ MIDI + LYR + CUR เป็นชุด และพิจารณา LRC/SNF ที่มี
ถ้าไฟล์เปลี่ยนระหว่างตรวจ จะไม่บันทึกผลแคชนั้นและแจ้งให้ตรวจรอบถัดไป

## ดัชนีผลตรวจ
ครั้งแรกหลังอัปเดตจะเตรียมข้อมูลไฟล์จากรายการเดิม และคำนวณค่าเนื้อหาเดิมเฉพาะกลุ่มขนาดที่เกี่ยวข้องเมื่อจำเป็น
จึงอาจใช้เวลามากกว่ารอบถัดไป ข้อมูลนี้เป็นข้อมูลช่วยเร่งความเร็ว ไม่ใช่ฐานเพลงหลัก
เก็บใน songs-index-cache.sqlite3 ข้างฐาน songs.sqlite3 และสร้างใหม่ได้โดยไม่เปลี่ยน ID เพลง
ลายเซ็นข้อมูลไฟล์เป็นตัวคัดกรอง ไม่ใช่หลักฐานยืนยันเนื้อหาทุกกรณี
Windows ใช้ ChangeTime เมื่อระบบไฟล์รองรับ หากข้อมูลนั้นไม่พร้อม จะตรวจเนื้อหาแทนการข้ามโดยเชื่อเวลาอย่างเดียว
สำหรับไฟล์ที่ถูกแก้จากภายนอกตำแหน่งที่กำลังอัปเดต หรือกรณีสงสัยข้อมูลเวลา ให้เลือกตรวจทั้งคลัง
ก่อนย้ายหรือรีไซเคิลยังตรวจเนื้อหาใหม่อีกครั้ง ไม่ใช้ผลแคชเพียงอย่างเดียว

## คลังเดิมและ DBF
นำเข้ารายละเอียดจาก DBF เฉพาะเมื่อดัชนีเดิมเปลี่ยน หรือเลือกโหมดตรวจทั้งหมด
แยกการอ่านข้อมูล DBF ออกจากการตรวจไฟล์เพลง จึงไม่อ่าน MIDI เดิมทั้งชุดซ้ำเพราะเปิดเมนูนำเข้าอีกครั้ง
เมื่อพบโครงสร้างคลังเดิมแบบมาตรฐาน จะนับไฟล์ใน Songs และไม่ดึงไฟล์เสียงของตัวโปรแกรมมาปะปน

## หน้าความคืบหน้า
- เป้าหมาย ตรวจแล้ว รายการพร้อมใช้ ข้าม และซ้ำในรอบนี้
- แสดงจำนวนเดิมไม่เปลี่ยน เพิ่มใหม่ อัปเดต พร้อมร้อยละแต่ละขั้นตอน
- ตารางผลล่าสุด 300 รายการ พร้อมรหัส ชื่อ ศิลปิน ตำแหน่ง และผลจำแนก
- CSV เก็บทุกรายการ รวมคำเตือนและเหตุผลที่ข้าม
- เวลา ความเร็ว เวลาเหลือโดยประมาณ และจำนวน MB ระหว่างอ่านเนื้อหาไฟล์ใหญ่
- ยกเลิกโดยเก็บส่วนที่ทำเสร็จ และซ่อนหน้าต่างให้ทำงานต่อได้
- ไม่แสดงร้อยละสมมติขณะยังนับเป้าหมาย และไม่บังคับเป็น 100% เมื่อยกเลิก

## ตรวจทั้งคลัง
รวมตำแหน่งที่ตั้งค่าและรายการเดิมนอกโฟลเดอร์ที่เลือก โดยไม่ดึงโฟลเดอร์กักเพลงซ้ำกลับเข้ามา
ตรวจเนื้อหาใหม่แม้ข้อมูลเวลาเหมือนเดิม และอ่านรายละเอียดใหม่ตามความจำเป็น
ไฟล์เหมือนกันจริงสามารถใช้รายละเอียดของชุดหลักที่ตรวจแล้ว ไม่ต้องถอดข้อมูลซ้ำทุกสำเนา
จะช้ากว่าโหมดอัปเดตปกติ แต่เหมาะสำหรับตรวจยืนยันและซ่อมดัชนี
ไม่ลบไฟล์หายออกจากฐานโดยอัตโนมัติ เพื่อรักษาคิวและประวัติ

## อัปเดตโปรแกรม
ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ต้องมี Python 3.11+ Windows 64 บิตและอินเทอร์เน็ตสำหรับสร้าง EXE
เปิด D:\newKaraoke\Karaoke\X-Stage Karaoke.cmd และตรวจรุ่นเป็น 0.5.8
ตัวติดตั้งเก็บ Data และไฟล์เพลงเดิมไว้

## ผลทดสอบ
168 รายการ: ผ่าน 162 ข้าม 6 ไม่มีข้อผิดพลาด
เพิ่ม 24 การทดสอบด้านแคช/ไฟล์เปลี่ยน/ตรวจซ้ำก่อนอ่านรายละเอียด/ข้อมูลไม่ครบ/รุ่นตัวอ่าน
รวมรักษา ID/เพลงโปรด/ข้อมูลแก้ไข กลุ่มเก่าเมื่อไฟล์หลักเปลี่ยน และการยกเลิกโดยไม่รายงานผิดว่าเพลงเสีย
ตรวจกรณีไฟล์แก้แต่คืนเวลาเดิม การเปลี่ยนขณะอ่าน การไม่มีข้อมูลเวลาเชื่อถือได้ และพาธ Windows
ข้าม 4 Windows Uniscribe, 1 native BASS และ 1 opt-in Windows Recycle Bin
ยังไม่ได้ทดสอบหน้าต่าง/Windows API/ถังรีไซเคิลจริงหรือสร้าง Windows EXE ในสภาพแวดล้อมนี้

INCREMENTAL_BENCHMARK.json บันทึกผลทดลองไฟล์ MIDI ตัวอย่างขนาดเล็ก
ไฟล์เดิม 500 ไฟล์: รอบถัดไปอ่านเนื้อหา 0 ครั้ง อ่านรายละเอียด 0 ครั้ง
ไฟล์เดิม 500 + ใหม่ 100 (สำเนา 90/เพลงใหม่ 10): อ่านเนื้อหา 100 ครั้ง อ่านรายละเอียด 10 ครั้ง
เป็นการทดลองแกนประมวลผลบน Linux ไม่รวม GUI/เสียง และไม่ใช่การรับประกันความเร็วเครื่องผู้ใช้
ทดสอบซ้ำได้ด้วย python tools/benchmark_incremental.py --songs 500

อ้างอิงทางเทคนิค Windows file ChangeTime:
https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info


## บันทึกรุ่นก่อน (แนวทางใช้งานปัจจุบันให้ยึดข้อความด้านบน)

# X-Stage Karaoke 0.5.7 — ศูนย์ความคืบหน้างานเพลง

รุ่นนี้รวมระบบตรวจ/เก็บ/ย้าย/รีไซเคิลเพลงซ้ำ และปรับงานนำเข้า/สร้างสารบัญให้เห็นความคืบหน้าชัดเจน

## ขั้นตอนใช้งาน
1. กด F2 → ที่เก็บเพลง → เลือกประเภทและเพิ่มโฟลเดอร์
2. ไปแท็บสร้างรายการ → เริ่มสร้างรายการเพลง → ยืนยัน
3. หน้าต่างศูนย์การนำเข้าจะแสดงการนับจำนวนก่อนเริ่มอ่านไฟล์
4. รออ่านและบันทึกข้อมูล → ตรวจเนื้อหาเพลงซ้ำ → บันทึกผล → เสร็จเรียบร้อย
5. ปิดหน้าต่างแล้วค้นหาเพลง หรือเปิดรายงานสรุป/รายการทั้งหมด
เพิ่มไฟล์เพลงทันทีและเชื่อมคลังเพลงเดิมใช้หน้าต่างความคืบหน้าเดียวกัน

## หน้าต่างใหม่
- หัวข้อขั้นตอนและร้อยละของขั้นตอนที่ทราบจำนวนแล้ว
- ระหว่างนับ/สำรอง/เตรียมงาน แสดงแถบเคลื่อนไหว ไม่สร้างร้อยละสมมติ
- เป้าหมายเพลง ตรวจแล้ว อ่านข้อมูลได้ ข้าม/อ่านไม่ได้ และรายการซ้ำที่ซ่อน
- ชื่อเพลง รหัส ศิลปิน และตำแหน่งไฟล์ของรายการที่ทำเสร็จ
- แสดง 300 รายการล่าสุดในหน้าจอ และเก็บรายงานครบทุกไฟล์ที่ตรวจในขั้นอ่านข้อมูล
- เวลาใช้ไป ความเร็วต่อวินาที และเวลาเหลือโดยประมาณของขั้นตอนนั้น
- ไฟล์ขนาดใหญ่ที่ตรวจเนื้อหาซ้ำ แสดงจำนวน MB ที่อ่านแล้วด้วย
- สัญญาณหน้าต่างตอบสนองและเวลาตั้งแต่ผลล่าสุด ช่วยแยกงานกำลังทำกับงานรอผล
- ยกเลิกงานโดยรอชุดปัจจุบันบันทึกให้เสร็จ และเก็บส่วนที่ทำเสร็จไว้
- ซ่อนหน้าต่างให้ทำงานต่อ แล้วเปิดกลับด้วยปุ่ม “เปิดหน้าต่างความคืบหน้า”
- เมื่อเสร็จ ยกเลิก หรือผิดพลาด แสดงสถานะแตกต่างกัน ไม่บังคับร้อยละเป็น 100 เมื่อยกเลิก

## ความหมายตัวเลข
เป้าหมายนับไฟล์ชนิดที่รองรับในโฟลเดอร์ที่เลือก ไม่รวม LYR/CUR/LRC/SNF ซึ่งเป็นไฟล์ประกอบ
ไฟล์ชนิดที่ยังไม่รองรับจะแสดงเป็นรายการข้ามแยกต่างหาก จึงอาจมีจำนวนข้ามนอกเป้าหมาย
ตรวจแล้วนับรายการที่อ่านสำเร็จหรือพบข้อผิดพลาดแล้วจากแผนงาน
รายการที่อ่านได้จะส่งเข้ารายการล่าสุดหลังบันทึกชุดนั้นลงฐานข้อมูลสำเร็จ
ไฟล์เนื้อหาซ้ำยังนับเป็นไฟล์ที่ตรวจแล้ว ส่วนจำนวนซ้ำแสดงแยกและซ่อนจากผลค้นหาเป็นค่าเริ่มต้น
ถ้าโฟลเดอร์ซ้อนกัน จะนับตำแหน่งไฟล์เดียวกันครั้งเดียว
แผนงานเป็นภาพ ณ ตอนนับ: ไฟล์ที่เพิ่มภายหลังให้นำเข้าในรอบถัดไป
ถ้าไฟล์ในแผนหายระหว่างงาน จะบันทึกเป็นอ่านไม่ได้ แต่จำนวนเป้าหมายจะไม่แกว่ง
ร้อยละและ ETA แสดงแยกแต่ละขั้นตอน โดย ETA เป็นค่าประมาณซึ่งเปลี่ยนตามความเร็วจริง

## รายงาน
- รายงานสรุป: จำนวน ผลตรวจ เหตุผลที่ข้าม เวลาเริ่ม ระยะเวลา และตำแหน่งรายงานทั้งหมด
- “เปิดรายการทั้งหมด”: เปิด CSV ด้วยโปรแกรมที่ตั้งไว้ใน Windows เช่น Excel
- CSV เก็บลำดับ เวลา ผลตรวจ รหัส ชื่อเพลง ศิลปิน ไฟล์ และรายละเอียด/คำเตือน
- บันทึกทีละช่วงระหว่างทำงาน ไม่ต้องรอให้ครบทั้งหมดก่อนจึงมีรายงาน
- หากงานผิดพลาด หน้าต่างแสดงสาเหตุและเก็บรายงานส่วนที่ตรวจแล้ว

## การเพิ่มความเร็วและควบคุมหน่วยความจำ
- เดินโฟลเดอร์เพื่อสร้างแผนงานครั้งเดียว แล้วอ่านจากแผนที่บันทึกชั่วคราวบนดิสก์
- ไม่นำรายชื่อเพลงทั้งคลังมาเก็บค้างในลิสต์หน่วยความจำ
- อ่าน/บันทึกทีละ 100 รายการ ใช้ธุรกรรมเป็นชุด ไม่ล็อก SQLite ขณะอ่านไฟล์
- อัปเดตข้อมูลหน้าต่างประมาณไม่เกิน 10 ครั้ง/วินาที ยกเว้นการเปลี่ยนขั้นตอน/จบงาน
- จำกัดข้อมูลล่าสุดในคิวและตารางไม่เกิน 300 รายการ แต่ CSV เก็บครบ
- ใช้แคชรายชื่อโฟลเดอร์ร่วมกันภายในงานเดียว และเริ่มแคชใหม่ทุกงาน
- ตรวจขนาดก่อน SHA-256 และตรวจชนิดไฟล์ซ้ำเพียงชุดหลักของกลุ่มที่เนื้อหาเหมือนกัน
- ยังตรวจเนื้อหาใหม่ก่อนย้าย/รีไซเคิล และไม่ย้ายไฟล์ที่รายการอื่นใช้อยู่ร่วมกัน
- ทำงานไฟล์/ฐานข้อมูลใน worker โดยแก้หน้าจอเฉพาะเธรดหลัก
ไม่มีการรับประกันความเร็วเท่ากันทุกเครื่อง ไฟล์ใหญ่ ไดรฟ์เครือข่าย และชุดเพลงจริงอาจต่างจากตัวอย่างมาก

## เพลงซ้ำ
F2 → เพลงซ้ำ → ตรวจและจัดการเพลงซ้ำ
เก็บไฟล์/ซ่อนรายการซ้ำเป็นค่าเริ่มต้น เลือกรายการหลัก ย้ายแยกพร้อม restore.json หรือส่งเข้าถังรีไซเคิลหลังยืนยัน
ตรวจ NCN ทั้ง MIDI/LYR/CUR รวม LRC/SNF ที่มี ไม่ยึดชื่อหรือรหัสอย่างเดียว
ไม่มีการย้ายหรือลบไฟล์อัตโนมัติ รายละเอียดเพิ่มเติมใน DUPLICATE_GUIDE_TH.md

## อัปเดต
ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ต้องมี Python 3.11+ Windows 64 บิต และอินเทอร์เน็ตสำหรับสร้าง EXE
เปิด D:\newKaraoke\Karaoke\X-Stage Karaoke.cmd หลังติดตั้ง และตรวจรุ่นเป็น 0.5.7
ตัวติดตั้งเก็บ Data และไฟล์เพลงเดิมไว้

## ผลตรวจสอบ
144 รายการ: ผ่าน 138 ข้าม 6 ไม่มีข้อผิดพลาด
เพิ่มการทดสอบเป้าหมายก่อนเริ่ม ไฟล์ซ้อน/เปลี่ยนระหว่างงาน ความคืบหน้า CSV ครบ
การบันทึกข้อมูลก่อนรายงาน การยกเลิก/ข้อผิดพลาด ตัวเลขร้อยละ/ETA เป้าหมาย DBF และคิวข้อมูลจำกัด
ทดสอบ pipeline จริงใน worker รวมสร้างสารบัญ ตรวจซ้ำ และรายงานจบงาน
ข้าม 4 Windows Uniscribe, 1 native BASS และ 1 opt-in Windows Recycle Bin
ยังไม่ได้ทดสอบหน้าต่างบน Windows จริงหรือสร้าง Windows EXE ในสภาพแวดล้อมนี้
PROGRESS_BENCHMARK.json เป็นผลทดลอง MIDI ตัวอย่างเหมือนกัน 500 ไฟล์ขนาดเล็กบน Linux
ไม่นับการสร้างไฟล์ตัวอย่าง ไม่รวม GUI/เสียง และไม่ใช่การทำนายความเร็วคลังของผู้ใช้
ทดลองบนเครื่องตัวเองได้ด้วย python tools/benchmark_index_jobs.py --songs 500


## บันทึกรุ่นก่อน (วิธีใช้งานปัจจุบันให้ยึดข้อความด้านบน)

# X-Stage Karaoke 0.5.6 — ตรวจและจัดการเพลงซ้ำ

## เปิดใช้งาน
F2 → จัดการข้อมูลเพลง → แท็บ “เพลงซ้ำ” → “ตรวจและจัดการเพลงซ้ำ”

## ค่าเริ่มต้น: เก็บไฟล์ / ซ่อนรายการซ้ำ
หลังเพิ่มเพลงหรือสร้างรายการผ่านงานนำเข้าหลัก ระบบจะตรวจเนื้อหาไฟล์ซ้ำ
เก็บไฟล์ต้นฉบับทั้งหมดไว้ และแสดงรายการหลักเพียงหนึ่งรายการในผลค้นหา
คลังเดิมที่มีอยู่แล้วให้กดตรวจซ้ำหนึ่งครั้งเพื่อปรับรายการ
ไม่มีการย้ายหรือลบไฟล์อัตโนมัติ

ตรวจ SHA-256 ของเนื้อหาไฟล์ ไม่ยึดชื่อเพลง รหัส หรือชื่อไฟล์อย่างเดียว
NCN เทียบทั้ง MIDI + LYR + CUR และต้องมีไฟล์ประกอบครบคู่
ถ้ามี LRC หรือ SNF จะเทียบไฟล์ประกอบนั้นด้วย (ไม่ได้เพิ่มตัวเล่น SNF ใหม่)
เพลงชื่อเหมือนกันแต่เนื้อหาหรือไฟล์ประกอบต่างกันจะเก็บทั้งสองชุด
ไฟล์เสียงเดียวกันแต่เข้ารหัสใหม่ไม่ถือเป็นไฟล์เหมือนทุกไบต์

## การเลือกรายการหลัก
ระบบให้ความสำคัญกับรายการในคิว/กำลังเล่น ข้อมูลแก้ไข และเพลงโปรด
เก็บ ID และข้อมูลของทุกรายการไว้ ไม่ลบแถวฐานข้อมูล
เพลงโปรดที่อยู่ในสำเนายังแสดงเป็นดาวและค้นหาในหมวดเพลงโปรดได้ผ่านรายการหลัก
ปุ่ม “ใช้ชุดที่เลือกเป็นรายการหลัก” เปลี่ยนชุดหลักได้ และจำตัวเลือกไว้ในการตรวจครั้งถัดไป

## ย้ายชุดซ้ำ
เลือกแถวไฟล์ซ้ำ → “ย้ายชุดที่เลือก” → เลือกปลายทาง → ตรวจตำแหน่งและยืนยัน
ระบบตรวจเนื้อหาซ้ำอีกครั้งและตรวจว่าชุดหลักยังอ่านได้ก่อนย้าย
ย้ายไฟล์พร้อม LYR/CUR/LRC/SNF ที่มีไปโฟลเดอร์ใหม่ชื่อไม่ซ้ำ
มี restore.json บันทึกตำแหน่งเดิม ตำแหน่งใหม่ และค่า SHA-256 ทุกไฟล์
โฟลเดอร์กักไฟล์ซ้ำจะไม่ถูกนำกลับเข้ารายการเมื่อสร้างสารบัญอีก
ถ้าย้ายผิดพลาดจะพยายามย้ายกลับและเก็บบันทึกไว้

## กู้คืนชุดที่ย้าย
กด “กู้คืนชุดที่ย้าย” แล้วเลือก restore.json ของชุดนั้นและยืนยัน
ตรวจเนื้อหาไฟล์ก่อนย้ายกลับ ไม่เขียนทับไฟล์ที่มีอยู่
รองรับบันทึกงานย้ายที่ค้างกลางทางเมื่อไฟล์แต่ละส่วนยังตรวจสอบได้
หากไฟล์เปลี่ยนหรือปลายทางเดิมมีไฟล์อยู่ จะหยุดและแสดงข้อผิดพลาด

## ส่งเข้าถังรีไซเคิล
เลือกแถวไฟล์ซ้ำ → “ส่งชุดที่เลือกเข้าถังรีไซเคิล” → ตรวจตำแหน่งและยืนยัน
ใช้ Windows IFileOperation พร้อม RECYCLEONDELETE ไม่มีทางเลือกเรียก permanent-delete แทน
ถ้า Windows ทำรายการไม่ได้ จะแจ้งข้อผิดพลาดและบันทึกไฟล์ส่วนที่ยังอยู่
การทำงานหลายไฟล์ผ่าน Windows อาจสำเร็จเพียงบางส่วน ให้ดูบันทึก recycle-*.json
กู้คืนผ่าน Recycle Bin ของ Windows แล้วสร้างรายการเพลง/ตรวจซ้ำอีกครั้ง
ไม่มีการลบไฟล์จริงจากการทดสอบในระบบผู้ใช้โดยอัตโนมัติ

## รายการที่ไม่อนุญาตให้ย้ายหรือลบ
- รายการหลัก
- สำเนาที่อยู่ในคิว กำลังเล่น เป็นเพลงโปรด หรือมีข้อมูลแก้ไขไว้
- ไฟล์/ไฟล์ประกอบที่รายการอื่นใช้อยู่ร่วมกัน รวม hardlink และตำแหน่งอ้างถึงไฟล์เดียวกัน
- ชุดหลักหาย อ่านไม่ได้ เนื้อหาเปลี่ยน หรือชุด NCN ไม่ครบ
เลือกเก็บรายการที่มีข้อมูลสำคัญเป็นชุดหลัก แล้วจัดการสำเนาอื่นแทน

## การสำรองและสถานะ
สำรองฐานข้อมูลก่อนเปลี่ยนการซ่อน ย้าย หรือส่งเข้าถังรีไซเคิล
ไฟล์ที่ย้าย/รีไซเคิลยังมีรายการประวัติอยู่ในหน้าตรวจเพลงซ้ำ
การยกเลิกตรวจซ้ำก่อนจบไม่เขียนผลการซ่อนชุดใหม่
หน้าต่างจัดการทำงานเบื้องหลัง และปิดปุ่มดำเนินการซ้ำระหว่างงานเดิม

## อัปเดต
ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ต้องมี Python 3.11+ Windows 64 บิต และอินเทอร์เน็ตสำหรับสร้าง EXE
หลังติดตั้ง เปิด D:\newKaraoke\Karaoke\X-Stage Karaoke.cmd ตรวจรุ่นให้เป็น 0.5.6
ตัวติดตั้งเก็บ Data และไฟล์เพลงเดิมไว้

## ผลทดสอบ
130 รายการ: ผ่าน 124 ข้าม 6 ไม่มีข้อผิดพลาด
ครอบคลุมไฟล์ซ้ำข้ามโฟลเดอร์ ชุด NCN/LRC/SNF ต่างกัน ชุดไม่ครบ
การเก็บคิว/ID/ข้อมูลแก้ไข/เพลงโปรด การเปลี่ยนชุดหลักและจำตัวเลือก
ย้าย-กู้คืน ไม่เขียนทับ ไฟล์เปลี่ยน ชุดหลักหาย hardlink ย้ายล้มเหลวและย้อนกลับ
งานย้ายขาดช่วง การไม่สแกนโฟลเดอร์กักกลับเข้าคลัง และการยืนยันก่อนดำเนินการ
การทดสอบถังรีไซเคิลใช้ตัวจำลองขอบเขต Windows และมี native test แบบ opt-in
ยังไม่ได้ทดสอบ Windows GUI/ถังรีไซเคิลจริงหรือสร้าง Windows EXE ในสภาพแวดล้อมนี้
เปิด native test บน Windows ได้ด้วย XSTAGE_TEST_RECYCLE=1 แล้วรัน unittest
การทดสอบนี้ใช้เฉพาะไฟล์ชั่วคราวที่สร้างขึ้นเอง ไม่ใช้เพลงของผู้ใช้

อ้างอิง Windows recycle flags:
https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags


## บันทึกรุ่นก่อน

# X-Stage Karaoke 0.5.5 — กำหนดที่เก็บเพลงและสร้างรายการแบบ Lister

รุ่นนี้ปรับขั้นตอนตามแนวทางคู่มือบนเว็บไซต์ eXtreme Karaoke
เป็นการปรับโปรแกรม X-Stage ไม่ใช่โปรแกรม eXtreme และไม่ได้เพิ่มตัวอ่านรูปแบบเฉพาะที่ยังไม่รองรับ

## วิธีใช้งาน
1. กด F2 หรือคลิกขวา → จัดการข้อมูลเพลง
2. แท็บ “ที่เก็บเพลง”: เลือกประเภท แล้วกด “เพิ่มโฟลเดอร์เพลง”
   การเลือกโฟลเดอร์บันทึกตำแหน่งเท่านั้น ไม่เริ่มสแกนทันที
   ปุ่มนี้ใช้งานได้แม้กำลังสร้างรายการจากตำแหน่งชุดเดิม
3. สำหรับ NCN เลือกโฟลเดอร์แม่ที่มี Song / Lyrics / Cursor และเก็บรหัสไฟล์ให้ตรงกัน
   ระบบรองรับโฟลเดอร์ย่อยรหัสตัวแรกและชื่อไฟล์ตัวพิมพ์เล็ก/ใหญ่
4. ไปแท็บ “สร้างรายการ” แล้วกด “เริ่มสร้างรายการเพลง” และยืนยัน
5. รอจนแถบการทำงานหยุดและข้อความแจ้งผลตรวจเสร็จ แล้วปิดหน้าต่างเพื่อค้นหาเพลง
6. เพิ่มไฟล์ลงโฟลเดอร์เดิมเมื่อใด ให้กดสร้างรายการอีกครั้ง ระบบจะค้นพบไฟล์ใหม่ด้วย

## รายละเอียด
- เลือกตำแหน่งหลายแห่งได้ และเลือกทุกประเภท, NCN/MIDI/KAR, EMK, เพลงเสียง หรือวิดีโอ
- นำโฟลเดอร์ออกได้โดยไม่ลบไฟล์เพลงหรือรายการเดิมในฐานข้อมูล
- รายการตำแหน่งบันทึกใน settings.json เปิดโปรแกรมใหม่แล้วยังอยู่
- การสร้างรายการใช้ตำแหน่งชุดที่ยืนยันตอนเริ่มงาน การเพิ่มตำแหน่งระหว่างงานมีผลรอบถัดไป
- ไม่เริ่มนำเข้าคลังเดิมอัตโนมัติในค่าเริ่มต้น จึงไม่ปิดปุ่มเพิ่มเพลงตอนเปิดโปรแกรม
- สำรองฐานข้อมูลก่อนสร้างรายการ รักษา ID เพลง คิว เพลงโปรด และข้อมูลที่ผู้ใช้แก้เอง
- ตำแหน่งหาย/ไฟล์ผิดชนิด/อ่านไม่ได้ จะแสดงในรายงานตรวจเพลง
- ยกเลิกได้ เก็บข้อมูลส่วนที่ตรวจเสร็จแล้ว
- ไม่คัดลอกหรือย้ายเพลง ไฟล์ต้นฉบับอยู่ที่เดิม
- “เพิ่มไฟล์เพลงทันที” และ “นำเข้าฐานข้อมูลจากคลังเดิม” เป็นทางเลือกแยกจาก Lister
- ถ้ายังไม่กำหนดตำแหน่ง จะถามก่อนอ่านเฉพาะรายการเดิม ซึ่งไม่ค้นพบไฟล์ใหม่
- ไม่มีการอ้างว่ารองรับ XMK/XAK/XVK/RMS ที่ยังไม่มี decoder

## อัปเดต
ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ต้องมี Python 3.11+ Windows 64 บิต และอินเทอร์เน็ตสำหรับสร้าง EXE
หลังติดตั้ง เปิด D:\newKaraoke\Karaoke\X-Stage Karaoke.cmd และตรวจรุ่นให้เป็น 0.5.5
ตัวติดตั้งเก็บ Data และไฟล์เพลงเดิมไว้

## การตรวจสอบ
ทดสอบอัตโนมัติ 104 รายการ: ผ่าน 99 ข้าม 5 ไม่มีข้อผิดพลาด
ตรวจการเพิ่มตำแหน่งขณะงานยุ่ง การบันทึกไม่เริ่มสแกน การยืนยันสร้างรายการ
ไฟล์ใหม่ในโฟลเดอร์ย่อย การกรองประเภท การยกเลิก สำรองฐานข้อมูล และเก็บ ID/เพลงโปรด
ยังไม่ได้ทดสอบ GUI บน Windows จริง และไม่ได้สร้าง Windows EXE ในสภาพแวดล้อมนี้

## เอกสารอ้างอิงขั้นตอน
- https://www.karaoke-soft.com/karaoke/document/NCN2EMK.pdf (การทำสารบัญเพลง Song Data Manager / Lister)
- https://www.karaoke-soft.com/smf/index.php?topic=124853.0 (ผู้พัฒนาระบุตำแหน่งเพลงเพิ่มเติมและยกเลิกสร้างรายการ)
เอกสารที่ตรวจเป็นคู่มือ/ประกาศรุ่นเดิม ไม่ใช่การยืนยันหน้าตารุ่นล่าสุดทุกส่วน


## บันทึกรุ่นก่อน (ขั้นตอนนำเข้าให้ยึด 0.5.5 ด้านบน)

# 0.5.4 — เปิดหน้าต่างจัดการเพลงโดยตรง

คลิกขวา → จัดการข้อมูลเพลง จะเปิดหน้าต่างรวมคำสั่งโดยตรง
เปิดได้ด้วย F2 หรือปุ่ม “จัดการเพลง F2” บนแถบควบคุม
มี 10 คำสั่ง: เพิ่มโฟลเดอร์ เพิ่มไฟล์ เชื่อมคลังเดิม สร้างรายการใหม่
ยกเลิกการตรวจ รายงานตรวจ รายละเอียดเพลง แก้ข้อมูล เพลงโปรด และรายละเอียดเพลงปัจจุบัน
ปุ่มเริ่มตรวจจะปิดระหว่างงานเดิม และปุ่มยกเลิกจะเปิดให้ใช้งาน
รายละเอียด/แก้ข้อมูล/เพลงโปรด ต้องค้นหาและเลือกเพลงก่อน

อัปเดต: ปิดโปรแกรม แตก ZIP ลงโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ต้องมี Python 3.11+ Windows 64 บิต และอินเทอร์เน็ตเพื่อสร้าง EXE รุ่นใหม่
เปิดจาก D:\newKaraoke\Karaoke\X-Stage Karaoke.cmd หลังติดตั้งเสร็จ
ตรวจในรายละเอียดโปรแกรมให้เป็น 0.5.4 เพื่อยืนยันว่าเปิดรุ่นใหม่
ข้อมูล Data และไฟล์เพลงเดิมจะไม่ถูกลบโดยตัวติดตั้ง

ทดสอบ 99 รายการ: ผ่าน 94 ข้าม 5 ไม่มีข้อผิดพลาด
ครอบคลุมการคลิกเปิดหน้าต่าง เส้นทางปุ่มทั้ง 10 และสถานะขณะตรวจเพลง
ยังไม่ได้รันทดสอบ Windows GUI จริงหรือสร้าง Windows EXE ในสภาพแวดล้อมนี้


# 0.5.3 — แก้เมนูจัดการข้อมูลเพลง

- ปิดเมนูและปล่อยการจับเมาส์ก่อนเรียกคำสั่งในรอบถัดไปของหน้าจอ
- ระบุหน้าต่างเจ้าของให้ตัวเลือกโฟลเดอร์ ตัวเลือกไฟล์ และการเชื่อมคลังเดิม
- รายงานตรวจเพลงเป็นหน้าต่างลูกของโปรแกรม และข้อความเมื่อยังไม่มีรายงานมีหน้าต่างเจ้าของ
- แสดงแถบสถานะเมื่อเริ่มตรวจเพลง และไม่ซ่อนอัตโนมัติระหว่างทำงาน
- ข้อผิดพลาดจากคำสั่งเมนูจะแสดงและบันทึกใน newKaraoke.log

วิธีอัปเดต: ปิดโปรแกรม แตก ZIP ไปโฟลเดอร์ใหม่ แล้วเรียก Install-to-D.cmd
ตัวติดตั้งจะสร้าง EXE ใหม่บน Windows ก่อนอัปเดตโปรแกรม โดยเก็บ Data เดิมไว้
ต้องมี Python 3.11+ แบบ 64 บิต และอินเทอร์เน็ตสำหรับสร้าง EXE
อย่าเปิด ZIP แล้วเรียกติดตั้งจากภายใน ZIP

เมนูรายละเอียด/แก้ข้อมูล/เพลงโปรด: ค้นหาและเลือกเพลงก่อน เมนูจึงเปิดใช้งาน
ระหว่างตรวจรายการ ให้รอเสร็จ หรือใช้เมนูยกเลิกการตรวจรายการก่อนเริ่มงานใหม่

ผลทดสอบ: 98 รายการ ผ่าน 93 ข้าม 5 (Windows Uniscribe 4, native BASS 1)
เพิ่ม regression tests 6 รายการ ครอบคลุมลำดับปิดเมนู การแสดงข้อผิดพลาด
การยกเลิกตัวเลือกไฟล์ หน้าต่างเจ้าของ และสถานะระหว่างตรวจเพลง
ยังไม่ได้ทดสอบ Windows GUI จริงหรือสร้าง Windows EXE ในสภาพแวดล้อมนี้


## 0.5.2 — 2026-11-03
- Central read-only media inspector for file/folder/catalog/playlist imports.
- NCN sidecar metadata, legacy EMK embedded metadata, KAR @T, MP3 ID3 and LRC tags.
- Validate supported signatures and MIDI/archive structures; log invalid/missing/partial files.
- Rebuild metadata in batches with SQLite backup, stable IDs, user edits and favorites preserved.
- Context commands to rebuild, cancel and inspect the latest import report.
- Keep the updated source-build installer from the latest 0.5.1 package.

# X-Stage Karaoke v0.5.1 — Source Preview

- จัดเมนูคลิกขวาเป็นหมวดตามคู่มือบนเว็บไซต์ eXtreme; เชื่อมเฉพาะคำสั่งที่ทำงานจริงใน X-Stage
- ช่องพิมพ์ค้นหาซ้าย/ข้อมูลเพลงขวา/ผลค้นหา 2–4 แถว วางเป็นแถบด้านบน
- สงวนพื้นที่เนื้อร้องใต้แผงค้นหาและคิวบนจอหลัก โดยไม่ลดพื้นที่จอร้องแยก
- แถบควบคุมติดขอบล่างและซ่อนอัตโนมัติ ตัวเลือกตรึงแถบอยู่หมวดหน้าต่าง
- เพิ่มหน้าต่างเลือก Windows MIDI output แยกจาก SoundFont และรายละเอียดเพลงปัจจุบัน
- เลือกแถวใต้เมาส์ก่อนคลิกขวา; ปิดคำสั่งผลค้นหาที่หมดอายุ/กำลังค้นหา
- คง Enter เพิ่มคิวขณะเล่นและระบบ SoundFont ของ 0.5.0

## X-Stage Karaoke v0.5.0 — Source Preview

- เพิ่มแผง SoundFont หลายไฟล์พร้อมลำดับความสำคัญและ gain แยกไฟล์
- เพิ่ม float32/48 kHz, sinc interpolation, voice limit, buffering profiles และ effects ตามเพลง/กำหนดเอง
- ตรวจ metadata ของ SF2, เก็บค่าและย้ายการตั้งค่าแบบไฟล์เดียวจากรุ่นเก่า
- ทดลองเสียง 4 กลุ่มเครื่องดนตรีพร้อมหยุดและคืน native resources เมื่อปิดหน้าต่าง
- แก้ Enter ขณะเพลงกำลังเล่น/พัก/หยุด ให้เพิ่มคิว แม้คิวรอว่าง
- ตรวจด้วย native BASSMIDI offline PCM บน Linux; Windows GUI/device/build ยังรอทดสอบ

## X-Stage Karaoke v0.4.4

- จัดอันดับรหัส/ชื่อเพลงตรงก่อนเพลงที่เพียงมีคำค้นอยู่ในชื่อหรือเนื้อร้อง และจัดอันดับก่อนจำกัดจำนวนผล
- ใช้ดัชนีชื่อแบบ covering เพื่อเร่งคำค้นไทยสั้นและตรวจสถานะไฟล์ที่รองรับในหน้าผลที่จำกัดขนาด
- worker ใช้ SQLite reader เดิมพร้อมแคชรหัสผลค้นหา และล้างแคชเมื่อข้อมูลเปลี่ยน
- คำค้นใหม่ยกเลิก SQL เก่า เพื่อไม่ให้คำสั้นที่กำลังสแกนขวางคำค้นล่าสุด
- อุ่นหน้าดัชนีและคำค้นที่เคยเลือกใช้ล่าสุด 5 คำเบื้องหลัง พร้อมสถานะเตรียม/พร้อมค้นหา
- รับโฟกัสบนหน้าหลักอัตโนมัติเมื่อเปิด ไม่ต้องคลิกหรือกด F3
- เปิดฐานที่มีโครงสร้างครบโดยไม่ทำ DDL ซ้ำ และใช้ EXISTS ตรวจคลังแทนการนับทั้งหมดก่อนสร้างหน้าจอ
- ทดสอบกับฐานจริง 218,660 รายการและกรณี “รักน้องพร” ให้เลือก 20120 เป็นรายการแรก

## X-Stage Karaoke v0.4.3

- Enter บนผลค้นหาเล่นทันทีเมื่อคิวรอว่าง และเพิ่มต่อคิวเมื่อมีเพลงรออยู่
- เพิ่มยกเลิกเพลงปัจจุบันผ่าน F7 เมนูคลิกขวา และแถบควบคุม โดยคงเพลงรอคิวไว้
- แสดงเลขรุ่นพร้อม v หลังชื่อในหน้าต่าง หน้าจอเพลง จอร้อง และหน้ารีโมต

## ตัวติดตั้งปรับปรุงครั้งที่ 2

- ตรวจว่าโปรแกรมที่ติดตั้งอยู่ยังทำงานหรือไม่ โดยเทียบพาธ EXE ให้ตรงกับปลายทาง
- Install-to-D.cmd ขอปิดโปรแกรมตามปกติและรอให้บันทึกข้อมูลก่อนเริ่มอัปเดต
- ตรวจไฟล์ปลายทางก่อนคัดลอก เพื่อแจ้งกรณี EXE/DLL ยังถูกใช้งาน
- แจ้งสาเหตุไฟล์ถูกใช้งานแยกจากสิทธิ์เขียน แทนข้อความเหมารวมว่าไดรฟ์ D มีปัญหา

## X-Stage Karaoke 0.4.2

- เปิดเต็มจออัตโนมัติทุกครั้ง F11 และ Esc ยังใช้สลับออกตามบริบทเดิม
- เปลี่ยนการวาดอักษรไทยเป็น Windows Uniscribe/GDI แบบทั้งบรรทัด เพื่อวางสระและวรรณยุกต์ถูกตำแหน่ง
- ใช้ Leelawadee UI ในเนื้อร้อง HUD ช่องค้นหา และรายการคิว พร้อมเพิ่มความสูงแถวรายการ
- จัดระยะเนื้อร้องสองบรรทัดด้วยความสูงจริง และขยายขอบเขตป้ายสีให้ครอบคลุมวรรณยุกต์และสระล่าง
- ใช้ตำแหน่งจากข้อความทั้งบรรทัดในการป้ายสี แทนการวัดข้อความส่วนต้นที่อาจจัดรูปต่างกัน
- ตรวจการคืน handle ฟอนต์/bitmap ของ Windows เพื่อป้องกันการรั่วเมื่อเปิดเพลงต่อเนื่อง

## X-Stage Karaoke 0.4.1

- รับข้อความจากช่องพิมพ์จริงที่พร้อมทำงานบนหน้าหลัก แถบค้นหาปรากฏเมื่อข้อความเข้ามาโดยไม่ต้องกด F3
- พร้อมพิมพ์ใหม่หลังปิดค้นหา เพิ่มคิว หรือกลับจากแถบเลือกคิว
- รองรับข้อความที่วางหรือส่งเข้าช่องพิมพ์โดยตรง และไม่ทำอักษรตัวแรกหายหรือซ้ำ
- ปรับข้อความบนจอและเมนูให้บอกว่าพิมพ์ค้นหาได้เลย
- ทดสอบเส้นทางการพิมพ์ผ่าน Tk Entry รวมถึงการพิมพ์หลัง Esc และขณะเปิดแถบเลือกคิว

## X-Stage Karaoke 0.4.0

- ค้นหาปรากฏตั้งแต่อักษรแรก เริ่มค้นที่ idle รอบถัดไปโดยไม่มี debounce 180 ms
- worker ค้นหาเดียวรับคำค้นล่าสุด ป้องกันงานค้นหาสะสมและผลลัพธ์เก่า
- การ์ดเลือกคิวด้วย ← →; Enter เล่นเพลงที่เลือกทันที โดยคงลำดับเพลงอื่นและค่าผู้ร้อง/คีย์/ความเร็ว
- Ctrl+Enter เล่นผลค้นหาทันที; Enter ปกติยังเพิ่มคิว
- ปรับหน้าจอเป็นพื้นหลังเข้มแบบเวที พร้อม HUD เวลา BPM ห้อง จังหวะ และแถบตำแหน่งเพลง
- แถบควบคุมย่อแสดงเมื่อขยับเมาส์ ซ่อนอัตโนมัติ และตรึงจากคลิกขวาได้
- เลือกรูปพื้นหลังจากเมนูคลิกขวา เก็บสำเนาไว้ใน Data/Backgrounds ปรับความมืดและล้างภาพได้
- cache ภาพพื้นหลังแยกจากเนื้อร้อง และข้ามการวาดภาพซ้ำเมื่อสถานะไม่เปลี่ยน
- คงระบบเนื้อร้อง MIDI/NCN/EMK การป้ายสี และการตั้งค่าสองจอ

## X-Stage Karaoke 0.3.0

- เปิดมาที่จอเล่นเพลงเต็มพื้นที่หน้าต่าง ซ่อนคิวและแผงควบคุมจนเรียกใช้
- พิมพ์เพื่อเปิดแถบค้นหาในหน้าหลัก รองรับชื่อเพลง ศิลปิน รหัส และเนื้อร้อง
- ลูกศรขึ้น/ลงเลือกผลค้นหา Enter เพิ่มเข้าคิวและกลับจอเพลง Esc ยกเลิกค้นหา
- ป้องกัน Enter เลือกผลเก่าระหว่าง debounce หรือรอผลค้นหาใหม่
- รวมคิว การเล่น เนื้อร้อง คลังเพลง มิกเซอร์ และเครื่องมือไว้ในเมนูคลิกขวา
- เมนูระบบ 2 จอเปิด/ปิดจอร้อง เลือกจอปลายทาง และสลับเต็มจอได้
- F11 ใช้สลับหน้าหลักเต็มจอ; F10 เปิดคิว; F3 และ Ctrl+F เปิดค้นหา
- เก็บฐานข้อมูล คิว การตั้งค่า และการแก้เนื้อร้องจากรุ่นก่อน

## X-Stage Karaoke 0.2.1

- เปลี่ยนชื่อหน้าต่าง แถบโปรแกรม จอร้อง รีโมต และ EXE เป็น X-Stage Karaoke
- EXE ใหม่ชื่อ XStageKaraoke.exe และมีข้อมูล ProductName/FileDescription ตามชื่อใหม่
- แก้เนื้อร้อง NCN/EMK หายทั้งเพลงเมื่อมีข้อความท้ายไฟล์ Nick Karaoke ที่ไม่มี cursor
- ตัดเฉพาะข้อความเครดิตท้ายที่รู้จักและบรรทัดว่าง ไม่ตัดชื่อที่อยู่กลางเนื้อร้อง
- ถ้า cursor ขาดท้าย ให้ใช้เฉพาะอักขระที่มีข้อมูลเวลาจริง พร้อมคำเตือน
- ถ้าข้อมูลเวลาท้ายเสีย ไม่ทิ้งเนื้อร้องส่วนก่อนหน้า
- แสดงเนื้อร้องบรรทัดแรกล่วงหน้าเป็นสีปกติ แล้วป้ายสีเมื่อถึงเวลาร้อง
- เพิ่ม Data/last-playback.json สำหรับตรวจจำนวนบรรทัด profile และคำเตือนของเพลงล่าสุด
- นำเข้า playlist เดิมของ newKaraoke ได้ และเก็บฐานข้อมูล คิว การตั้งค่าในตำแหน่งเดิม
- ทดสอบภาพป้ายสีที่เปลี่ยนระหว่างเวลา cursor สองจุดกับเพลง NCN จากคลังจริง

ตำแหน่งติดตั้งยังเป็น D:\newKaraoke\Karaoke ตามที่ผู้ใช้กำหนด
เปิดด้วย X-Stage Karaoke.cmd; Start-Karaoke.cmd เดิมยังใช้เปิดรุ่นใหม่ได้
# 0.9.1 - 2026-11-07

- เพิ่มการตรวจพบงานลบเพลงที่ค้างจากการปิดผิดปกติหรือไฟดับ
- แสดงแผนและสถานะ journal ให้ผู้ใช้ตรวจและกู้คืนก่อนทำงานลบต่อ
- เพิ่ม regression tests สำหรับ crash recovery ของงานลบ

# 0.9.22 - 20261107

- เพิ่มเมนู `ซิงก์ X-Stage Karaoke Online…` ในหน้าต่างผู้เล่นหลักภายใต้ `ตั้งค่า` โดยตรง
- เมนูซิงก์ทำงานกับ Google Drive Desktop และใช้บัญชีเดียวกับเว็บเพลเยอร์
- ไม่มีเมนูสำรองข้อมูลแยกในหน้าผู้ใช้

# 0.9.23 - 20261107

- เพิ่ม `ซิงก์ X-Stage Karaoke Online…` ในเมนูคลิกขวา → เครื่องมือ
- รายการซิงก์ใช้คำสั่งเดียวกับเมนู `ตั้งค่า` และทำงานเบื้องหลัง

# 0.9.24 - 20261107

- ซิงก์ Google Drive อัตโนมัติ เปิดหน้าล็อกอิน ตรวจหาไดรฟ์ และสร้าง `X-Stage Karaoke` ให้เอง
- แสดงความคืบหน้าระหว่างซิงก์และเปิดเว็บเพลเยอร์เมื่อเสร็จ
- ปรับหน้าเว็บด้วยโลโก้ X-Stage พื้นหลังโทนเดียวกับโปรแกรม และ Google Login กลางหน้า

