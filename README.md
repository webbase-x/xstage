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

เมนูที่ต้องเข้าถึง BASSMIDI/SoundFont, MIDI Mixer, Windows MIDI ports, ASIO, การแก้ไข SQLite ต้นทาง และการเปลี่ยนคีย์อิสระจากเสียง M4A ยังคงใช้บน Windows เท่านั้น เว็บไซต์ไม่เก็บไฟล์เพลงส่วนตัวหรือ Google OAuth Token ใน GitHub
