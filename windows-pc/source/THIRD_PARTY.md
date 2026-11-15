## Remote output audio (0.5.35)

Windows builds include SoundCard 0.4.6 (BSD-3-Clause; see third_party_licenses/SoundCard-LICENSE.txt), with its NumPy/CFFI dependencies installed by pip and bundled by PyInstaller. SoundCard package data, including its Windows CFFI header, is collected explicitly.
Project: https://github.com/bastibe/SoundCard
API reference: https://soundcard.readthedocs.io/en/latest/
Loopback: https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording
Browser audio activation: https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices
Fullscreen capability: https://developer.mozilla.org/en-US/docs/Web/API/Element/requestFullscreen

# Runtime and API references

This implementation contains no KaraPlayer binaries, eXtreme DLLs, dongle
drivers, copied program code, or bundled songs from third parties.

Runtime: Python standard library (Python Software Foundation License),
Tcl/Tk (included in the Windows Python installation under its own licenses),
and the Windows system WinMM library (provided by Windows, not redistributed).
An optional packaged build also includes Python/Tcl/Tk and the PyInstaller
bootloader; their accompanying notices are included in `third_party_licenses`
and `_internal`.

API references used for the independent implementation:

- https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-midioutopen
- https://learn.microsoft.com/en-us/windows/win32/multimedia/sending-individual-midi-messages
- https://learn.microsoft.com/en-us/windows/win32/multimedia/window
- https://learn.microsoft.com/en-us/windows/win32/multimedia/changing-the-playback-state
- https://docs.python.org/3/library/tkinter.html

WAV uses native PCM waveOut playback and does not require an MCI codec.
MCI is a legacy Windows API used for other media. Codec and playback speed support vary
by computer. MP4/MKV success is not guaranteed; failures are surfaced to the
user and the queued song remains queued. Media speed may also change pitch.


Version 0.2 adds Pillow (HPND and bundled dependency notices), SQLite FTS5, and independent public-format readers. The release copies Pillow distribution license files into third_party_licenses. BASS/BASSMIDI are optional, downloaded separately from Un4seen; no DLL or SoundFont from eXtreme is redistributed. NCN interoperability reference: https://www.un4seen.com/forum/?topic=11559.0 . EMK format reference: https://docs.rs/crate/emk-rs/0.2.0/source/emk-spec.md . No source code was copied from those implementations.
# Windows text layout

การจัดรูปอักษรไทยใช้ Uniscribe (`usp10.dll`) และ GDI ของ Windows ที่ติดตั้งอยู่ในระบบ
ไม่มีการแนบ DLL หรือไฟล์ฟอนต์ของ Windows มาในชุดโปรแกรม
เอกสาร API: https://learn.microsoft.com/en-us/windows/win32/intl/using-the-scriptstring-functions


SoundFont v0.5.0 uses the documented BASSMIDI API for float synthesis, sinc SRC, font gain and stacking. Official libraries used for Linux offline PCM verification were downloaded from https://www.un4seen.com/files/bass24-linux.zip and https://www.un4seen.com/files/bassmidi24-linux.zip. They are not redistributed in this source preview. tests/soundfont_fixture.py generates an original sine-wave SF2 solely for automated tests, not a production sound library.
See SOUNDFONT_GUIDE_TH.md for API references and runtime limitations.

## qrcode 8.x
Python QR encoder used locally for the mobile invitation. BSD license: third_party_licenses/qrcode-LICENSE.txt. No external QR service is used.

## FFmpeg for X-Stage Online v0.9.46
The Windows build installs imageio-ffmpeg 0.6.0 (Python wrapper, BSD-2-Clause)
and bundles its platform-specific FFmpeg executable as part of the application.
FFmpeg itself has distinct LGPL/GPL licensing depending on the binary build;
redistributors must comply with the actual binary license, applicable source
availability obligations and notices. See https://ffmpeg.org/legal.html and
https://github.com/imageio/imageio-ffmpeg . The app does not bundle SoundFonts
or user songs.
