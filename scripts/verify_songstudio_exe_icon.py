"""Verify that a Windows PE executable embeds real icon resources.

Checks RT_GROUP_ICON (14) and RT_ICON (3) in the PE resource directory.
This deliberately uses Python's standard library: no pip install is required.
It does not claim the file is signed or the program is otherwise functional.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path


class IconVerificationError(ValueError):
    pass


def verify_icon(path: Path) -> tuple[int, int]:
    data = path.read_bytes()

    def read(fmt: str, off: int):
        size = struct.calcsize(fmt)
        if off < 0 or off + size > len(data):
            raise IconVerificationError("truncated PE header/resource")
        return struct.unpack_from(fmt, data, off)

    if data[:2] != b"MZ":
        raise IconVerificationError("not a Windows MZ executable")
    pe_off = read("<I", 0x3C)[0]
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise IconVerificationError("invalid PE signature")

    coff = pe_off + 4
    section_count = read("<H", coff + 2)[0]
    optional_size = read("<H", coff + 16)[0]
    opt = coff + 20
    magic = read("<H", opt)[0]
    if magic not in (0x10B, 0x20B):
        raise IconVerificationError("unsupported PE optional header")
    directories = opt + (96 if magic == 0x10B else 112)
    if directories + 8 * 3 > opt + optional_size:
        raise IconVerificationError("no PE resource directory")
    resource_rva, resource_size = read("<II", directories + 8 * 2)
    if not resource_rva or not resource_size:
        raise IconVerificationError("PE contains no resource directory")

    sections = []
    for i in range(section_count):
        sec = opt + optional_size + 40 * i
        virtual_size, rva, raw_size, raw_ptr = read("<IIII", sec + 8)
        sections.append((rva, max(virtual_size, raw_size), raw_ptr))

    def offset_for_rva(rva: int) -> int:
        for start, size, raw_ptr in sections:
            if start <= rva < start + size:
                offset = raw_ptr + (rva - start)
                if offset < len(data):
                    return offset
        raise IconVerificationError("invalid resource RVA")

    resource_base = offset_for_rva(resource_rva)

    def entries(relative: int):
        pos = resource_base + relative
        named, ids = read("<HH", pos + 12)
        count = named + ids
        if count > 100000:
            raise IconVerificationError("invalid resource entries count")
        for i in range(count):
            value, child = read("<II", pos + 16 + 8 * i)
            ident = (value & 0xFFFF) if not (value & 0x80000000) else None
            yield ident, child

    def raw_resources(branch: int):
        def visit(node: int, depth: int):
            if depth >= 8:
                raise IconVerificationError("resource nesting too deep")
            if node & 0x80000000:
                for ident, child in entries(node & 0x7FFFFFFF):
                    yield from visit(child, depth + 1)
            else:
                position = resource_base + node
                rva, size = read("<II", position)
                off = offset_for_rva(rva)
                if size > len(data) - off:
                    raise IconVerificationError("truncated icon resource")
                yield data[off:off + size]
        yield from visit(branch, 0)

    types = {ident: child for ident, child in entries(0) if ident is not None}
    icons = list(raw_resources(types[3])) if 3 in types else []
    groups = list(raw_resources(types[14])) if 14 in types else []
    good_groups = 0
    for group in groups:
        if len(group) < 6:
            continue
        reserved, resource_type, count = struct.unpack_from("<HHH", group)
        if reserved == 0 and resource_type == 1 and count > 0 and len(group) >= 6 + 14 * count:
            good_groups += 1
    if not icons or not good_groups:
        raise IconVerificationError(
            f"branded Windows icon missing: RT_ICON={len(icons)}, "
            f"valid RT_GROUP_ICON={good_groups}"
        )
    return len(icons), good_groups


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: verify_songstudio_exe_icon.py path-to-app-or-installer.exe", file=sys.stderr)
        return 2
    for filename in sys.argv[1:]:
        try:
            path = Path(filename)
            if path.suffix.lower() != ".exe" or not path.is_file():
                raise IconVerificationError("expected an existing .exe file")
            icons, groups = verify_icon(path)
            print(f"OK: {path} embeds {icons} icon images / {groups} icon group(s)")
        except (OSError, IconVerificationError) as exc:
            print(f"FAIL: {filename}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
