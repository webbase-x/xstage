# X-Stage Karaoke PC — Professional Live Roadmap (P0–P6)

**Project:** `webbase-x/xstage` — keep the existing `windows-pc/source/` application and user data.  
**Last audited:** 2026-11-21 (Asia/Bangkok).  
**Current phase:** **P0 (blocked from progression until every P0 gate passes).**  
**Tracking:** 27 acceptance items in 7 sequential phases. Each item requires test evidence; absence of Windows hardware evidence is **NOT PASS**.  
**Safety:** Do not break existing SQLite, queue, history, SoundFont settings, lyrics, medley, or user song directories. Avoid unverified auto-delete and do not advertise a production update from a preview-only build.

## Current verified baseline

- Windows candidate CI [run 44824614592](https://github.com/webbase-x/xstage/actions/runs/44824614592), source commit `ac7620ebe3a37223797199515504dec21e8254f3`: **1,014 tests run, 0 failed, 0 errors, 78 skipped**; Windows EXE + Inno Setup installer compiled; BASS DLL architecture, icon and SHA-256 checks passed.
- Candidate installer SHA-256: `14c5eb8d494dfd206ed9da26903be6e96ef818d1a103a5d62f57c110f7f0dd61`.
- Public **unsigned preview** publication [run 44825421635](https://github.com/webbase-x/xstage/actions/runs/44825421635) succeeded. This is *not* a signed stable release.
- The current `.github/workflows/build-windows-pc.yml` now also defines **Install candidate silently and verify installed runtime**; that step **was not present in the successful CI job's step list**. Must be executed on the current workflow revision before accepting P0.3.
- `windows-pc/manifest.json` still has `windows_build_verified: false`, `installer_published: false` and status `SOURCE_IMPORTED_NOT_A_WINDOWS_RELEASE`. This is conservative release status; do not confuse it with the distinct preview publication.
- Previous failing tests `test_component_repair_requires_windows_consent_before_exit` and `test_mixer_follows_new_engine_and_cancels_poll_on_close` have fixes in main; rerun them as part of the next Windows gate.
- **Known limitation:** GitHub-hosted tests do not prove long-duration playback, actual analog audio outputs, USB interface/driver operation, or a user's Windows machine.

## Acceptance checklist — complete one item and its tests before moving on

| ID | Phase | Acceptance condition | Status | Evidence / next action |
|---|---|---|---|---|
| P0.1 | Build and tests | Re-run full Windows regression on the latest P0 source/workflow; **0 fail, 0 errors** and review skips | **PASS** | [run 44876022780](https://github.com/webbase-x/xstage/actions/runs/44876022780), commit `eb6bd7f92750483073bd592f0d38e923a4b3ad2d`: **1,040 tests, 0 failures, 0 errors, 78 skipped**; Windows build, installer, installed dependency smoke, and artifact upload all PASS; reviewed 78 skips |
| P0.2 | EXE and integrity | Native 64-bit BASS DLLs, icon, executable, SHA-256 and signed package manifest verified | **PASS** | [run 44877165196](https://github.com/webbase-x/xstage/actions/runs/44877165196), commit `6b33cedc2939e3f579b431f982df804e079ef30b`: 1,042 tests, 0 failures/errors, 78 skipped; package completeness + native x64 BASS + icon + SHA-256 PASS; signed Sigstore provenance [attestation 70463681](https://github.com/webbase-x/xstage/attestations/70463681) for setup EXE and release-manifest.json independently verified. **Not an Authenticode-signed production EXE.** |
| P0.3 | Real installer smoke | Silent install to Thai/space path; installed EXE dependency preflight; clean uninstall | **PASS** | [run 44877690650](https://github.com/webbase-x/xstage/actions/runs/44877690650), commit `3c8ee7a6781ab38ba91ff6fbf17a106c3117c1be`: silent install + installed dependency preflight + silent uninstall return code + no remaining installed files + CI user-Data sentinel preserved PASS, 1,042 tests / 0 fail / 0 error / 78 skipped. Signed attestation [70464622](https://github.com/webbase-x/xstage/attestations/70464622). |
| P0.4 | GUI & queue safety | Windows UI open/close, search, hotkeys, queue, mixer lifecycle and no stalling/flicker | IN PROGRESS | [run 44879046667](https://github.com/webbase-x/xstage/actions/runs/44879046667): 1,043 regression tests, 0 fail/error, 79 skipped; native Tk probe and first 4 GUI tests passed, then parent logger CP1252 UnicodeEncodeError halted suite. UTF-8 correction `5d9c533a94c595cd9a479290c0d66b5507916926`; [run 44879694855](https://github.com/webbase-x/xstage/actions/runs/44879694855) pending. Full GUI gate and display checks remain required. |
| P0.5 | Playback & live audio | Real Windows MIDI/NCN/EMK-legacy, SoundFont, MP3/video, transitions and ≥30-minute audio device soak | BLOCKED-HARDWARE | Requires actual Windows speakers/audio interface and playback observation |
| P0.6 | Data & release safety | Backup/restore, corrupted files, fail-closed deletes, recovery; no unintended stable publish | OPEN | Verify safe migrations and explicit stable gate |
| P1.1 | Multi-Out | Audio-bus graph and interfaces without breaking current stereo engine | NOT STARTED | |
| P1.2 | Multi-Out | Assign GM MIDI channels and drum keys to independent 4/8/16 output buses | NOT STARTED | |
| P1.3 | ASIO | Low-latency Windows ASIO backend with recoverable fallback | NOT STARTED | |
| P1.4 | Multi-Out QA | Multiple real interfaces, routing/latency/dropout and mixer verification | NOT STARTED | |
| P2.1 | Mixer | Bus meters, pan, gain, mute/solo and routing-preserving UI | NOT STARTED | |
| P2.2 | Dynamics | Measured per-song loudness compensation and a safe peak limiter | NOT STARTED | |
| P2.3 | Mixer QA | Presets, gain structure, latency and clipping tests | NOT STARTED | |
| P3.1 | Medley | Bounded next-song preload independent of UI frame rate | NOT STARTED | |
| P3.2 | Medley | Musical beat/bar-aligned fades and drum-fill handoff | NOT STARTED | |
| P3.3 | Medley QA | No unplanned dead air; unsupported-format fallback and cancellation tests | NOT STARTED | |
| P4.1 | VST3 | Optional isolated VST3 host with plugin-crash recovery | NOT STARTED | |
| P4.2 | Instruments | Per-instrument bank/program SoundFont + optional plugin mapping | NOT STARTED | |
| P4.3 | Drum map | Vendor-independent note maps and percussion preset tests | NOT STARTED | |
| P5.1 | Formats | Verify/extend playable formats using lawful reference specimens; no lock circumvention | NOT STARTED | |
| P5.2 | Video | Video/image/camera background and reliable display synchronization | NOT STARTED | |
| P5.3 | Video | Optional chromakey compositor and output QA | NOT STARTED | |
| P5.4 | Lyrics | Configurable 2/3/4-line synchronized sweep and monitor scaling | NOT STARTED | |
| P6.1 | Soak | 2+ hour Windows native playback, repeated app recovery and crash diagnostics | NOT STARTED | |
| P6.2 | Hardware | Audio devices, multi-monitor, MIDI input, Wi-Fi remote hardware matrix | NOT STARTED | |
| P6.3 | Release | Verified release/signing/update with rollback and stable acceptance | NOT STARTED | |
| P6.4 | Handoff | Operator docs, installer repair, published checksums and final acceptance report | NOT STARTED | |

**Current outstanding:** **24 of 27** checklist items, including **3 P0** gates. **P0.1, P0.2, P0.3 PASS; P0.4 is the next item.** Prior candidate test success provides evidence but **does not automatically close an item** on newer code/workflow.

## Rules for every hourly development iteration

1. Read current `main`, workflow runs, relevant code/tests and this file; avoid concurrent-work conflicts.
2. Select only the first unfinished acceptance ID within the current phase. Make the smallest safe code/test fix, or collect concrete missing evidence.
3. Run unit/regression checks and GitHub Actions on the exact source revision. If an error occurs, **fix and re-run**; do not mark PASS on source-only inspection.
4. On a blocking requirement (e.g. no real hardware or unavailable credentials), mark `BLOCKED-HARDWARE`/`BLOCKED-ACCESS`, document reproducible checks, and remain in the same phase. Never fabricate device QA.
5. Record dated commit SHA, CI run URL, tests run/passed/failed/errors/skipped, any artifacts, and exact remaining count. Do not mutate Release/installer availability flags without verified evidence.
6. Continue to the next task **only after the current task passes**; advance to P1 only when **all 6 P0 items pass**.

## 2026-11-21 13:14 Asia/Bangkok — P0.1 investigation\n\n- Windows [run 44872566462](https://github.com/webbase-x/xstage/actions/runs/44872566462) passed source inspection, Windows regression, native x64 BASS validation, icon verification and installer compilation; **failed** in silent installation smoke because the expected installed `XStageKaraoke.exe` was not found in the requested Thai/space path. Installer SHA-256: `e6bf9eabb012e59ce0cfee13a90b243035a20e5d33d69080b9d4563176a011be`. This SHA belongs to a failed candidate and must not be advertised as a release.\n- Workflow change `deb9e859b05c8d6a1ffcefaa0e503f69ca5aa2c7` makes `/DIR` and `/LOG` explicit single-string arguments and prints install directory contents plus Inno log on failure. This is a **diagnostic/fix candidate**, not proof of success.\n- **P0.1 remains OPEN** until rerun of complete Windows CI and installer smoke succeeds; **27/27 remain**. No physical hardware or production EXE verification.\n\n## 2026-11-21 13:36 Asia/Bangkok — P0.1 accepted; next P0.2

- **Root cause fixed:** Inno Setup's AppExe is `X-StageKaraoke.exe` while PyInstaller's input is `XStageKaraoke.exe`. The Windows installer smoke was checking the wrong installed filename. Workflow correction: commit [eb6bd7f9](https://github.com/webbase-x/xstage/commit/eb6bd7f92750483073bd592f0d38e923a4b3ad2d).
- **Exact Windows CI:** [run 44876022780](https://github.com/webbase-x/xstage/actions/runs/44876022780) **SUCCESS**. Full regression 1,040 tests; **0 failed, 0 errors, 78 skipped**, 119.401 seconds; release manifest and bundled BASS x64 validation PASS; Inno Setup installer compiled; silent install to a Thai/space-containing path and installed EXE native dependency preflight PASS; candidate artifact upload PASS.
- **78 skips reviewed:** 54 retired v0.9.41 behavior tests (replacement suites exist), 20 display-required GUI tests, 4 platform/opt-in native checks. These do not count as Windows physical device or live GUI certification.
- **Candidate-only installer SHA-256:** `f656c91e7d5387188b8f38aa692b39f8e647d0b623099d1d35982178ae490fa9`; Actions artifact ID `14696072242`. Do **not** publish as a signed/stable release without P0.2–P0.6 evidence.
- **Decision:** **P0.1 PASS**. Remaining **26/27 total, 5/6 in P0**. Next P0.2 is separate acceptance for native runtime/icon/hash/signature manifest; P0.3 still requires explicit uninstall cleanup evidence. P0.5 requires real audio hardware.

## 2026-11-21 13:52 Asia/Bangkok — P0.2 passed; next P0.3

- **Changed:** `tools/verify_release.py` now rejects extra/unlisted package payloads and checks nested manifest names; 2 new manifest tampering regression tests in `tests/test_stability061.py`. `build.ps1` removes test-generated `__pycache__` from *dist build staging only* before hashing, without touching Data or song directories. `.github/workflows/build-windows-pc.yml` uses GitHub Sigstore keyless signing (actions/attest@v4) and verifies provenance for both the candidate Installer and the SHA-256 release manifest.
- **Initial CI caught a real packaging issue:** [run 44876722020](https://github.com/webbase-x/xstage/actions/runs/44876722020) was FAIL because generated `karaoke/__pycache__/*.pyc` was present in dist but unlisted by the manifest. Fixed via commit `6b33cedc2939e3f579b431f982df804e079ef30b`.
- **Exact validated CI:** [run 44877165196](https://github.com/webbase-x/xstage/actions/runs/44877165196) **SUCCESS**, 1,042 tests / 0 fail / 0 error / 78 skipped. BASS DLL x64, icon, EXE, release-manifest integrity, installer compilation, installation smoke and installed runtime dependencies all PASS.
- **Cryptographic evidence:** [Sigstore attestation 70463681](https://github.com/webbase-x/xstage/attestations/70463681) signs build provenance for two separate subjects (installer EXE and internal `release-manifest.json`), recorded on Rekor and validated using `gh attestation verify` bound to this repository/workflow. Candidate installer SHA-256 `2e941761692eeaef6acca54058531c0f38e78114be785b76dcc3b99c290a30a2`. Actions artifact ID `14697051076`.
- **Scope:** Sigstore supply-chain signature is NOT a Windows Authenticode code-signing certificate; real hardware/long playback and full installer uninstall-cleanup acceptance remain unverified. Do not mark Stable or publish a production update based on P0.2 alone.
- **Decision:** **P0.2 PASS**. Remaining **25/27 total, 4/6 P0**. Next item **P0.3** must check clean uninstall, residue handling and installed app preflight without impacting existing Data.

## 2026-11-21 13:59 Asia/Bangkok — P0.3 accepted; next P0.4

- **Changed:** Windows candidate workflow now requires silent uninstall success with exit code 0, verifies no installed files remain in the Thai/space test path, and asserts a run-unique sentinel under the test account's user Data directory is intact after uninstall. Only its own CI marker is removed; other user Data and song files are never touched. Commit [3c8ee7a6](https://github.com/webbase-x/xstage/commit/3c8ee7a6781ab38ba91ff6fbf17a106c3117c1be).
- **Windows run evidence:** [run 44877690650](https://github.com/webbase-x/xstage/actions/runs/44877690650) SUCCESS; **1,042 tests / 0 fail / 0 error / 78 skipped**; installer build + native x64 audio checks + installation with Thai/space path + deployed runtime preflight + clean uninstall all PASS. Explicit log: `Silent uninstall verified: no installed files remain; user Data preserved`.
- **Signed candidate integrity:** [Sigstore attestation 70464622](https://github.com/webbase-x/xstage/attestations/70464622), signed for 2 subjects and verified with GitHub CLI. Installer SHA-256: `e63c5557a009145d8f6953b940feccc2acc1dcaddb74710a67d233e02f1fc5d7`. GitHub artifact ID: `14696319033`.
- **Scope:** This is GitHub-hosted Windows CI acceptance for an unsigned candidate, NOT native external hardware or production Authenticode certificate validation. P0.4 GUI/hotkeys/queue, P0.5 real-audio soak and P0.6 data/release gates remain open.
- **Decision:** **P0.3 PASS**. Remaining **24/27 total, 3/6 P0**. Next **P0.4**.

## 2026-11-21 — P0.4 native GUI gate initiated

- Reviewed 20 GUI-related skips from [run 44877690650](https://github.com/webbase-x/xstage/actions/runs/44877690650). Existing test decorators require DISPLAY, which was never set by the Windows CI. Do not infer UI coverage from the headless regression.
- Added a genuine Tk search→queue→mixer lifecycle test in `tests/test_quality090.py` (commit `4e49555e290a3272ff095c5c78d57df75d91e5e8`). It uses a temporary song/index and mocks only the decision to start audio, not the Tk widgets. Checks search results, queue selection, F9/F10 bindings, window mapping, repeated mixer open/close and event-loop responsiveness.
- CI now verifies the native Win32 Tk window can map before explicitly enabling GUI tests; each selected GUI test runs in its own subprocess with timeout and unexpected skips rejected. Workflow commits `50559392b9ccc14e8e857aa4a9779ec68a9bd4de` and `6b7cf321137ddcc5521160ffac4fd16145a0f840`. The legacy scan/delete scenario is explicitly retired; the separate older ImportGuiTests are not covered by this gate (review their current behavior before making broad UI coverage claims).
- **Verification pending:** [run 44879046667](https://github.com/webbase-x/xstage/actions/runs/44879046667) on source commit `6b7cf321137ddcc5521160ffac4fd16145a0f840`. Inspect GUI failures/timeouts, fix and rerun. A native event-loop probe is not proof of physical display flicker or real audio hardware operation.
- **Decision:** P0.4 IN PROGRESS; remaining **24/27 total; 3/6 P0**. Do not advance to P0.5 until P0.4 criteria are established.

## 2026-11-21 — P0.4 GUI runner UTF-8 correction

- [Run 44879046667](https://github.com/webbase-x/xstage/actions/runs/44879046667): full regression **1,043 tests / 0 failures / 0 errors / 79 skipped**; native Win32 Tk probe succeeded; first four isolated GUI cases succeeded. During the fifth case, parent Python logger crashed at `print(proc.stdout)` with CP1252 `UnicodeEncodeError` when printing Thai characters. The fifth case and subsequent cases were not established as passed.
- Corrected parent Python STDOUT/STDERR, child process environment and PowerShell encoding to UTF-8; preserved partial timeout logs. Commit `5d9c533a94c595cd9a479290c0d66b5507916926`. No tests were removed, no failure conditions weakened.
- [New run 44879694855](https://github.com/webbase-x/xstage/actions/runs/44879694855) must complete. **P0.4 IN PROGRESS, 24/27 outstanding, 3/6 P0 gates still outstanding.** No physical display/audio hardware acceptance claimed.

## Hourly report format

- **Working on:** `P?.?` + one-line objective
- **Changed:** exact file paths, Git commit SHA and/or CI run
- **Verification:** tests X, failed Y, errors Z, skipped S; Windows hardware checked / not checked
- **Decision:** PASS / FAIL / BLOCKED
- **Remaining:** P0 6−accepted, total 27−accepted (explicitly show count)
- **Next:** stay on same item if not PASS; otherwise first remaining item in phase
