## X-Stage Karaoke Online v1.0.103 (Build 1103) — NCN timing on Web and Android TV

- The Web importer now reads .LYR using the original CP874 bytes, consumes one invisible CUR cue before each nonblank lyric line, and converts each CUR position from NCN24 units using actual MIDI tempo changes rather than dividing by 24 as seconds. Thai combining marks remain synchronized with the preceding displayed glyph.
- Accepts valid trailing unused CUR values, including legacy 65535 sentinels and a final FF byte, without altering MID/LYR/CUR. Backward positions are displayed at the last known valid time; missing visible-character timing is never fabricated, and incomplete timed NCN songs are not published as complete catalog entries.
- Web and Android TV use the same hosted player logic. After updating, import a source NCN set again to regenerate the stored Lyrics JSON of previously imported songs. Existing Google Drive files remain private, with MD5 de-duplication and conflict checks retained.
- Tested with synthesized tempo-change / Thai CP874 / CUR sentinel fixtures and offline analysis of the user's supplied 00001 MID/LYR/CUR trio. Physical Android TV playback still requires verification on the target device.

## Video Karaoke — original media and song details

- Source formats: AVI, MPG/MPEG, DAT (VCD MPEG-PS), VOB, MKV, MOV, WMV and FLV. The browser importer verifies media headers and **retains the exact original bytes** in the owner's private `XStageWeb/VIDEO/ORIGINAL/<FORMAT>/Songs/<bucket>/` folder. It also publishes a codec-compatible H.264/AAC MP4 as `song.video` (and `song.audio` for a video-only item) when conversion is needed. `song.originalVideo` points at the original file, and `sourceVideoMd5` records its hash.
- Original file playback depends on the browser and codecs. When `HTMLVideoElement.canPlayType()` reports support, the stage offers the original picture; it automatically switches back to the compatible MP4 if the original cannot decode. For formats a browser cannot decode, preserving the source **does not claim direct playback**: the compatible MP4 is played. Karaoke sound remains on the synchronized primary audio clock.
- Each selected video requires the owner to review its **song code, song title and artist** before upload. Optional metadata: album, composer, genre, language and year. Use the importer video editor to select each video and save. Unreviewed videos stay pending without being silently published as Karaoke songs.
- The video editor asks whether subtitles/lyrics are already burned into the picture. For videos **without** embedded subtitles, use a same-named timed LRC/JSON file or write a real timed LRC manually. The preview supports playback in browser-compatible formats and insertion of the current timestamp into LRC; entering the lyric text is still required. It **does not auto-transcribe** video audio or invent timing.
- Browser-only conversion is local and currently capped at 192 MiB per input, requiring an automatic FFmpeg.wasm download. A bundled Song Studio PC engine is suitable for larger/unsupported codecs. Google OAuth tokens and file bytes are not sent to the converter CDN, and original files are never overwritten. This change does not promise native AVI/WMV/FLV decoders in every browser.
- Web and Android TV use the same private catalog. Video import metadata is kept in IndexedDB per signed-in account for paused/reselected folder jobs; it is not stored in localStorage with Google tokens.

## v1.0.101 — Video Karaoke VDO on WEB / Android player

- MP4/WebM with real LRC/JSON overlay or embedded lyrics (no separate timed file) can be imported as a private catalog song. For embedded lyrics the system publishes `lyricsMode: "embedded-video"` and `lines: []`; it never fabricates lyric timestamps.
- AVI, MPG, MPEG, DAT (MPEG-PS VCD), VOB, MKV, MOV, WMV and FLV are checked by file signature and converted **locally** to H.264/AAC MP4 via an isolated FFmpeg.wasm Web Worker before upload. The original file is not uploaded or overwritten. The worker has no access to the Google OAuth token in the page.
- Browser conversion is optional/on demand, depends on download of pinned FFmpeg.wasm assets and supports up to **192 MiB per source** as a memory safety limit. For larger files or unsupported codecs use the FFmpeg-included Song Studio PC Ready. Web/Android HTML5 decoders cannot be guaranteed for every source codec/device.
- While a video is playing, the stage hides its background banner, keeps audio as the master clock, synchronizes muted picture playback, and lets users show/hide separately timed lyrics. Pause, stop and cancel release the video media and in-flight Drive download.
- This revision preserves existing Google Drive private library / MD5 deduplication, audio/MIDI/NCN/SoundFont imports, and no public media hosting. Tests: `npm test`, browser-import Chromium E2E, and Android TV regression.


