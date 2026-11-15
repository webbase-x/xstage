# X-Stage Karaoke Windows — R13: SQLite test-file lock (WinError 32)

วันที่ตรวจ: 9 พฤศจิกายน 2569 · ซอร์สพื้นฐาน: Responsive Online R12 · โปรแกรม v0.9.48

## ปัญหาจาก Build Gate จริง

Windows 11 / Python 3.13.5 รายงาน 1,131 tests, failure 0, error 1, skipped 102.
กรณีเดียวที่ Error คือ:

`test_online_fast_preflight_r11.FastSQLPreflightTests.test_counts_large_catalog_without_touching_missing_media`

Traceback: `tempfile.TemporaryDirectory` พยายามลบ `songs.sqlite3` ขณะยังมี connection จากขั้นตอนสร้างฐานเพลงจำลองเปิดอยู่ จึงถูก Windows ปฏิเสธด้วย `PermissionError: [WinError 32]`.

## ต้นเหตุและการแก้ไข

`with sqlite3.connect(db) as conn:` จัดการ `commit/rollback` แต่ไม่ได้รับประกันว่าจะเรียก `conn.close()` เมื่อออกจาก `with` ใน Python บน Windows ตัวแปร `conn` ยังถือ connection อยู่จนจบ function; การลบ Temp Directory เกิดก่อนหน้านั้น.

แก้ใน `tests/test_online_fast_preflight_r11.py` โดยใช้ `contextlib.closing` ร่วมกับ context manager ของ transaction:

```python
from contextlib import closing

with closing(sqlite3.connect(db)) as conn, conn:
    ...  # create table / insert data
```

เมื่อออกจาก `with` จะ commit ก่อนและปิด SQLite connection แน่นอน ก่อนมีการลบ directory ชั่วคราว.

**แก้เฉพาะ test fixture** ไม่มีการแก้ `karaoke/online_preflight.py`, คลังเพลง, SQL schema, ข้อมูลบน Google Drive, OAuth หรือ Pipeline และไม่ได้ข้ามหรือปิด Test Gate.

## วิธีใช้ไฟล์

1. สำรอง `D:\newKaraoke\Data` ตามขั้นตอนปกติ แม้การแก้ครั้งนี้ไม่แตะ Data จริง.
2. ถ้าใช้ซอร์สเต็ม ให้แตก `X-Stage-Karaoke-v0.9.48-Windows-Source-BuildGate-SQLite-R13.zip` ลงโฟลเดอร์ใหม่.
3. ถ้าใช้ Hotfix R13 กับ **R12 เท่านั้น** ให้ปิดโปรแกรมที่กำลังรันจากซอร์ส, แตกไฟล์ทับโฟลเดอร์ซอร์ส R12 โดยคงโครงสร้าง `tests/` เดิม.
4. รัน `Verify-Windows-0948.cmd` หรือ `Build-Windows.cmd` ใหม่; เกณฑ์ผ่านคือ Failure 0, Error 0 และ `BUILD TEST RESULT: PASS`.
5. Build EXE และติดตั้งต่อ **เฉพาะหลัง Gate ผ่าน**. ถ้ามี error ใหม่ ให้ดู `build-tests.log` และ `build-tests-summary.json` ของรอบใหม่ ไม่ใช่ของรอบก่อน.

**ไม่จำเป็นต้องลบไฟล์เพลง แคชอัปโหลด หรือฐานเพลงเดิม** และไม่ควรลบ Temp Directory ตอนยังมีการรันทดสอบ.

## ขอบเขตการยืนยัน

ทดสอบกรณีที่ล้มเหลวซ้ำใน Linux ผ่านแล้ว; การปิดไฟล์ด้วย `closing()` เป็นการแก้สาเหตุของ WinError 32 จาก traceback ที่แนบมาโดยตรง. การ Build Windows EXE และทดสอบบน Windows ของผู้ใช้ยังต้องทำที่เครื่อง Windows จริง.
