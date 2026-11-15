# X-Stage Karaoke Online — Private Drive

เว็บสำหรับ GitHub Pages ใช้ Google OAuth `drive.file` อ่านคลัง `XStageWeb` ที่ X-Stage Windows สร้างไว้ใน Google Drive ส่วนตัวของผู้ใช้แต่ละบัญชี. ไม่มีไฟล์เพลง/เนื้อร้องหรือ Token อยู่ใน GitHub. เว็บไซต์เริ่มจาก `current.json`, แล้วอ่าน `database-*.json` และโหลด M4A/lyrics JSON ตาม File ID ในบัญชีนั้น. ไม่ใช้ชุด Backup หรือ `web-manifest.json` เดิม.

ต้องตั้ง Google OAuth Web Client ID (ข้อมูลสาธารณะ) ใน `config.js` และ Authorized JavaScript origins ให้ตรงกับเว็บไซต์. ห้ามเผยแพร่ OAuth Client Secret. Browser ปัจจุบันดาวน์โหลด M4A ทั้งไฟล์เป็น Blob ก่อนเล่น; ยังไม่ใช่ streaming รายช่วง.
