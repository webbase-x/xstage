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
| P0.4 | GUI & queue safety | Windows UI open/close, search, hotkeys, queue, mixer lifecycle and no stalling/flicker | DEFERRED-HARDWARE | [run 44879694855](https://github.com/webbase-x/xstage/actions/runs/44879694855): Windows build, required isolated Tk GUI regression, installer smoke and provenance steps SUCCESS. Physical display flicker/responsiveness remain unverified; user approved deferral. |
| P0.5 | Playback & live audio | Real Windows MIDI/NCN/EMK-legacy, SoundFont, MP3/video, transitions and ≥30-minute audio device soak | IN PROGRESS | P0.5.1 source audit: `karaoke/bass.py` constructor, offline song reset, close; `karaoke/audio_device.py` reference-counted acquire/release. Added guarded BASS cleanup `5e6de970` and injected FX teardown regression `ffe512b0`; Added initialization-error preservation `ec3548bd` and regression `dca3c5df`; Multi-channel EQ teardown fix `80a509d5` and regression `5a2b08e2` added; Windows CI verification pending; physical audio remains BLOCKED-HARDWARE. |
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

**Current outstanding:** **24 of 27** checklist items, including **3 P0** gates. **P0.1, P0.2, P0.3 PASS; P0.4 deferred by user; P0.5 active.** Prior candidate test success provides evidence but **does not automatically close an item** on newer code/workflow.

## Rules for every hourly development iteration

1. Read current `main`, workflow runs, relevant code/tests and this file; avoid concurrent-work conflicts.
2. Select only the first unfinished acceptance ID within the current phase, except the explicitly authorized P0.4 deferral to P0.5. Make the smallest safe code/test fix, or collect concrete missing evidence.
3. Run unit/regression checks and GitHub Actions on the exact source revision. If an error occurs, **fix and re-run**; do not mark PASS on source-only inspection.
4. On a blocking requirement (e.g. no real hardware or unavailable credentials), mark `BLOCKED-HARDWARE`/`BLOCKED-ACCESS`, document reproducible checks, and remain in the same phase. Never fabricate device QA.
5. Record dated commit SHA, CI run URL, tests run/passed/failed/errors/skipped, any artifacts, and exact remaining count. Do not mutate Release/installer availability flags without verified evidence.
6. Continue to the next task **only after the current task passes**, except the explicitly authorized P0.4 deferral to P0.5; advance to P1 only when **all 6 P0 items pass**.

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

## 2026-11-21 — User-authorized P0.4 deferral / P0.5 active

- Audited main `71d0dbda9c3942299cfab36e0d055344b59551c3`; [run 44879694855](https://github.com/webbase-x/xstage/actions/runs/44879694855) job steps confirm full regression, isolated native Tk GUI regression, installer smoke and provenance success. Earlier reported regression count: 1,043 / 0 failures / 0 errors / 79 skipped; count not independently re-read from logs in this audit.
- P0.4 remains NOT PASS. User explicitly authorized moving to P0.5 and combining physical Windows checks later. All P0 gates must pass before P1.
- P0.5 work order: MIDI/BASSMIDI lifecycle; SoundFont and memory; MIDI/NCN/EMK-legacy/MP3/video; next-song preload; transition/dead-air checks; >=30 minute physical audio soak. Reuse existing implementations/tests; no claim of physical audio or display acceptance.
- Remaining 24/27 total, 3/6 P0. No application code or Download Manager changes in this decision commit.

## 2026-11-21 — P0.5.1 BASSMIDI lifecycle source audit

- Reviewed current `karaoke/bass.py` and `karaoke/audio_device.py` on main `17e5a24dd708c5b2d9c5a80a6cb9ce9160bb8a73`. Existing implementation has reference-counted device acquire/release, stream/font teardown, offline song stream replacement and channel EQ cleanup. Do not duplicate these features.
- Potential failure-path gap for targeted tests: `BassSynth.close()` calls `_release_channel_eq()` before freeing stream/fonts/device; an exception during processor teardown can interrupt later cleanup. Verify with injected failure tests and implement guarded cleanup only if reproduced; preserve original error reporting.
- No new Windows regression/CI or physical audio run this audit; **P0.5.1 NOT PASS**. P0.4 deferred, P0.5 IN PROGRESS, 24/27 remain; next action is reproducible failure-path tests and minimal fix, then full Windows CI.

## 2026-11-21 — P0.5.1 FX failure cleanup fix

- Code commit [`5e6de970`](https://github.com/webbase-x/xstage/commit/5e6de97079c30f824921090e7ee9b63eb5f7828e): `karaoke/bass.py` now attempts all cleanup stages after an EQ processor raises, preserving the first exception. Test commit [`ffe512b0`](https://github.com/webbase-x/xstage/commit/ffe512b09b784efc98bef9cf0905bebb7ee2668e): injected failing EQ close verifies stream/font/device/DLL cleanup and idempotent repeat close.
- Regression/Windows Actions result **PENDING**, no test count or hardware pass claimed. P0.5.1 remains IN PROGRESS; 24/27 outstanding.

## 2026-11-21 — P0.5.1 additional teardown failure regression

- Added injected stream-free and SoundFont-free failures to `tests/test_midi_channel_eq.py` in [`27a2baaf`](https://github.com/webbase-x/xstage/commit/27a2baafa11734d87602e8ffc07855e4f585903b); refined explicit assertion in [`74bf795a`](https://github.com/webbase-x/xstage/commit/74bf795a4816b2b777cc771e8241b67cb5235299). Test expects first stream error, attempts both font releases, releases device and clears DLL directory.
- GitHub commit workflow lookup returned no runs for `74bf795a`; **Windows CI NOT VERIFIED**, full regression count unavailable, physical audio not tested. P0.5.1 remains IN PROGRESS; P0.4 deferred; 24/27 outstanding.
- Next: execute relevant unit test and complete Windows CI on exact commit, fix any failures before marking PASS or proceeding to SoundFont memory work.

## 2026-11-21 — P0.5.1 preserve native initialization root cause

- `karaoke/bass.py` [`ec3548bd`](https://github.com/webbase-x/xstage/commit/ec3548bd1523eed126b94f94d55e261272b3017a): initialization failure now retains its original exception if best-effort `close()` also raises.
- `tests/test_soundfont.py` [`dca3c5df`](https://github.com/webbase-x/xstage/commit/dca3c5df717887f3eba5b6892d5257f092d71f8b): injected SoundFont stream configuration failure plus stream cleanup exception; assert original error and remaining font/device release.
- **Not yet tested:** no executable local checkout/Windows runner in this interaction; the GitHub connector workflow lookup is PR-filtered and cannot establish push CI results. Do not claim regression PASS. P0.5.1 IN PROGRESS, 24/27 outstanding.

## 2026-11-21 — P0.5.1 multi-channel FX teardown

- [`80a509d5`](https://github.com/webbase-x/xstage/commit/80a509d5ed7a04d2045d2c72b42d975d8e2fab56) changes `_release_channel_eq()` to attempt cleanup of all MIDI channel processors after the first failure, then re-raise the first error. [`5a2b08e2`](https://github.com/webbase-x/xstage/commit/5a2b08e29e1b78d3eafc7c712418050a6125d34d) adds a two-channel failure regression asserting both channels and master stream free.
- **No test execution verified:** container cannot resolve github.com for a checkout, and available GitHub connector has no workflow dispatch/list-push-runs action. Do not mark PASS based only on committed tests. P0.5.1 IN PROGRESS, 24/27 outstanding.

## 2026-11-21 — P0.5 SoundFont long-batch handle regression

- [`d5c5e1dd`](https://github.com/webbase-x/xstage/commit/d5c5e1ddbe77c7fbc56afecb3683518e3c5f5709) adds a 100-song offline batch mock regression in `tests/test_soundfont.py`: one SoundFont initialization, 101 MIDI streams, 100 stream frees during transitions, final stream/font/device free at shutdown.
- This is a resource-handle lifecycle assertion, **not** a Windows RAM measurement or 30-minute live-audio soak. Test execution and CI remain unverified; P0.5 IN PROGRESS, P0.4 deferred, 24/27 outstanding.

## 2026-11-21 — P0.5 medley preload partial-build teardown

- [`092168ec`](https://github.com/webbase-x/xstage/commit/092168ec4619a66710b63451a6da3dd8c686e59e) makes `medley_decks.build()` release both rhythm and main decks on failure even when one close raises, preserving original setup exception.
- [`628f697a`](https://github.com/webbase-x/xstage/commit/628f697a63d15eb33e3d07c0be90ec00ede054c9) adds injected failure regression to `tests/test_full_song_medley.py`.
- Source and tests committed; **test execution, Windows CI and real-time gapless audio remain unverified**. P0.5 IN PROGRESS; 24/27 remaining. Next validate tests on Windows, then measure preload/transition gap and 30-minute audio soak.

## 2026-11-21 — P0.5 discard completed preloaded decks safely

- [`bacf1c03`](https://github.com/webbase-x/xstage/commit/bacf1c036a5941550858eaa9e9cdec85fdd39dfc) changes `Decks.discard()` callback to attempt closure of both completed preload players even if one close raises. [`f51fd58f`](https://github.com/webbase-x/xstage/commit/f51fd58f1f71e59bf28c0e4a3fd886117d33718d) adds deterministic `Future`-based regression.
- Source and tests committed, **not yet executed**. Windows CI and measured no-gap audio transitions remain pending. P0.5 IN PROGRESS; 24/27 outstanding.

## 2026-11-21 — P0.5 medley tail teardown and executor shutdown

- [`41a30a74`](https://github.com/webbase-x/xstage/commit/41a30a7418f01ce23426bbd7c47bc2a8f75d43e4) updates `Decks.stop_tail()` to attempt drum channel restoration and close both tail/rhythm players, preserving first cleanup error. `Decks.close()` always shuts down preload executor via `finally`.
- [`0cd3e64e`](https://github.com/webbase-x/xstage/commit/0cd3e64e708fd4b08975b96161089c5195b96204) adds tests for both-player teardown and executor shutdown after injected failures.
- **Committed but not executed in Windows CI**. P0.5 IN PROGRESS, 24/27 outstanding; actual seamless playback and hardware tests not yet verified.