## v1.0.50 — TrueID TV / TV Bro Google Login helper

- เพิ่มการตรวจ Pop-up ก่อนเริ่ม Google Login บนอุปกรณ์ Android TV ที่ควบคุมด้วยรีโมต
- หาก TV Bro บล็อกหน้าต่าง Google ระบบจะแสดงคำแนะนำบนจอทีวีทันที พร้อมปุ่ม “ตรวจอีกครั้งและเข้าสู่ระบบ”
- แนะนำให้อนุญาต Pop-up เฉพาะ host ของ X-Stage แทนการปิดตัวบล็อกทั้งเบราว์เซอร์
- หาก Google ส่งข้อผิดพลาดเกี่ยวกับ popup/window/blocked ระบบจะแสดงหน้าช่วยเหลือ TV Bro อัตโนมัติ
- ไม่ลดความปลอดภัยของ Google OAuth และไม่พยายามข้ามตัวบล็อก Pop-up ของเบราว์เซอร์

# X-Stage Karaoke Online (v0.9.44)

หน้าเว็บ GitHub Pages นี้ไม่มีเพลงหรือฐานข้อมูลส่วนตัวอยู่ใน repository

1. ผู้ใช้ใช้ X-Stage Karaoke Windows v0.9.44 เพื่อสร้าง M4A/JSON และซิงก์ไปยังโฟลเดอร์ **XStageWeb** ใน Google Drive ของตน
2. Windows อัปโหลดไฟล์เสียง/เนื้อร้องเป็นรายเพลง จากนั้นเผยแพร่ catalogs/database-*.json และอัปเดต current.json เป็นขั้นตอนสุดท้าย
3. เว็บใช้ Google Identity Services และ scope drive.file เพื่ออ่านเฉพาะคลังที่บัญชีเข้าถึงได้ ไม่ใช้ web-manifest.json หรือ Backup SQLite เดิม
4. Web Client ID เป็นข้อมูลสาธารณะ แต่ห้ามอัปโหลด Desktop Client Secret, tokens, เพลง, lyrics หรือ catalog ของผู้ใช้
5. การใช้ drive.file ข้าม Desktop/Web OAuth Client ต้องอยู่ภายใต้ Google Cloud Project เดียวกัน และทดสอบกับบัญชีจริง
6. ไฟล์บน Drive ไม่เปิดสาธารณะ; ผู้ใช้แต่ละคนใช้ Google Drive ของตนเอง

การส่ง M4A จาก Drive ไป Browser เป็นการดาวน์โหลด Blob พร้อม OAuth Token เหมาะกับการใช้งานส่วนตัวแบบจำกัด ไม่ใช่ CDN สาธารณะ


## X-Stage PC-style web search (v0.9.48)

ค้นหาเพลงบนเวทีเหมือนรุ่น Windows, แสดงผลแบบเรียลไทม์, เรียกผลด้วย F3/Ctrl+F และซ่อนหลังเลือกเพลง ระบบรองรับคิว, การเล่น, ประวัติ, เพลงโปรดเฉพาะแท็บ, สุ่มเพลง, ช่วงวน A–B, Web Audio EQ, สี/ขนาดเนื้อร้องและพื้นหลัง, ส่งออก/นำเข้าคิว และจอร้องแยก

การควบคุม BASSMIDI, Windows MIDI ports, ASIO และแก้ไข SQLite ต้นทางยังคงใช้บน Windows เท่านั้น เว็บ v1.0.96 เพิ่มตัวเรนเดอร์ MIDI/KAR/NCN และตัวอ่าน SoundFont SF2/SF3 ภายในเบราว์เซอร์ (ไม่ใช่ BASSMIDI/FluidSynth และคุณภาพเสียงอาจไม่เท่ากัน) เว็บไซต์ไม่เก็บไฟล์เพลงส่วนตัวหรือ Google OAuth Token ใน GitHub

