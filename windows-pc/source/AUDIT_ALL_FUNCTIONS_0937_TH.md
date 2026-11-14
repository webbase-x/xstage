# ตรวจสอบระบบ X-Stage Karaoke v0.9.36 และข้อเสนอหลังเพิ่มเมดเลย์เพลงฮิตใน v0.9.37

ฐานตรวจ: ซอร์สล่าสุด v0.9.36 และผล regression ทุกรายการ; งานเพิ่มฟังก์ชันใหม่อยู่ใน v0.9.37
ขอบเขตซอร์ส: โฟลเดอร์ `karaoke/` 129 โมดูล ประมาณ 21,900 บรรทัด, `tests/` 99 ไฟล์ทดสอบ; ตรวจการเรียกใช้งานและทดสอบรวม 911 รายการ
ข้อจำกัด: การรันทุก unit test ไม่เท่ากับการทดสอบทุกเมนูจริงบน Windows พร้อมอุปกรณ์ภายนอก ดังนั้นแต่ละหัวข้อระบุส่วนที่ยังไม่รับรอง

## ผลประเมินตามกลุ่มฟังก์ชัน

| กลุ่มระบบ | สิ่งที่ตรวจ | ผลและการปรับปรุงที่ควรทำต่อ |
|---|---|---|
| เปิดโปรแกรม / ตั้งค่า / UI | main, performer, ui, classic, context_menu, dialog_layout, keyboard controls และหน้าต่าง Tk | ผ่านการตรวจไวยากรณ์และ GUI unit tests ส่วนใหญ่ใน Xvfb; ต้องตรวจการโฟกัสช่องค้นหาทันที ขนาด DPI 125–200% และปิดหน้าต่างขณะ worker ยังทำงานบน Windows |
| ค้นหาเพลงและฐานคลัง | library, catalog_window, search, FTS, SQLite | ใช้ฐานเพลงเดิมได้และมีชุดทดสอบค้นหา; ควรวัดแผนคิวรี/หน้าแสดงผลจริงที่ 100k–500k เพลง และลดการนับผลซ้ำในหน้าจอ |
| สร้างรายการเพลง | fast_catalog, incremental, lister, index_plan, jobs, job_dialog | มีแคชและการเขียนเฉพาะแถวเปลี่ยนแล้ว; ต้อง benchmark HDD/USB/NAS ขนาดใหญ่ ตรวจการหยุดงาน/กลับมาทำต่อ/ไดรฟ์ออฟไลน์กับข้อมูลจริง |
| เพลงซ้ำ / คุณภาพ / ลบเพลง | duplicates, library_hygiene, name_duplicates, quality scan, recycle/restore | **ต้องทดสอบ Windows ก่อนใช้งานจริง**: ชุดทดสอบ 9 รายการยังไม่ผ่านบน Linux+Xvfb โดยกระจุกที่ลบและกู้คืนไฟล์ ไม่ควรยอมให้ระบบลบไฟล์จริงอัตโนมัติ |
| นำเข้าและจัดการโฟลเดอร์ | ingest, managed_import, song_workspace, path_relocate | มีชุด regression ครอบคลุม copy-to-Songs และ policy เพลงซ้ำ; ควรเพิ่มทดสอบ NCN/EMK/ไฟล์ไทย/พาธยาวบน NTFS และคัดลอกล้มเหลวกลางทาง |
| เล่นเพลง คิว และประวัติ | playback, performer, song_queue, performance_features, history | ระบบบันทึก start/finish และจำกัด history 500 รายการ; **v0.9.37 เพิ่มเพลงฮิตจากประวัติ**; ระยะต่อไปควรเพิ่มสถิติสะสมบน SQLite และระยะเวลาที่เล่นจริงโดยไม่กระทบ history เดิม |
| เมดเลย์และจังหวะ | medley, medley_full, medley_trim, medley_decks, random_medley | มีการจัดคิว ข้าม/ยกเลิกชุด และตรวจเพลงก่อนเล่น; โหมดสุ่มทั้งหมดเดิมอ่านแถวเพลงจำนวนมากทุกครั้ง ควรทำ sampling/limit ที่คงความยุติธรรม เพื่อไม่โหลดทั้งแคตตาล็อก |
| MIDI/SoundFont/เสียง | midi_input, soundfont, bass, PCM, EQ, media_routing, audio_diagnostics | ผ่าน unit tests ที่ไม่ต้องเปิดอุปกรณ์; ยังต้องรับรองเสียงจริง: เปลี่ยน SoundFont ระหว่างเล่น, latency, ไมค์, แยกช่อง, audio dropout, Windows driver และ EQ/APO |
| เนื้อร้อง วิดีโอ และคีย์เพลง | lyrics, smf, ncn_structure, emk, video route, key/speed | มีชุดทดสอบ parsing/transition; ควรใช้ชุดเพลงจริงหลายชนิดทดสอบเวลาเนื้อร้อง คีย์/tempo และการตัดจบเพลงเมื่อไฟล์เสีย |
| รีโมทมือถือ/Wi-Fi | remote, remote_requests, remote_audio, remote_page, wifi tools | โค้ดมี pairing/session/rate-limits และเงื่อนไขสิทธิ์; ควรทดสอบ Wi-Fi จริงเมื่อหลายเครื่องเชื่อมต่อ รวมความเสี่ยงบน LAN และคุณภาพเครือข่ายขาด/กลับมา |
| Google Drive/สำรอง/กู้คืน | google_drive_sync, cloud_sync, restore, json_recovery | มีชุดทดสอบ snapshot/recovery; ต้องทดสอบบัญชีจริง, quota เต็ม, token หมดอายุ, ยกเลิก upload, และกู้คืนตอนฐานหลาย GB บน Windows |
| Shutdown/งานเบื้องหลัง | auto_shutdown_dialog, jobs, runtime diagnostics | มีการตรวจ status และนับถอยหลัง 60 วินาที ยกเลิกได้; **ยังไม่สั่ง shutdown.exe จริง**; ต้องทดสอบปิดเครื่องเฉพาะงานสมบูรณ์ ไม่มีงานสำรอง/เสียงค้าง |
| Build / ติดตั้ง / ย้ายเครื่อง | Build-Source.ps1, build.ps1, installer, verify_release, native components | source/version gate ผ่าน; 5 PowerShell integration tests รันไม่ได้บน Linux; ต้องทำ Windows build gate ให้ผ่านก่อนออก EXE และทดสอบอัปเกรดใน `D:\newKaraoke` โดยสำรอง Data |

