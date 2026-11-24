# X-Stage Windows Volume Bridge

ดาวน์โหลด [EXE โดยตรง](https://github.com/webbase-x/xstage/releases/download/windows-volume-bridge/XStageWindowsVolumeBridge.exe) แล้วเปิดบน Windows 10/11 ด้วยสิทธิ์ผู้ใช้ปกติ

อนุญาตในหน้าต่าง Windows ครั้งแรก เลือกได้ว่าจะเริ่มพร้อม Windows หรือไม่ เปิด Karaoke Online แล้วระบบตรวจพบอัตโนมัติ ไม่ต้องกรอกรหัส โปรแกรมฟังเฉพาะ 127.0.0.1:48731 ตรวจ Origin และใช้ bearer token ในหน่วยความจำ

ทุกครั้งที่เปิด EXE โปรแกรมตรวจรุ่นจาก GitHub Release ของโครงการ ตรวจ SHA-256 ที่ GitHub รายงานก่อนติดตั้ง และไม่ติดตั้งรุ่นย้อนหลัง หากอัปเดตไม่ได้ให้ใช้รุ่นเดิมต่อ การอัปเดตไม่ทำขณะโปรแกรมกำลังให้บริการ

ยกเลิกการอนุญาตถาวรโดยปิดโปรแกรมและลบ %LOCALAPPDATA%\XStage\VolumeBridge\approved-v1 ยกเลิกเริ่มพร้อม Windows ใน Task Manager > Startup apps