เครื่องมือเพิ่มเติม: แก้ชื่อผู้ร้อง/ความเร็วเฉพาะเพลงในคิว, นำเข้า/แก้ไขเนื้อร้อง LRC ชั่วคราว, บันทึกเสียงไมโครโฟนเมื่ออนุญาต และเลือกเสียงเอฟเฟกต์จากไฟล์ของผู้ใช้ในเบราว์เซอร์ ฟังก์ชันเหล่านี้ไม่เขียนทับ Catalog หรือไฟล์เพลงบน Drive


## On-screen keyboard + QR mobile remote (web v0.9.55)

- ปุ่ม "⌨ แป้นพิมพ์" อยู่บนเวที รองรับจอปกติและโหมดเต็มหน้าจอ ใช้พิมพ์ค้นหาเพลงภาษาไทย/อังกฤษ ตัวเลข เว้นวรรค ลบ ล้าง และ Enter; ปุ่ม "ซ่อนแป้นพิมพ์" ปิดได้ทันที
- ปุ่ม "▦ รีโมท QR" บนเวทีสร้าง QR ใหม่สำหรับเปิด /remote.html#p=…&k=… บนมือถือ
- ใช้ PeerJS Cloud สำหรับ signaling ของ WebRTC DataChannel; บางเครือข่าย/ไฟร์วอลล์อาจต้องใช้ TURN หรือเซิร์ฟเวอร์ PeerJS ของตนเอง
- มือถือต้องได้รับอนุญาตจากจอหลักก่อนจึงจะค้นหาเพลง จัดคิว เล่น/หยุด/ข้ามเพลงและปรับเสียงได้
- โค้ดรีโมทไม่ส่ง Google OAuth Token, ไฟล์ M4A, เนื้อร้อง หรือ URL ของ Google Drive ไปยังมือถือ; QR ใช้รหัสสุ่มเฉพาะเซสชันและต้องจับคู่ใหม่หลังปิดหน้า
- ไลบรารี PeerJS และ QRCode โหลดจาก cdnjs แบบระบุเวอร์ชัน หาก CDN ถูกบล็อก จะไม่สามารถเปิดรีโมทหรือสร้าง QR ได้; ก่อนใช้งาน production ในองค์กร แนะนำ vendor library และใช้ SRI หรือโฮสต์เอง

## Compact-screen stage layout (web v0.9.56)

- หน้าจอกว้างไม่เกิน 820px หรืออุปกรณ์สัมผัสในแนวนอนที่หน้าจอเตี้ย จะแสดงโลโก้/ชื่อแอปซ้อนบนเวที เหนือแถบค้นหา พร้อมปุ่มเมนู
- ช่องค้นหายังคงอยู่บนเวที โดยแยกพื้นที่นาฬิกาที่มุมขวา เพื่อป้องกันการทับซ้อน
- ซ่อนแถบส่วนหัวเดิม แถบล่าง คิวเพลง และเครื่องมือรองในมุมมองเล็ก แล้วเรียกใช้จากเมนู (คิวเพลง, เครื่องมือ, แป้นพิมพ์, QR รีโมท, เต็มจอ, Google)
- คงปุ่มควบคุมเพลงหลักและแถบเวลาการเล่นไว้สำหรับการใช้งานทันที
- ในโหมดเต็มจอบนจอเล็ก เมนู โลโก้ และช่องค้นหายังคงอยู่บนเวที; การเปิดคิวเพลงหรือเครื่องมือจะออกจากเต็มจอก่อนเพื่อเข้าถึงแผงเดิม

## Safari Google OAuth delayed-callback hardening (v1.0.100, Build 1100)

- The Web Google Identity Services token client uses popup callback UX. Safari can regain focus before Google delivers a token; focus/pageshow is no longer treated as an authorization failure and never invalidates an in-flight request.
- Keep token callback alive through userinfo and private Drive verification; prevent a parallel pending-token recovery and ignore duplicate popup errors after receiving a token.
- Defer automatic web update reload while the Google popup is awaiting a callback or Drive is verifying. This also prevents incidental 15-second update checks from destroying an OAuth result.
- After 12 seconds without a Google response, re-enable the login controls for **explicit user retry** without discarding a valid delayed response. Only Google's actual callback/error, a user-requested new login, or the 90-second request timeout can terminate that request.
- Use the supported GIS token popup model for private Google Drive; no unsupported static-page OAuth code redirect, refresh-token persistence, or PWA functionality is added.
- CI simulates Safari focus at 2.5 seconds, late token receipt, duplicate popup close, slow Drive verification, manual retry, timeout, and update deferral.

