# X-Stage Karaoke Windows PC — unified v1.0.76 (pending build)

The Web app, Android TV/tablet source and Windows PC source now use **v1.0.76 / build 1076** as a shared release label, but each platform has independent installation artifacts. A version label alone is **not** proof that a Windows installer is published.

## Windows continuous random medley

The source ZIP `X-Stage-Karaoke-v1.0.76-Windows-Source-Continuous-Medley.zip` includes:
- A new transport/menu action to **start continuous shuffled medley by detected song category**.
- Category groups from the indexed `rhythm` metadata, including unclassified songs; rotate groups rather than mixing blindly.
- Background, bounded batches of up to six playable tracks, refilled when the remaining queue is low.
- A stop action (including F8) that cancels pending automatic tracks but preserves manually queued tracks.
- Startup update check after eight seconds and hourly silent re-checks; a new verified release offers immediate download and SHA-256 validation.

**Import status:** The archive is not uploaded in this repository. Upload exactly `downloads/X-Stage-Karaoke-v1.0.76-Windows-Source-Continuous-Medley.zip` (SHA-256 `e93df7b13548dfd01b1d35e71cd521635bd82fd7ad60de33fa46fc6a29a9cdd7`, 447 files). GitHub Actions workflow `import-windows-pc-v1076-source.yml` then verifies/imports it. `build-windows-pc.yml` builds/tests on Windows. Keep `downloads/windows-pc-latest.json.available=false` until a tested installer is published.

---

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

## Windows PC update policy

- `downloads/windows-pc-latest.json` is the source of truth for verified Windows installer availability.
- Until the actual Windows installer passes CI and signature/integrity checks, `available` must remain `false`. Do not display an "install now" action without a verified artifact.
- `Check-Update.ps1 -CurrentVersion 0.9.48` checks release availability; add `-Install` to download, validate SHA-256, and launch the installer when a newer, verified release is available.
- The source import is currently incomplete, so the Windows application menu is **not yet wired** to this script. Once its source arrives, invoke the check on startup and from Help > Check for Updates without blocking playback. Offer immediate installation only after presenting the new version and stopping active audio safely.
- Web `1.0.74` and Android `1.0.74` are separate from Windows `0.9.48`; do not compare their numeric versions across platforms.

## Update notification behavior (R18.2 source, pending Windows build)

The verified R18.2 source archive adds `karaoke/program_updates.py`. The program calls `check_program_update(False)` eight seconds after launch (non-blocking), and the update menu calls `check_program_update(True)`. When `downloads/windows-pc-latest.json` explicitly advertises a newer verified Windows installer, the application asks the user whether to download immediately. It validates SHA-256, then asks for confirmation before launching the installer. Song files and Drive data are not overwritten by the updater.

**Deployment blocker:** The update-enabled R18.2 archive is not yet imported into `windows-pc/source/`, and no tested Windows installer has been published. `available: false` is correct until a Windows build and installer are verified. Previously installed Windows builds cannot gain this new update UI until upgraded to an installer containing the R18.2 source.
