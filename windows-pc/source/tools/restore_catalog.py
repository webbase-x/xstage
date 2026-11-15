"""Offline, interactive restoration of a checked X-Stage song catalog snapshot.

Close X-Stage Karaoke before running this tool. Requires CPython 3.13 and the
unpacked source folder; this script is not an unattended installer operation.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Works whether invoked from a source checkout or another working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from karaoke.library import SongLibrary


def main(argv=None):
    parser = argparse.ArgumentParser(description='X-Stage Karaoke — checked catalog backup restore')
    parser.add_argument('--database', type=Path, default=Path(r'D:\newKaraoke\Data\songs.sqlite3'),
                        help='Path to the existing songs.sqlite3')
    parser.add_argument('--list', action='store_true', help='List snapshots only')
    args = parser.parse_args(argv)
    if not args.database.is_file():
        parser.error('ไม่พบฐานข้อมูลเพลง: ' + str(args.database))
    library = SongLibrary(args.database)
    copies = library.list_reindex_backups(include_legacy=True)
    if not copies:
        print('ไม่พบไฟล์สำรองจากระบบจัดทำรายการเพลง')
        return 1
    print('สำเนาฐานเพลง (ใหม่สุดก่อน):')
    for idx, item in enumerate(copies, 1):
        print(f'  {idx}. {item.name} ({item.stat().st_size:,} bytes)')
    if args.list:
        return 0
    print('\nปิด X-Stage Karaoke และโปรแกรมอื่นที่กำลังใช้ฐานเพลงก่อนดำเนินการ')
    answer = input('เลือกลำดับไฟล์สำรองเพื่อกู้คืน (Enter = ยกเลิก): ').strip()
    if not answer:
        return 0
    if not answer.isdecimal() or not (1 <= int(answer) <= len(copies)):
        print('ลำดับที่เลือกไม่ถูกต้อง')
        return 2
    selection = copies[int(answer)-1]
    print('จะใช้สำเนา: ' + selection.name)
    if input('พิมพ์ RESTORE เพื่อยืนยัน: ').strip() != 'RESTORE':
        print('ยกเลิกแล้ว')
        return 0
    safety = library.restore_reindex_backup(selection)
    print('กู้คืนฐานข้อมูลเรียบร้อย · สำเนาก่อนกู้คืน: ' + str(safety))
    print('เมื่อเปิด X-Stage ให้สร้างรายการแบบ Fast เพื่อจัดข้อมูลไฟล์จริงอีกครั้ง')
    return 0


if __name__ == '__main__':
    sys.exit(main())