## Platform hardening and separate release channels (v1.0.99)

- Android TV: preserve native D-Pad/IME cursor and text selection while editing, request Android media Audio Focus before playback, and handle transient/permanent loss distinctly. Restore playback on focus gain only when the user has not paused/stopped.
- Native Google session inspection synchronizes with concurrent login, restore, and logout.
- Windows PC launcher resolves EXE relative to the script or known installation locations and accepts explicit `-AppPath`. The updater reads matching local release metadata to compare builds but never advertises an unverified Windows installer.
- Song Studio Ready v0.3.25 Build 325 is a verified portable ZIP with a separate Source Preview channel. Python 3.13.10 embedded downloads are pinned to the SHA-256 published by Python.org.
- Safari on iPhone/iPad: explain folder picking on iOS 18.4+ and the limitations of older file pickers. No PWA is reintroduced.

## X-Stage Web + Android APK + Windows EXE (v1.0.98)

- รุ่นเว็บเปิดผ่านเบราว์เซอร์ปกติ โดยไม่มี PWA Manifest, Service Worker หรือปุ่มติดตั้งเว็บแอป
- หน้าเว็บใหม่ยกเลิก Service Worker ขอบเขต X-Stage เดิมและล้างเฉพาะแคช `xstage-shell-*` โดยไม่ลบ Google Login หรือไฟล์เพลงส่วนตัว
- Android TV/แท็บเล็ตใช้ APK; หน้าเว็บบน Android ยังคงเสนอไฟล์ APK จาก metadata ล่าสุด พร้อมตัวเลือกใช้งานเว็บต่อโดยไม่ต้องติดตั้ง
- Windows PC ใช้ EXE/Installer แยกช่องทาง; ไอคอนและ favicon ของเว็บยังคงใช้ตามปกติ


## Stage-first UI redesign (v0.9.60)

- หน้าเว็บใช้เวทีเต็มพื้นที่หน้าจอ และอ้างอิงภาพ UX/UI ที่ผู้ใช้ส่งมา โดยแยก stylesheet ใหม่ `xstage-ux.css` เพื่อไม่กระทบระบบเพลงและ Google Drive เดิม
- แถบด้านบน: ☰ เมนูด้านซ้าย, ช่องค้นหาเรียลไทม์, แป้นพิมพ์, QR รีโมท, Fullscreen, นาฬิกา
- เมนูซ้าย: หน้าแรก, คิวเพลง, เครื่องมือและตั้งค่า, แป้นพิมพ์, รีโมทมือถือ, เกี่ยวกับ X-Stage, Google Login/Logout; เปิดอัตโนมัติบนเดสก์ท็อปขนาดใหญ่และยุบได้
- ค้นหา: แสดงรายการตรงคำค้นทันที กด ↑/↓ เพื่อเลือก Enter เล่นหรือเข้าคิว และเน้นคำที่ตรงกัน
- รีโมท QR: แผงลอยด้านขวาใต้แถบคำสั่ง กดซ้ำ/กด ✕ จึงซ่อน ใช้กลไกอนุญาตการจับคู่เดิมและไม่ส่ง OAuth token
- เวทีกลาง: ฉากหลัง SVG นีออนที่สร้างขึ้นใหม่ใน `assets/xstage-neon-stage.svg` และป้าย X-STAGE / KARAOKE / Online / ไมโครโฟน ด้วย HTML/CSS
- ด้านล่าง: ปกเพลง, เพลงปัจจุบัน, เวลาการเล่น/แถบเลื่อน, สุ่มเพลง, ก่อนหน้า/เล่น/ถัดไป/หยุด/วนเพลง, ระดับเสียง และปุ่มคิวเพลง
- แผงคิวและเครื่องมือเป็น overlay ภายในเวที จึงเปิดได้ในโหมด Fullscreen; ค่าความเร็วและวนเพลงเดิมย้ายเข้าแผงเครื่องมือ
- พื้นที่แสดงเนื้อร้องคำนึงถึงแถบควบคุมและแป้นพิมพ์ เพื่อไม่ให้เนื้อร้องบรรทัดล่างถูกบังเมื่อแสดงบนจอเล็ก
- Responsive รองรับเดสก์ท็อป แท็บเล็ต และมือถือ โดยซ่อนปุ่มรองในเมนูเมื่อพื้นที่จำกัด; ไม่แก้ไฟล์เพลง ฐานข้อมูลส่วนตัว หรือโปรโตคอล Google OAuth

