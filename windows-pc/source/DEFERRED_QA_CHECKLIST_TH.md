# X-Stage Karaoke PC — รวมงานเขียนโค้ดก่อนทดสอบ (21 พ.ย. 2569)

เอกสารนี้แยก **เขียนโค้ดแล้ว** ออกจาก **ผ่านการทดสอบ** ตามคำขอให้เลื่อน QA ไปทำรวมภายหลัง ห้ามใช้เป็นหลักฐานออก Stable Release โดยลำพัง

## สิ่งที่มีโค้ดแล้ว (ยังไม่รับรอง)

- **P0:** มีหลักฐาน Windows CI / installer smoke จากรุ่นก่อนหน้าใน Roadmap; การเปลี่ยนแปลงหลังจากนั้นยังต้องผ่าน full regression อีกครั้ง
- **P1:** Multi-Out MIDI BASS 2/4/8/16 buses, drum-note routing และหน้าตั้งค่าเป็นโหมดเลือกเปิด; ASIO 1.4 driver discovery, native float32 stereo FIFO, MSVC DLL build, opt-in ASIO playback, ตรวจการหยุดของไดรเวอร์, BASS fallback ตอนเริ่มและระหว่างเล่น มีการ replay program/controller/note เท่าที่ทำได้โดยไม่หยุด clock ของเพลง
- **P2 (บางส่วน):** มิกเซอร์ช่อง MIDI เดิมใช้งานต่อได้; เพิ่ม Stereo PCM sample-peak safety limiter เฉพาะ ASIO โดยปิดเป็นค่าเริ่มต้น และดู peak/underrun/overrun ได้จากเมนูสถานะระบบเสียง; **ยังไม่ใช่ true-peak limiter, per-bus post-fader meter หรือ LUFS loudness matching**
- **P3 (มีโค้ดเดิม):** queue warmup, medley decks, crossfade, drum fill และฟังก์ชันต่อคิวมีอยู่แล้ว แต่ **ASIO ไม่ได้รองรับ seamless dual-deck handoff เทียบเท่า BASS stereo**
- **P4:** VST3 isolated plugin host, plugin recovery และ mapping ลง host ยัง **ไม่ได้ทำเสร็จ**; ห้ามกล่าวว่ารองรับ VST3 แบบสมบูรณ์
- **P5:** ตัวอ่านเพลง/เนื้อร้อง/ภาพพื้นหลังเดิมมีอยู่แล้ว แต่การรับรองฟอร์แมตและฟีเจอร์ configurable lyric 2–4 lines / chromakey ไม่ครบ
- **P6:** ไม่มีหลักฐาน 2-hour hardware soak, multi-interface ASIO sync, Authenticode signature หรือ stable rollout ผ่านเกณฑ์

## ข้อจำกัดและความปลอดภัย

1. ASIO ใช้งานเมื่อเปิดในเมนู **ตั้งค่า → ASIO Output · ทดลองใช้** เท่านั้น ค่าเริ่มต้นยังเป็น BASS; หาก Multi-Out เปิดอยู่จะใช้ Multi-Out ก่อน
2. ต้องมี `bassasio.dll` x64 API **1.4** ที่มีสิทธิ์ใช้งานจาก Un4seen; ตัวโปรแกรมจะไม่ปลอม/ข้ามการตรวจรุ่น DLL. BASSASIO ให้ใช้ฟรีสำหรับการใช้งานที่ไม่ใช่เชิงพาณิชย์ และมีเงื่อนไขใบอนุญาตสำหรับการใช้งานเชิงพาณิชย์: https://www.un4seen.com/bassasio.html
3. การสลับ ASIO → BASS ระหว่างเล่นเป็น best-effort: ถ้าปิดไดรเวอร์เก่าไม่ได้ จะหยุดอย่างปลอดภัยแทนการเสี่ยงปล่อย callback ที่ยังใช้งานอยู่; โน้ตที่กำลังดังอาจเริ่ม attack ใหม่หลังสลับ
4. Peak Limiter ลด **sample peak** ใน ASIO PCM เท่านั้น ไม่รับประกัน true-peak/LUFS หรือคุณภาพเสียงเท่ากันทุกอุปกรณ์; ค่าเริ่มต้นปิด
5. ห้ามแก้ไข/ลบเพลง ฐานข้อมูล และข้อมูลผู้ใช้โดยอัตโนมัติจากงาน QA; ห้ามแก้ Stable release metadata เพียงเพื่อให้ CI ผ่าน

## แผนตรวจครั้งเดียวหลังพัฒนาโค้ดครบ (ยังไม่ดำเนินการ)

1. ตรวจ full Windows GitHub Actions regression และ native Win32 GUI; 0 failures, 0 errors, วิเคราะห์ skips และตรวจว่าตัวใหม่บรรจุ `native/x64/xstage_asio_pcm.dll`
2. ทดสอบ native callback ABI, buffer underrun/overrun, output channel mapping, SetDevice/IsStarted, ASIO stop & cleanup, fallback MIDI state, optional limiter และการเก็บสถานะ
3. ทดสอบ SoundFont, NCN/MIDI/XMIDI ที่รองรับ, เสียง MP3/วิดีโอ, คิวเพลง, medley/crossfade, ความตรงเนื้อร้อง และจอแยกกับตัวอย่างที่มีสิทธิ์ใช้งาน
4. ทดสอบ ASIO ไดรเวอร์จริงหลายรุ่น / sample rates 44.1k, 48k, 96k, ถอดอุปกรณ์ขณะเล่น, Multi-Out 2/4/8/16 buses และระดับเสียงจริง
5. รัน live soak อย่างน้อย 2 ชั่วโมง เก็บค่า CPU/RAM, PCM underrun/overrun, latency, crash logs, queue gaps และตรวจการกลับมาทำงานหลังปิดเปิดโปรแกรม
6. ทดสอบติดตั้ง/ถอนบน Windows, โฟลเดอร์ชื่อไทย, user Data preservation, SHA-256, Sigstore provenance และใบรับรอง Authenticode ตามนโยบายเผยแพร่ แล้วจึงตัดสินใจ Stable Release

**สถานะรวม:** `CODE-IN-PROGRESS / PENDING-QA / DEFERRED-HARDWARE` — การข้ามการทดสอบไม่ทำให้รายการที่ยังไม่เขียนโค้ดกลายเป็นเสร็จสมบูรณ์
