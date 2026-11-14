# X-Stage Karaoke Online — No-Console Recovery R5

## สาเหตุและสิ่งที่แก้ไข

- รุ่น R4 Build ด้วย PyInstaller `--windowed` อยู่แล้ว แต่คำสั่งเบื้องหลังบางส่วนเรียก `ffmpeg.exe` และ `ffprobe.exe` โดยไม่กำหนด `CREATE_NO_WINDOW` ทำให้ Windows อาจเปิดหน้าต่าง CMD ระหว่างตรวจโปรแกรมแปลงเสียง หรือขณะแปลงเพลง
- เพิ่ม `karaoke/windows_process.py` กำหนด `CREATE_NO_WINDOW` และ `STARTUPINFO` (ซ่อนหน้าต่าง) **เฉพาะ Windows** เพื่อใช้กับคำสั่งที่ไม่ต้องรับข้อมูลจากผู้ใช้
- แก้ `karaoke/web_assets.py` สำหรับเข้ารหัส AAC ผ่าน FFmpeg, `karaoke/web_environment.py` สำหรับตรวจ FFmpeg และ `karaoke/offline_generator.py` สำหรับตรวจ AAC ด้วย FFprobe
- คง `stdout/stderr` แบบเดิมเพื่อให้ตรวจผลลัพธ์และบันทึกข้อความผิดพลาดได้ ไม่ละเลยการตรวจสอบคุณภาพไฟล์
- เพิ่ม `Start-XStage-Silent.vbs` เพื่อเปิดตัวโปรแกรมโดยไม่เรียก CMD และให้ตัวติดตั้งคัดลอกไฟล์นี้ไปยังโฟลเดอร์ X-Stage ด้วย
- เพิ่มชื่อรุ่นบนหน้าต่างซิงค์ `[Recovery r5]` สำหรับแยกจาก EXE เดิม
- ไม่แก้ไฟล์เพลงจริง ฐานข้อมูลเพลง คิวเพลง การลงชื่อเข้าใช้ Google หรือระบบกู้คืนงานซิงค์ของ R4

## เมื่อ Build และติดตั้งเสร็จ

1. เปิด X-Stage ด้วย `D:\newKaraoke\X-Stage Karaoke.lnk` (ทางลัดที่ชี้ตรงไปยัง EXE) หรือ `D:\newKaraoke\Start-XStage-Silent.vbs` ที่ตัวติดตั้งสร้างไว้ หลีกเลี่ยงการเปิด `Start-Karaoke.cmd`/`X-Stage Karaoke.cmd` หากไม่ต้องการเห็น CMD แม้เพียงชั่วคราว
2. เข้าเมนูซิงค์ออนไลน์และตรวจชื่อหน้าต่างว่ามี `[Recovery r5]`
3. ซิงค์เพลงทดสอบ 1–2 เพลงและสังเกตว่าไม่มีหน้าต่าง CMD/PowerShell เปิดขึ้นระหว่างตรวจ FFmpeg/FFprobe และแปลง M4A
4. ตรวจไฟล์ผลลัพธ์และรายงานข้อผิดพลาดตามขั้นตอนเดิม และทดสอบซิงค์ต่อเมื่อปิดหน้าต่างอย่างถูกต้อง

> ไฟล์ `Build-Windows.cmd`, `Verify-Windows-0948.cmd`, `Install-to-D.cmd` และเมนูซ่อมอุปกรณ์/ส่วนประกอบเป็น **เครื่องมือสำหรับผู้ดูแล** ซึ่งยังอาจเปิด Console/UAC เมื่อผู้ใช้เรียกใช้โดยตั้งใจ ไม่ได้เปลี่ยนให้ทำงานเงียบเพื่อไม่ซ่อนข้อผิดพลาดของการติดตั้ง/ซ่อมระบบ

## การ Build

ไฟล์ที่ส่งเป็นซอร์ส/แพตช์ **ยังไม่ใช่ EXE สำเร็จรูป** ให้แตกไปยังโฟลเดอร์ใหม่ก่อน แนะนำสำรอง `D:\newKaraoke\Data` และใช้ Windows ตามลำดับ:

1. `Verify-Windows-0948.cmd`
2. `Build-Windows.cmd`
3. ทดสอบ `dist\XStageKaraoke\XStageKaraoke.exe` และ `Start-XStage-Silent.vbs` ก่อนติดตั้งทับ
4. เมื่อตรวจผ่านแล้วจึง `Install-to-D.cmd` ตามขั้นตอนปัจจุบัน

## ผลทดสอบในสภาพแวดล้อมนี้

- Unit test เฉพาะ Windows Console policy ใหม่ **6/6 ผ่าน**
- ชุดทดสอบส่วนแปลงเพลง/ซิงค์/กู้คืน/Google Session รวม **62 รายการ (ผ่าน 60, ข้าม 2)**
- GUI จำลองภายใต้ Xvfb: **8 รายการผ่าน** (รวมตรวจปุ่ม Google Login และ Resume)
- ยังไม่สามารถยืนยันว่าไม่มี CMD บน Windows จริง และยังไม่ได้ Build EXE แบบ Windows; ต้องตรวจผ่าน Windows Build Gate และทดสอบโปรแกรมจริงบนเครื่อง