## v0.9.61 — ค้นหาเมื่อมีคำค้น, กู้เมนูเครื่องมือ และคืนเซสชันหลังรีเฟรช

- เมื่อช่องค้นหาเป็นค่าว่าง `state.shown=[]` และย่อรายการผลค้นหาทันที (ไม่แสดงเพลงทั้งคลัง) เริ่มแสดงผลเรียลไทม์เมื่อพิมพ์จริงเท่านั้น
- เพิ่มปุ่ม “จอร้องแยก” ในแถบบนและเมนู; เรียกใช้ `pc-stage-pop` และ `stage.html` เดิมโดยตรง
- เพิ่มเมนูย่อยสำหรับเพลงโปรด สุ่มเพลง ประวัติ EQ ปรับเนื้อร้อง/พื้นหลัง A–B Loop นำเข้า/ส่งออกคิว LRC ไมโครโฟน และเครื่องมือขั้นสูง โดยเชื่อมปุ่มเดิมใน `pc-extensions.js`
- ยกข้อความ X-STAGE / KARAOKE / Online บนเวทีขึ้น ปรับขนาดเมื่อเล่นเพลง และคำนวณตำแหน่งเนื้อร้องให้ไม่ทับ QR โดยเลื่อนแนวตั้งหรือจำกัดความกว้างทางซ้ายของแผง QR ตามพื้นที่จริง
- เมื่อรีเฟรช **ในแท็บเดิม** ให้ใช้ access token แบบอายุสั้นที่ยังไม่หมดอายุจาก `sessionStorage` เพื่อโหลดคลังส่วนตัวกลับมาได้โดยไม่เปิดหน้าลงชื่อเข้าใช้อีก Google Token Model ไม่รองรับการต่ออายุ token แบบไร้การกระทำจากผู้ใช้: เมื่อ token หมดอายุหรือถูกเพิกถอนต้องกด Google Login ใหม่
- ข้อมูลเพลงและ Google refresh token **ไม่** ถูกจัดเก็บถาวร; access token ใน `sessionStorage` ถูกลบเมื่อ Logout/หมดอายุหรือปิดแท็บ และมีความเสี่ยงจากสคริปต์ที่รันบน origin เดียวกัน จึงไม่ใช่ระบบล็อกอินถาวรระยะยาว

## v0.9.62 — เมนูเวทีเรียบง่าย + รีโมท QR สำหรับ **ขอเพลง**

- ย้าย **รีโมท QR, จอร้องแยก** ออกจากแถบด้านบนไปไว้ในเมนู ☰ (ระบบติดตั้ง PWA เดิมยกเลิกใน v1.0.98)
- แก้เมนูข้อความยาว: ย่อบรรทัดในขอบเมนูทุกขนาดจอ รองรับแนวตั้ง/แนวนอนและ Fullscreen
- มือถือเข้า `remote.html` จาก QR โดยไม่ต้องลงชื่อเข้าใช้ Google, ไม่เห็นไฟล์เพลงหรือ Drive Token
- หน้ารีโมทมือถือเหลือเพียง **ชื่อผู้ขอ / หมายเหตุ / ค้นหาเพลง / ขอเพลง**; ไม่มีปุ่มเล่น หยุด ข้ามหรือปรับเสียง
- จอหลักรับคำขอในเมนู **📥 คำขอเพลง** โดยเจ้าของเวทีเลือกอนุมัติ **เพิ่มเข้าคิว** หรือปฏิเสธ ไม่เปลี่ยนคิวเมื่อได้รับคำขอโดยอัตโนมัติ
- QR มีรหัสสุ่มต่อเซสชัน และใช้ WebRTC/PeerJS Cloud สำหรับจับคู่; จำกัดจำนวนการเชื่อมต่อและความถี่ในการส่งคำขอ ผู้ถือ QR ขอเพลงได้แต่ควบคุมเครื่องเล่นไม่ได้
- การค้นหาและแสดงผลเพลงจากแค็ตตาล็อกบนจอหลักยังต้องให้ **เจ้าของเวที** เข้าสู่ระบบ Google Drive ส่วนตัวก่อน; ข้อกำหนดนี้ไม่ใช่การล็อกอินสำหรับมือถือ

