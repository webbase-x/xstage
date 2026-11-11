# Windows Installer local build kit FIX4 (v1.0.76)

When winget successfully installs Inno Setup 6.7.3 but the installer still reports that ISCC.exe is missing, the failure is **compiler discovery**, not a failed winget installation.

The FIX4 build kit includes a replacement `Build-Installer.ps1` that checks:
- `XSTAGE_INNO_ISCC` override and `ISCC.exe` on PATH
- Program Files (64 and 32 bit), per-user LocalAppData and AppData
- User and machine uninstall registry entries
- Versioned `%LOCALAPPDATA%\Microsoft\WinGet\Packages\JRSoftware.InnoSetup*` directories
- A manual path prompt if automatic discovery fails.

It deliberately does **not** reject an existing executable only because `VersionInfo.ProductMajorPart` differs or is unavailable.

Build from a fresh extracted FIX4 ZIP. The Inno compiler can be set explicitly in the same PowerShell session as:
```powershell
$env:XSTAGE_INNO_ISCC = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
.\Build-Installer.ps1
```
Adjust the path to where ISCC.exe actually exists. Never disable regression tests or mark a candidate as publicly installable before Build and manual install checks pass.
