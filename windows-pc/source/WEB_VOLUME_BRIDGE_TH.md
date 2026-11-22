# X-Stage Karaoke Online — การเชื่อมเสียงหลัก Windows

หน้าเว็บ [X-Stage Karaoke Online](https://webbase-x.github.io/xstage/karaoke.html) ไม่สามารถสั่ง Windows Core Audio Master Volume ได้โดยตรงตามข้อจำกัดของเบราว์เซอร์ แถบเสียงเว็บกับ Windows Volume Mixer เป็นคนละระดับ การเลื่อนล้อเมาส์บนเว็บจะปรับเฉพาะเสียงของเว็บ เว้นแต่ผู้ใช้ **เปิดและจับคู่โปรแกรมช่วย Windows** ตามขั้นตอนด้านล่าง

## วิธีเชื่อม (Windows 10 / Windows 11)

1. เปิด [Build X-Stage Windows Volume Bridge](https://github.com/webbase-x/xstage/actions/workflows/build-web-volume-bridge.yml) เลือก Workflow Run ที่มีสถานะผ่าน และดาวน์โหลด Artifact ชื่อ `XStageWindowsVolumeBridge-Windows-EXE` (จะได้ ZIP)
2. แตก ZIP และเปิด `XStageWindowsVolumeBridge.exe` ด้วยสิทธิ์ผู้ใช้ปกติ **ไม่ต้อง Run as administrator** โปรแกรมแสดงรหัส 10 หลักในหน้าต่าง Command Prompt และรอรับคำสั่งเฉพาะ `127.0.0.1:48731`
3. เปิด Karaoke Online ใน Chrome บน Windows เครื่องเดียวกัน กดปุ่ม **↔ Win** ข้างแถบระดับเสียง กรอกรหัส 10 หลัก แล้วกด **เชื่อมเสียง Windows** หาก Chrome ขอ Local network access ให้ยืนยันว่าเป็นการเชื่อมกับตัวช่วยที่เพิ่งเปิดเอง
4. เมื่อเห็น **● Win** แถบเสียงในเว็บจะแสดงระดับเสียงหลัก Windows ที่อ่านได้จริง การเลื่อนล้อเมาส์บนเวที/แถบเสียงปรับเสียง Windows ครั้งละ 5% การเปลี่ยนค่าใน Windows จะสะท้อนกลับในเว็บโดยประมาณทุก 0.5 วินาที
5. ต้องการเลิกใช้ให้กด **● Win → ตัดการเชื่อมต่อ** หรือปิดโปรแกรมช่วย (Ctrl+C หรือปิดหน้าต่าง) เว็บจะกลับไปควบคุมเสียงของตัวเอง

ไม่ต้องปิดระบบป้องกัน Chrome และไม่มีการดักล้อเมาส์ทั่วทั้ง Windows; เว็บรับเหตุการณ์ได้เฉพาะตอนหน้าต่าง/พื้นที่เว็บมีโฟกัส เมื่อ Quick Settings หรือแอปอื่นมีโฟกัส ให้เลื่อนแถบเสียง Windows ตามปกติและระบบจะซิงก์ระดับเสียงกลับหลังเชื่อมแล้ว

## ความปลอดภัยและข้อจำกัด

- โปรแกรมช่วยไม่เริ่มทำงานเอง ไม่ตั้งค่า Startup และไม่ติดตั้ง Windows Service
- รับคำสั่งผ่าน loopback ภายในเครื่องเท่านั้น จำกัด Origin เป็น `https://webbase-x.github.io` และต้องจับคู่ด้วยรหัส 10 หลักก่อนสั่งอ่าน/เขียนระดับเสียง
- โทเค็นที่จับคู่เก็บในหน่วยความจำของหน้าเว็บเท่านั้น รีโหลดหน้าเว็บหรือรีสตาร์ตตัวช่วยต้องจับคู่ใหม่
- ปรับเฉพาะระดับเสียงหลัก (Default Playback Endpoint) และสถานะ mute ของ Windows ไม่เปลี่ยนระดับเสียงรายแอปใน Windows Volume Mixer
- เมื่อเชื่อมแล้ว ตัวเล่น HTML/MIDI ในเว็บใช้ gain 100% เพื่อไม่ลดเสียงซ้ำกับ Windows; เมื่อยกเลิกจะคืนการปรับเสียงเฉพาะเว็บ
- หากอุปกรณ์เสียงหลักถูกถอด เปลี่ยนระหว่างใช้งาน หรือ Windows ปฏิเสธคำสั่ง แอปจะรายงานการเชื่อมต่อผิดพลาดและกลับสู่การควบคุมเสียงเฉพาะเว็บ
- EXE ที่สร้างโดย GitHub Actions เป็นเวอร์ชันทดสอบที่ไม่ได้ลงลายเซ็นดิจิทัล ตรวจสอบผู้เผยแพร่และไฟล์ก่อนเปิด; ไม่มีการอ้างว่าทดสอบเสียงออกลำโพงจริงทุกอุปกรณ์แล้ว

## การพัฒนาและทดสอบซอร์ส

ซอร์สอยู่ที่ `windows-pc/source/karaoke/web_volume_bridge.py` และนำ Windows Core Audio จาก `karaoke/system_volume.py` มาใช้ ทดสอบข้อกำหนด HTTP โดยไม่ต้องมีฮาร์ดแวร์ Windows ด้วย:

```powershell
cd windows-pc/source
python -m unittest discover -s tests -p test_web_volume_bridge.py -v
python -m karaoke.web_volume_bridge
```

การทดสอบเว็บใช้ `node scripts/windows-volume-bridge-contract-test.mjs` และ CI สร้าง EXE บน `windows-2022` พร้อมการทดสอบเซิร์ฟเวอร์ localhost แต่ไม่สามารถยืนยันความสัมพันธ์กับลำโพงจริงจาก CI เพียงอย่างเดียว