**Windows Source:** มี Hotfix รุ่น v0.9.48 เพิ่ม Google Login ตั้งแต่หน้าต่างซิงค์ ใช้ Desktop OAuth JSON เดิมและบันทึก Refresh Token ด้วย Windows DPAPI รายละเอียดในไฟล์ `GOOGLE_DRIVE_LOGIN_0950_TH.md` ที่มาพร้อมซอร์ส Windows (ไม่ได้รวม OAuth Client JSON จริงหรือโทเค็นใน GitHub)

## v0.9.63 — QR remote จับคู่ครั้งแรก / คิว / เสียง / เมดเลย์ M4A

- มือถือสแกน QR โดย **ไม่ต้องเข้าสู่ระบบ Google** จอหลักต้องกด **อนุญาตมือถือ** ก่อนเปิดสิทธิ์ในการเชื่อมต่อนั้นครั้งเดียว จากนั้นไม่ต้องอนุมัติทีละเพลง; เมื่อเชื่อมต่อใหม่อาจต้องอนุมัติอีกครั้ง
- หลังเชื่อมต่อมีสามแท็บ **ขอเพลง / คิวเพลง / ควบคุม** หน้าคิวอัปเดตเพลงปัจจุบัน ชื่อผู้ขอ และรายการเพลงที่กำลังรอ
- เมื่อผู้ขอเลือกเพลง ระบบเพิ่มในคิวเดิมทันที หากคิวเดิมว่าง **และไม่มีการเล่นเพลงอยู่** จะสั่งเริ่มเพลงนั้นทันที ถ้ามีเพลงกำลังเล่นจะเข้าคิวไม่แทรก
- คำสั่งควบคุมหลังอนุมัติ: เล่น/พัก, หยุด, เพลงถัดไป, เพิ่ม/ลดระดับเสียงทีละ 5%, ปิด/เปิดเสียง และย่อ/ขยาย **ภาพเวที/เนื้อร้อง** บนจอหลัก 70–135%
- ปุ่ม **เต็มจอมือถือ** เปิด/ปิด Fullscreen **บนโทรศัพท์ที่ถือรีโมท** เท่านั้น การสั่งเปลี่ยนหน้าต่าง/Fullscreen ของจอหลักโดย WebRTC ไม่ได้รับอนุญาตจากเบราว์เซอร์หากไม่มีการแตะกดบนจอหลัก
- ปุ่ม **เมดเลย์** เปิดโหมดต่อเพลง M4A: เตรียมไฟล์เสียง/เนื้อร้องเพลงถัดไปโดยใช้ Google Drive ของจอหลัก ก่อนช่วงท้ายเพลง และตัดเข้าสู่เพลงถัดไปก่อนจบเมื่อโหลดทัน พร้อมลดเสียงช่วงท้าย; หากดาวน์โหลดล่วงหน้าไม่ทันยังใช้การเล่นเพลงถัดไปตามปกติ ไม่มีระบบจับ BPM หรือ MIDI Beat Matching
- เจ้าของเวทีสลับเมดเลย์ได้จากเมนู ☰ เช่นกัน และจะสะท้อนสถานะบนมือถือ
- ข้อมูลล็อกอิน Google, Drive file ID/URL และไฟล์เสียง/เนื้อร้องยังอยู่เฉพาะเบราว์เซอร์จอหลัก รีโมทได้รับเพียงเมทาดาทาเพลง/คิวที่จำเป็น ใช้ QR secret ต่อเซสชันและ whitelist คำสั่งเท่านั้น
- มีการจำกัดจำนวนเชื่อมต่อ/ความถี่คำขอ และไม่บันทึกสิทธิ์ของโทรศัพท์ข้ามเซสชันไว้ถาวร
- **ข้อจำกัดเบราว์เซอร์**: การเล่นเสียงครั้งแรกบนจอหลักอาจต้องให้ผู้ใช้แตะปุ่มเล่นบนจอหลักก่อน เพื่อปลดข้อจำกัด autoplay

