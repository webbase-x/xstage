# X-Stage Karaoke Online

เว็บ static สำหรับ GitHub Pages ใช้ Google OAuth และ Google Drive ของผู้ใช้

1. ติดตั้งและตั้งค่า X-Stage Karaoke บน PC
2. กดซิงก์เพื่อสร้าง `web-manifest.json` และชุดข้อมูลต่อผู้ใช้ใน Google Drive
3. คัดลอก `config.js.example` เป็น `config.js` แล้วใส่ Google OAuth Web Client ID
4. เผยแพร่โฟลเดอร์นี้บน GitHub Pages
5. ผู้ใช้เปิดเว็บ ล็อกอิน Google และค้นหา/เล่นเพลงจาก Drive

เว็บใช้ manifest สำหรับรายการเพลง และไม่เปิด SQLite จาก Drive โดยตรง

