# X-Stage Karaoke PC — Windows CMD source preview

This ZIP contains the **Windows PC Python source**, not a compiled EXE.
It does not contain X-Stage Karaoke Online, Android APK, or Song Studio builds.

## Run on Windows 10 / Windows 11 (x64)

1. Download **Windows-CMD-Source ZIP** from the GitHub Actions artifact and extract **both ZIP layers** if GitHub downloaded an artifact ZIP containing the source ZIP. Extract the entire *inner* source ZIP to a normal writable directory (avoid Program Files). In the extracted source directory, `Run-X-Stage-Karaoke-PC.cmd` and `main.py` must be alongside one another, with `karaoke/` and `requirements.txt`. Current packages place these files at the source ZIP root; older packages may nest them under `X-Stage-Karaoke-PC-Source/`.
2. Install **Python 3.13 x64** with Tcl/Tk and the Python launcher (if not already installed).
3. Double-click **Run-X-Stage-Karaoke-PC.cmd**, or open CMD in this folder and run:

   ```cmd
   Run-X-Stage-Karaoke-PC.cmd
   ```

   The first run creates a local `.venv` and installs Python packages from `requirements.txt`. Internet access is needed once for missing packages.
4. Use **Test-X-Stage-Karaoke-PC.cmd** to run the full Python regression suite and produce `build-tests-summary.json` and `build-tests.log`.

## Data isolation and safeguards

- The preview uses **.local-test-data/** alongside the source and does not deliberately modify an installed PC user's Data folder.
- Existing music files are **not bundled**; choose the music folder yourself in the application.
- The ZIP is a **source test package**, not a fully offline production installer. Some native MIDI/audio features can need system codecs, the appropriate SoundFont, or native components. Do not assume all hardware-specific audio functions are certified by the Python unit tests.
- Keep the whole source directory intact. Do not run `install_to_D.ps1` merely to try the source preview.
- Internally the executable name remains `XStageKaraoke.exe` for compatibility; public application branding is **X-Stage Karaoke PC**.