## v0.9.64 — ช่องค้นหาโปร่งใส, รีโมท Fullscreen จอหลัก, เมดเลย์สุ่มเพลง

- ช่องค้นหาด้านบนเวทีเป็นสีเข้มโปร่งใสเพื่อให้เห็นฉากหลัง และเมื่อแสดงผลค้นหาจะเพิ่มระดับความเข้มสำหรับอ่านชื่อเพลงได้ชัด
- ปุ่มรีโมทมือถือ **เต็มจอหลัก / ย่อจอหลัก** ควบคุมสถานะ Fullscreen ของจอ X-Stage ที่กำลังเล่น ไม่ใช่ปรับขนาดภาพหรือ Fullscreen บนโทรศัพท์
- เบราว์เซอร์บังคับให้การเข้า Fullscreen เกิดจากการกระทำบนจอหลัก: เมื่อมือถือขอเปิด จอหลักจะแสดงปุ่มให้กดยืนยันหนึ่งครั้ง ไม่สามารถข้ามเงื่อนไขนี้ผ่าน WebRTC ได้ ส่วนการออกจาก Fullscreen สามารถขอจากมือถือได้
- **เมดเลย์** หมายถึง **สุ่มเพลง M4A เล่นต่อเนื่อง** จากคลังส่วนตัว โดยเพลงที่ผู้ใช้ขอในคิวจะได้เล่นก่อน เมื่อคิวหมดจึงสุ่มเพลงต่ออัตโนมัติ
- เลี่ยงสุ่มเพลงปัจจุบันหรือเพลงที่เพิ่งเล่นเมื่อมีเพลงอื่นให้เลือก เพลงที่กำลังเล่นจะเล่นจนจบ ไม่ตัดก่อนเวลา
- ก่อนเพลงจบประมาณ 25 วินาที โปรแกรมจะพยายามเตรียมเพลงถัดไปจาก Drive ในหน่วยความจำเท่านั้น หากโหลดไม่ทันจะโหลดตามปกติเมื่อจบเพลง ไม่มีการจับ BPM/MIDI หรือการมิกซ์จังหวะ
- เปิด/ปิดเมดเลย์จากทั้งเมนูจอหลักและแท็บควบคุมของรีโมทมือถือ (ไม่มีการส่ง Google OAuth Token หรือไฟล์เพลงไปให้มือถือ)

## v0.9.65 — Streaming catalog while Windows sync continues

- Windows X-Stage Pipeline R7 publishes a **first verified catalog batch** during conversion/upload, before the full job finishes.
- New catalog pointer fields: `catalogFileId` (immutable base snapshot) and optional `deltaFileIds` (verified incremental changes). The base snapshot remains compatible with previous schemaVersion 1.
- The browser loads base + deltas in order, checking `songCount` before using the combined catalog. Incomplete/invalid generations leave the last known-good playable songs unchanged.
- While signed in, the web player checks `current.json` **every 45 seconds**. When the generation changes, it updates the searchable song catalog without interrupting audio playback or clearing the existing queue.
- All media, lyrics, catalog and delta files are kept private in the owner's Google Drive. This feature does not expose them on GitHub Pages, and it never shares Google tokens with mobile remotes.
- Each checkpoint switches `current.json` only **after M4A and Lyrics JSON are both uploaded and verified**. Interrupted Windows sync may be resumed later. The final Windows pass compacts deltas into one complete snapshot.

## X-Stage Karaoke Online v1.0.96 — browser media/MIDI/SoundFont