## ข้อที่ต้องแก้/พิสูจน์ก่อนออกเป็นรุ่นใช้งานจริง

### P0 — ความปลอดภัยข้อมูล
1. ดำเนินการ Windows-native integration test สำหรับ 9 กรณีใน `test_quality090` (ลบ, สำรอง, rollback, restore, hard link, shared lyrics, UI) ก่อนยอมรับระบบลบเพลงจริง
2. ทดสอบกู้ฐาน SQLite พร้อมคิว/เพลงโปรด/ประวัติหลังย้ายโฟลเดอร์และเมื่อตัดไฟขณะ Commit บน Windows
3. ทดสอบ Auto Shutdown กับงาน partial/cancelled/error รวมทั้งโปรแกรมอื่นมีไฟล์ไม่บันทึก และการกดยกเลิกใน 60 วินาที

### P1 — ความเร็วและประสบการณ์ใช้งาน
4. ใช้วิธีเลือกสุ่มจากแคตตาล็อกขนาดใหญ่แบบไม่ต้องโหลดทุกเพลงใน `random_medley.build_preview` โหมดคลังทั้งหมด; รักษากฎเพลงซ้ำและคิวเดิม
5. วัด Search/FTS, waveform/media metadata, SQLite WAL และ GUI main thread จริงบนเพลง 10k/100k/500k ด้วย SSD/HDD/NAS
6. เพิ่มสถิติจำนวนครั้งที่เล่นสะสมแบบ transaction (ไม่จำกัด 500 ประวัติล่าสุด) พร้อมตัวเลือกเพลงฮิต 7/30/90 วัน และป้องกันเพลงที่เพิ่งถูกเล่นกลับมาซ้ำเร็ว
7. ทดสอบการกู้ประวัติที่ JSON เสีย/ถูกแก้จากภายนอกโดยไม่ทำประวัติเดิมหาย

### P2 — เสียง เครือข่าย และการบำรุงรักษา
8. ทำ test matrix ของ MIDI/SoundFont/MP3/MP4/NCN/EMK, key/speed, crossfade, รีโมท, USB MIDI และไมค์บน Windows จริง
9. ทดสอบ remote pairing กับ 5–10 อุปกรณ์ เครือข่ายหลุดกลางคิวและป้องกันคำสั่งซ้ำ
10. แยกโมดูล UI ขนาดใหญ่และเพิ่ม automated GUI smoke tests สำหรับทุกหน้าต่างหลัก เพื่อตรวจ focus, lifecycle และ cancel worker

## ผลทดสอบอ้างอิง
- v0.9.36 ก่อนแก้: Linux + Xvfb รัน **898 รายการ, ผ่าน 877, ล้มเหลว 9, Error 5, ข้าม 7**; Linux แบบไม่ใช้ Xvfb พบ Fail 8, Error 25, ข้าม 7
- v0.9.37 หลังเพิ่มฟังก์ชัน: Linux + Xvfb รัน 911 รายการ, **ผ่าน 890, ล้มเหลว 9, Error 5, ข้าม 7**
- จุดที่ไม่ผ่านอยู่ที่กลุ่มลบไฟล์/กู้คืนแบบ Windows และ PowerShell **ตรงกับ v0.9.36 ทุกกรณี** ไม่ใช่ชุดทดสอบเมดเลย์เพลงฮิตใหม่
- รายงานนี้เป็นการ audit ซอร์ส+ทดสอบโดยไม่มี Windows/device tests; **ไม่อ้างว่าทุกฟังก์ชันผ่านการใช้งานจริง**
