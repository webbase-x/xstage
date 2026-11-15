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