* **ติดตั้งเพิ่มเติม:** ไม่ต้องดาวน์โหลดโปรแกรม, runtime, executable หรือไลบรารีจาก CDN เพื่อเล่น MIDI; โค้ด `browser-midi.js` ส่งจาก origin เดียวกับ X-Stage บน GitHub Pages และใช้ Web Audio API ของเบราว์เซอร์
* **คลังส่วนตัว:** ไฟล์เพลง/เสียง/เนื้อร้อง/SoundFont เก็บใน Google Drive ของเจ้าของบัญชี ค้นหาโฟลเดอร์ `XStageWeb/SOUNDFONT/SF2` และ `SF3` เพื่อแสดงตัวเลือก SoundFont ไม่เก็บ token หรือเสียงลง GitHub
* **MIDI/KAR:** นำเข้าไฟล์ Standard MIDI `.mid`/`.midi`, Karaoke MIDI `.kar` ได้ โดยตรวจ track และสร้าง Lyrics JSON จากข้อความ KAR หรือระบุว่าเป็นเพลงบรรเลง; เล่นผ่าน Web Audio OfflineAudioContext เพื่อให้คิว/เล่นต่อ/เลื่อนเวลาใช้ตัวควบคุมเสียงเดิมได้
* **NCN:** รับชุดชื่อรหัสเดียวกัน `.mid + .lyr + .cur` (แยก Song/Lyrics/Cursor ได้) และเก็บต้นฉบับทั้งสามใน `MIDI/NCN` พร้อมสร้าง Lyrics JSON สำหรับเวที ต้องมีครบสามไฟล์จึงนำเข้าเป็น NCN
* **SoundFont:** รองรับ RIFF SF2 และ SF3 ที่มีข้อมูลครบ เลือกจากเมนูเวทีภายหลัง Google Login; SF2 สังเคราะห์เสียงด้วย sample bank, SF3 ใช้ native Ogg decoder ของเบราว์เซอร์และอาจใช้ไม่ได้ในบางรุ่น/อุปกรณ์ ถ้าไม่ได้เลือก SoundFont ใช้ oscillator พื้นฐานที่ฝังมากับเว็บ; ไม่แอบใช้เสียงพื้นฐานแทน SF3 ที่ถอดรหัสไม่สำเร็จ
* **เสียงและวิดีโออื่น:** นำเข้า MP3/M4A/WAV/AAC/FLAC/OGG/OGA รวมถึง MP4/WebM พร้อม Lyrics JSON/LRC ที่มีเวลาได้ โดยตรวจ magic bytes ก่อนอัปโหลด แต่การถอดรหัสจริงยังขึ้นกับ codec และ HTMLMediaElement ของเบราว์เซอร์ ไม่มีคำรับประกันว่าไฟล์ทุก codec เล่นได้
* **ขีดจำกัด:** MIDI 12 MiB/ความยาวไม่เกิน 15 นาที; SF2/SF3 ไม่เกิน 256 MiB; เรนเดอร์ทั้งเพลงเป็น WAV ภายในหน่วยความจำก่อนเล่น (อาจช้าบนมือถือและไฟล์ใหญ่) ไม่รองรับ EMK/AVI/WMV/VOB/FLV/MKV ที่ต้องถอดรหัสเฉพาะ และไม่ใช่เครื่องเล่น MIDI ระดับ BASSMIDI/FluidSynth ที่จำลองทุก controller/effect ได้ครบ
* **ความปลอดภัย:** MD5 ตรวจไฟล์เมื่อส่งขึ้น Drive, คู่รหัสไม่ตรงถูกข้าม, ชุดไม่สมบูรณ์ไม่เผยแพร่เข้า DB, เขียน `current.json` หลังอัปโหลดและตรวจ catalog สำเร็จเท่านั้น; token Google มีอายุตาม OAuth เดิม
* **การตรวจ:** `npm test` เพิ่มสคริปต์ `scripts/browser-midi-test.mjs` สำหรับ parser, NCN cursor และ WAV contract; ต้องทดสอบเล่น/อัปโหลดจริงบน Chrome, Safari iOS, Android TV และ SoundFont ตัวอย่างก่อนประกาศว่าครบทุกอุปกรณ์
