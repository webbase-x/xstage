# X-Stage Karaoke — Windows PC (source import)

The Windows PC application is **separate** from the Android TV/tablet APK and the GitHub Pages web app. Keep all three in this existing repository `webbase-x/xstage`.

## Latest Windows source identified

- **Windows app version:** `v0.9.48`
- **Source revision:** `TurboSync R18.1 — Thai ETA`
- **Exact source ZIP:** `X-Stage-Karaoke-v0.9.48-Windows-Source-TurboSync-R18.1-Thai-ETA.zip`
- **Size:** 3,842,804 bytes
- **SHA-256:** `2e7769c70580b61996ff2e351a20c30816dc674dcc8db1ee257fc1ed8c062beb`
- **Contents:** 444 file entries
- **Build status:** **NOT VERIFIED** on Windows; this is not an installer or a released EXE.

## Complete the source import

1. Upload the **exact ZIP** to `downloads/X-Stage-Karaoke-v0.9.48-Windows-Source-TurboSync-R18.1-Thai-ETA.zip` in this repository.
2. GitHub Actions workflow **Import X-Stage Windows PC v0.9.48 R18.1 source** automatically validates SHA-256, checks safe ZIP paths, and extracts to `windows-pc/source/`.
3. The workflow commits only `windows-pc/source/` and `windows-pc/manifest.json` on the same branch. It does not change the web app, Android TV source, version numbering, or existing song libraries.

GitHub can also run the workflow manually from the Actions tab after the ZIP has been uploaded.

## Windows build gate (after source import)

The Windows source includes `Verify-Windows-0948.cmd`, `Build-Windows.cmd`, and `Build-Source.ps1`. Build on **Windows** with the locked CPython 3.13 x64 environment. Do **not** upload or advertise `XStageKaraoke.exe` until the full Windows build tests and installer checks pass. Earlier v0.9.48 build logs included failures and did **not** produce an executable.

Keep OAuth client secrets, tokens, customer music, personal SQLite databases and private Google Drive contents out of the repository.
