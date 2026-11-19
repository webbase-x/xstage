"""Reject preview EXEs without an embedded Windows application icon."""
import sys
import pefile

if len(sys.argv) != 2:
    raise SystemExit("usage: verify_exe_icon.py <exe>")
pe = pefile.PE(sys.argv[1], fast_load=False)
pe.parse_data_directories(
    directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
)
if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
    raise SystemExit("FAIL: no Windows resources embedded in the EXE")
types = {entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
if 3 not in types or 14 not in types:
    raise SystemExit("FAIL: missing RT_ICON or RT_GROUP_ICON")
print("PASS: embedded native Windows icon resource present")
