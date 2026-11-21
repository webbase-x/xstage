# X-Stage Karaoke PC — Professional Live Roadmap (P0–P6)

**Project:** `webbase-x/xstage` — keep the existing `windows-pc/source/` application and user data.  
**Last audited:** 2026-11-21 (Asia/Bangkok).  
**Current phase:** **P0.6 development (P0.4/P0.5 verification deferred; not accepted).**  
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

## Acceptance checklist — implement in sequence; defer unavailable test results without claiming PASS

| ID | Phase | Acceptance condition | Status | Evidence / next action |
|---|---|---|---|---|
| P0.1 | Build and tests | Re-run full Windows regression on the latest P0 source/workflow; **0 fail, 0 errors** and review skips | **PASS** | [run 44876022780](https://github.com/webbase-x/xstage/actions/runs/44876022780), commit `eb6bd7f92750483073bd592f0d38e923a4b3ad2d`: **1,040 tests, 0 failures, 0 errors, 78 skipped**; Windows build, installer, installed dependency smoke, and artifact upload all PASS; reviewed 78 skips |
| P0.2 | EXE and integrity | Native 64-bit BASS DLLs, icon, executable, SHA-256 and signed package manifest verified | **PASS** | [run 44877165196](https://github.com/webbase-x/xstage/actions/runs/44877165196), commit `6b33cedc2939e3f579b431f982df804e079ef30b`: 1,042 tests, 0 failures/errors, 78 skipped; package completeness + native x64 BASS + icon + SHA-256 PASS; signed Sigstore provenance [attestation 70463681](https://github.com/webbase-x/xstage/attestations/70463681) for setup EXE and release-manifest.json independently verified. **Not an Authenticode-signed production EXE.** |
| P0.3 | Real installer smoke | Silent install to Thai/space path; installed EXE dependency preflight; clean uninstall | **PASS** | [run 44877690650](https://github.com/webbase-x/xstage/actions/runs/44877690650), commit `3c8ee7a6781ab38ba91ff6fbf17a106c3117c1be`: silent install + installed dependency preflight + silent uninstall return code + no remaining installed files + CI user-Data sentinel preserved PASS, 1,042 tests / 0 fail / 0 error / 78 skipped. Signed attestation [70464622](https://github.com/webbase-x/xstage/attestations/70464622). |
| P0.4 | GUI & queue safety | Windows UI open/close, search, hotkeys, queue, mixer lifecycle and no stalling/flicker | DEFERRED-HARDWARE | [run 44879694855](https://github.com/webbase-x/xstage/actions/runs/44879694855): Windows build, required isolated Tk GUI regression, installer smoke and provenance steps SUCCESS. Physical display flicker/responsiveness remain unverified; user approved deferral. |
| P0.5 | Playback & live audio | Real Windows MIDI/NCN/EMK-legacy, SoundFont, MP3/video, transitions and ≥30-minute audio device soak | PENDING-QA / DEFERRED-HARDWARE | P0.5.1 source audit: `karaoke/bass.py` constructor, offline song reset, close; `karaoke/audio_device.py` reference-counted acquire/release. Added guarded BASS cleanup `5e6de970` and injected FX teardown regression `ffe512b0`; Added initialization-error preservation `ec3548bd` and regression `dca3c5df`; Multi-channel EQ teardown fix `80a509d5` and regression `5a2b08e2` added; Windows CI verification pending; physical audio remains BLOCKED-HARDWARE. |
| P0.6 | Data & release safety | Backup/restore, corrupted files, fail-closed deletes, recovery; no unintended stable publish | IN PROGRESS | Verify safe migrations and explicit stable gate |
| P1.1 | Multi-Out | Audio-bus graph and interfaces without breaking current stereo engine | CODE EXISTS / PENDING-QA | |
| P1.2 | Multi-Out | Assign GM MIDI channels and drum keys to independent 4/8/16 output buses | CODE EXISTS / PENDING-QA | |
| P1.3 | ASIO | Low-latency Windows ASIO backend with recoverable fallback | CODE EXISTS / PENDING-QA | |
| P1.4 | Multi-Out QA | Multiple real interfaces, routing/latency/dropout and mixer verification | NOT STARTED | |
| P2.1 | Mixer | Bus meters, pan, gain, mute/solo and routing-preserving UI | NOT STARTED | |
| P2.2 | Dynamics | Measured per-song loudness compensation and a safe peak limiter | PARTIAL / PENDING-QA | |
| P2.3 | Mixer QA | Presets, gain structure, latency and clipping tests | NOT STARTED | |
| P3.1 | Medley | Bounded next-song preload independent of UI frame rate | CODE EXISTS / PENDING-QA | |
| P3.2 | Medley | Musical beat/bar-aligned fades and drum-fill handoff | CODE EXISTS / PENDING-QA | |
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
2. Implement the first unfinished engineering task, preserving existing code and user data. A test-only blocker must not stop implementation of the next independent task.
3. Add automated regression coverage and request/check CI when available. If test execution or results are unavailable, record `PENDING-QA` with exact commit and intended tests, then **continue to the next engineering task without waiting**. When results become available, report PASS/FAIL and repair failures; never silently upgrade to PASS.
4. For physical Windows devices, long audio soaks or unavailable credentials, record `DEFERRED-HARDWARE`/`BLOCKED-ACCESS` and continue non-hardware work. Do not fabricate QA.
5. Record dated commit SHA, available CI run URL and observed test counts. Never mark a test PASS from code inspection; never alter stable release/installer availability without verified evidence.
6. Continue P0.6 and subsequent engineering phases even while P0.4/P0.5 QA remains pending. Stable release and final acceptance **remain blocked** until mandatory gates actually pass.

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

## 2026-11-21 — P0.5 optional drum fill isolation

- [`b5396f8c`](https://github.com/webbase-x/xstage/commit/b5396f8c1eb7a57a8d28529a3c3cd987b41d0710) prevents an optional drum-fill close error from aborting a successfully prepared main song; [`ed2f9087`](https://github.com/webbase-x/xstage/commit/ed2f9087f9f7b371eca47957a4a004e7e2256e7f) adds a mocked seek-and-close failure regression.
- Tests committed but not executed in Windows CI. No verified gapless playback or hardware evidence yet. P0.5 IN PROGRESS, 24/27 outstanding.

## 2026-11-21 — P0.5 crossfade fallback and user-authorized hardware deferral

- User explicitly requests implementing all P0.5 source work now and deferring **all real-device, real-EXE, real-audio, and physical soak tests**. Record those checks as DEFERRED-HARDWARE; do not represent them as PASS or hold up source development. Automated source/CI checks remain desirable but do not certify hardware behavior.
- [`3c8aae08`](https://github.com/webbase-x/xstage/commit/3c8aae08aed34b4b14c0154fc4e5f9d2b0c5592c) prevents requested crossfade from fading the outgoing song to silence when the next deck is still loading; ordinary queue advance remains the fallback at the trigger.
- P0.5 source work remains IN PROGRESS: MIDI/NCN/EMK legacy and video path review, transition instrumentation and remaining fault handling not yet closed. No physical gapless/30-minute soak evidence; 24/27 checklist gates remain pending.

## 2026-11-21 — P0.5 MP3/WAV BASS FX failure cleanup

- [`a622995a`](https://github.com/webbase-x/xstage/commit/a622995aea4c204058b5d1772c340ff8cfb35d09) makes `PcmPlayer.close()` best-effort across router, stream, device and DLL directory, preserving the first exception and the original constructor exception on initialization failure.
- [`4bbf7cce`](https://github.com/webbase-x/xstage/commit/4bbf7cce5ab8823a5b204e18c5cce1ecc47cd9ef) adds router/stream teardown regression cases. These are source-only changes, **test execution not verified**.
- P0.5 remains **IN PROGRESS**, not PASS: media format path coverage (MIDI/NCN/EMK-legacy/video), transition edge cases, and automated CI evidence still need work. Physical Windows playback and 30-minute soak are **DEFERRED-HARDWARE at user request**. Do not claim fully implemented or certified.

## 2026-11-21 — P0.5 failed tail close isolation

- [`6f9927b7`](https://github.com/webbase-x/xstage/commit/6f9927b7eaf16b605a67621da14d7dfad73feb3a) detaches the finished tail before native close and prevents teardown exceptions from interrupting the active next song; logs `tail_cleanup_failed` best effort. [`ec86e7e7`](https://github.com/webbase-x/xstage/commit/ec86e7e733e2d61f4b37727ccef9f29e3e564e02) adds a regression for no repeated close on later ticks.
- Test not executed; hardware QA deferred at user request. P0.5 still IN PROGRESS; do not claim all file formats certified.

## 2026-11-21 16:09 Asia/Bangkok — P0.5 regression validity and rhythm ownership

- Main baseline `b641e4d2d55c3fb0d070376eeee91f2dd676d7db` reviewed before editing.
- [`8fcb9bd2`](https://github.com/webbase-x/xstage/commit/8fcb9bd2180464539891ed6830cc1102b9cc8115) corrects two preload regression tests: `MidiPlayer` patch must remain a type for `isinstance`, and rhythm song must expose real iterable MIDI events. Previously committed tests could fail with TypeError before reaching their intended failure branch.
- [`2f0124cc`](https://github.com/webbase-x/xstage/commit/2f0124ccbdc6ffb311be9aaf838ca3c64bb91601) fixes rhythm-deck ownership when full-song fill and crossfade pattern are both requested; release superseded fill before replacing it, avoiding leaked native stream.
- No test execution or Windows CI result available for these commits; physical playback and >=30-minute soak explicitly **DEFERRED-HARDWARE**, not PASS. P0.5 **IN PROGRESS**; 24/27 checklist items outstanding. Next: check MIDI/NCN/EMK/video loaders, transitions and CI, then P0.6 only after P0.5 acceptance.

## 2026-11-21 — P0.5 secondary medley fallback errors

- [`0d181a7a`](https://github.com/webbase-x/xstage/commit/0d181a7a63eb6edfd7580605c3faa0a4b4d637b1) isolates cleanup failure when replacing an optional preloaded fill with a crossfade rhythm deck.
- [`839b9123`](https://github.com/webbase-x/xstage/commit/839b912373bd32cf46aea5dce5f452502d5acc3d) prevents a second exception from `pause()` from breaking the optional fill failure fallback.
- These commits are **not validated by test execution**. P0.5 remains IN PROGRESS; real hardware and soak testing DEFERRED at user request. Do not assert completion or release readiness.

## 2026-11-21 — P0.5 auxiliary deck runtime fault isolation

- [`a8a388d3`](https://github.com/webbase-x/xstage/commit/a8a388d3586df08d68adb92157e020b85b30ba35) isolates play/pause/pump failures on auxiliary tail/rhythm decks, closes the affected deck best-effort, and restores drum channel 9 when rhythm fails. [`26c0d7ab`](https://github.com/webbase-x/xstage/commit/26c0d7ab3f2d20dbd0f3ec45c014887f92cf7225) adds a mocked rhythm failure regression.
- Source and test committed; test execution not verified. P0.5 remains IN PROGRESS; real hardware checks DEFERRED at user request.

## 2026-11-21 — P0.5 rhythm volume/tempo fault isolation and verification limitation

- [`f45f3078`](https://github.com/webbase-x/xstage/commit/f45f3078661d6015d509b098edc26ee65072bd06) guards rhythm tempo/gain adjustment; on failure, closes only the auxiliary rhythm and restores the main MIDI drum channel. [`8738dcf3`](https://github.com/webbase-x/xstage/commit/8738dcf31677cfdd61a42a98223d5d6d1052bfd4) adds a volume-failure regression.
- **Verification blocked:** local checkout is unavailable because github.com DNS resolution fails; available GitHub connector cannot trigger a fresh workflow run on the new main commit. Consequently neither these regression tests nor full Windows CI have been executed/verified for this revision. No PASS claim. Physical machine and live-audio soak explicitly DEFERRED by user.
- **P0.5 remains IN PROGRESS**, pending automated test execution and comprehensive MIDI/NCN/EMK-legacy/video route verification. Do not publish a stable EXE on this evidence.

## 2026-11-21 — P0.5 outgoing crossfade gain failure

- [`06beb6fd`](https://github.com/webbase-x/xstage/commit/06beb6fd8ec55446621404f46ca73d7563617f17) restores incoming song volume to base when outgoing tail gain adjustment fails, detaching and closing the tail best-effort. [`f56b79f3`](https://github.com/webbase-x/xstage/commit/f56b79f36cafe9d9ecab8e612fa1f46e92e9e2de) adds a regression test.
- Automated test execution is still unverified. P0.5 IN PROGRESS; actual Windows device playback/30-minute soak DEFERRED-HARDWARE.

## 2026-11-21 — P0.5 outgoing deck pump failure recovery

- [`2020cc42`](https://github.com/webbase-x/xstage/commit/2020cc424dc54c10f880c1960a182146696b2036) restores incoming deck volume to base after outgoing tail play/pause/pump failure, avoiding silent incoming audio at the beginning of crossfade. [`bc2fd625`](https://github.com/webbase-x/xstage/commit/bc2fd625cf7c91f008abdcbe28b4377d40d27aa7) adds a regression test.
- Changes committed but automated tests not executed in this session; P0.5 IN PROGRESS. Hardware playback and soak checks remain DEFERRED-HARDWARE.

## 2026-11-21 — P0.5 preload resource ownership and optional-fill isolation

- [`928d710f`](https://github.com/webbase-x/xstage/commit/928d710fbadf59a36b7441a3f3dad6ce299576ad), [`4044cf5d`](https://github.com/webbase-x/xstage/commit/4044cf5d944899073568c38efe4f689cfffb42c3): MIDI preload and auxiliary rhythm constructors now release the BASS synth if MidiPlayer construction raises; regression [`09834552`](https://github.com/webbase-x/xstage/commit/09834552f9da47e580024f64a7dadbcf2fc16ff9).
- [`bdeebc3c`](https://github.com/webbase-x/xstage/commit/bdeebc3c109e770c6bfa9dc50ea3f3be3ae3ac8d): optional drum-fill analysis/inspection failures no longer abort next-song preload; regression [`3738bf13`](https://github.com/webbase-x/xstage/commit/3738bf13c85a47e9e79893554b69dbf451f40ecd).
- **Gate status: IN PROGRESS, NOT PASS.** No successful automated test run on these commits has been observed; local git checkout cannot reach github.com (DNS). MIDI/NCN/EMK-legacy/video coverage still requires independent verification. User explicitly deferred real-machine and audio soak tests; those remain DEFERRED-HARDWARE, not PASS. Do not advance P0.6 or publish stable on unverified evidence.

## 2026-11-21 — User-authorized nonblocking QA policy

- User explicitly authorized continuing to subsequent engineering tasks whenever test results are pending, reporting the actual results later and fixing failures then. This supersedes the previous stop-on-every-gate sequencing rule **for development only**.
- P0.4 physical GUI and P0.5 physical audio remain DEFERRED-HARDWARE; P0.5 latest automated tests PENDING-QA. Neither is PASS.
- Start P0.6 now. Preserve release safety: no stable EXE claim or release flag until required tests pass. Track outstanding verification as technical debt and revisit on CI results.

## 2026-11-21 — P0.6 restore safety implementation (QA pending)

- [`a78e1653`](https://github.com/webbase-x/xstage/commit/a78e16534c7cb822a8ca2abbabdd9d661873e7fd) rejects symlink/junction inputs among required and optional restore backup files before reading or staging; [`b357de45`](https://github.com/webbase-x/xstage/commit/b357de4576ba127aee2aeb3e95a82d6d5a185770) adds regression that external symlink content cannot be restored and current data stays intact.
- Automated test result **PENDING-QA** (not PASS). Continue P0.6 data/release-safety work while waiting; revisit exact commits when CI evidence is available. Physical tests remain DEFERRED-HARDWARE. Do not advertise a stable EXE.

## 2026-11-21 — P0.6 interrupted restore journal hardening (PENDING-QA)

- [`475ddb7f`](https://github.com/webbase-x/xstage/commit/475ddb7f38779d88e019c54e57fb3e9218856c3f) validates interrupted restore safety-folder name, symlink/junction state, rollback target allowlist and backup file existence before rollback mutates user data.
- [`2e51ebe7`](https://github.com/webbase-x/xstage/commit/2e51ebe78ea823db0d8c7a59515dce536c7cf1a5) additionally rejects non-string and duplicate journal entries before set operations. Regression tests [`e7477058`](https://github.com/webbase-x/xstage/commit/e74770581c9e973edd26295e2655417d52e6367f), [`88dfc640`](https://github.com/webbase-x/xstage/commit/88dfc640308626721112e8811e15effe7e865f17).
- Source commits recorded; automated CI execution/results still PENDING-QA, not PASS. Continue independent engineering tasks under user-authorized nonblocking QA; do not release Stable before required gates pass.

## 2026-11-21 — P0.6 interrupted copy cleanup (PENDING-QA)

- [`b4f28564`](https://github.com/webbase-x/xstage/commit/b4f2856403ac6e28a1823f7a7658d357fb26c4b0) cleans up the `.restore-tmp` file if restore copy/rename raises, preserving the original exception and not replacing the destination with a partial copy. [`5b6a4157`](https://github.com/webbase-x/xstage/commit/5b6a41575a2cec1328674ca40e9c48bbfd231c2b) adds a simulated disk-full regression.
- Test execution remains PENDING-QA, not PASS; user authorized continuing other engineering work without waiting for results. Hardware tests remain deferred and stable release blocked.

## 2026-11-21 — P0.6 linked pending directory / live data guard (PENDING-QA)

- [`83dff647`](https://github.com/webbase-x/xstage/commit/83dff647eddc2c0d0f3cf7c8c3c16cd0903c9196) refuses symlink/junction `restore-pending` at staging/startup, and refuses linked/non-file current-data inputs before snapshotting for rollback. Regression [`318994e0`](https://github.com/webbase-x/xstage/commit/318994e0c0cef1860185a15ec4d5dbe15bd9f9c2) checks external targets remain unchanged.
- CI execution not verified yet: **PENDING-QA, not PASS**. Continue implementation on independent tasks under user-approved nonblocking policy. Physical QA deferred; stable release still blocked.

## 2026-11-21 — P0.6 safety snapshot failure cleanup (PENDING-QA)

- [`ed452c80`](https://github.com/webbase-x/xstage/commit/ed452c80a0c4979f5c8d44f1e13cf4e21a171d5c) validates all live backup inputs before creating safety directory; if snapshot fails, removes partial safety folder before any live-file replacement or applying-journal write.
- Regression [`1dfddb36`](https://github.com/webbase-x/xstage/commit/1dfddb363a83925dc75f45c8e89bbe6b8a08ba35) injects snapshot disk-full failure and asserts live song database unchanged, no orphan safety folder and pending restore retained.
- Automated results **PENDING-QA**. Development may continue, but P0.6 is not PASS and Stable remains blocked.

## 2026-11-21 — P0.6 applying journal persistence failure (PENDING-QA)

- [`6a05bd02`](https://github.com/webbase-x/xstage/commit/6a05bd02a9057433ee50a0dcc98f510bef30b04c) removes unused restore-safety snapshot if persisting the applying journal fails before live-file replacement. Regression [`b1d8c059`](https://github.com/webbase-x/xstage/commit/b1d8c05965c563bbf665d493a0afeb59a8f63f3f) injects journal disk-full and checks original song data, prepared state and absence of safety orphans.
- Test execution/results PENDING-QA, not PASS. Continue engineering without blocking on test latency; stable release still gated on verified results.

## 2026-11-21 — P0.6 malformed restore state (PENDING-QA)

- [`2387ff36`](https://github.com/webbase-x/xstage/commit/2387ff36cdba9b82690b3dd16411423723a61d5a) rejects non-object restore journal state and unknown statuses before indexing, instead of raising an uncontrolled TypeError/KeyError. [`266ea432`](https://github.com/webbase-x/xstage/commit/266ea43246c299178ba8d951d9d4cf8152478d3f) tests list/null/string/unknown status while preserving live data.
- New regression is PENDING-QA; continue independent work without waiting. Stable release requires actual CI and hardware acceptance evidence.

## 2026-11-21 — P1.1 engineering started (PENDING-QA)

- User requested continuous P0–P6 engineering without waiting for interim tests; retain all release and real-device gates for final consolidated verification.
- [`35026576`](https://github.com/webbase-x/xstage/commit/35026576572a1ea69a5b1b6d00f95053b3030393) introduces immutable, validated 2/4/8/16 logical output-bus routing for MIDI channels 0–15, with backwards-compatible stereo default. [`6de61f68`](https://github.com/webbase-x/xstage/commit/6de61f68a823af3b5da606d9d35e179a8c85a57e) adds model contract tests.
- **P1.1 IN PROGRESS, PENDING-QA**: model only; physical multichannel output graph, device selection and ASIO backend are not implemented by these commits. P0.4/P0.5/P0.6 verification remains outstanding; stable release blocked.

## 2026-11-21 — P1.2 percussion note routing (PENDING-QA)

- [`853f7ecd`](https://github.com/webbase-x/xstage/commit/853f7ecda3805ba269bcab0a0e18dab83046a3c4) adds validated per-note drum bus overrides on MIDI channel 9 (zero-based), with per-channel fallback and stereo-compatible defaults; [`72ef31e1`](https://github.com/webbase-x/xstage/commit/72ef31e18e6793ec6cb5fc07c1abfb768a42b2d6) adds unit coverage for overrides and malformed mappings.
- **P1.2 IN PROGRESS, PENDING-QA:** route resolution is implemented but no multichannel native audio backend is connected; ASIO and real-device acceptance remain pending. Continue source implementation without waiting for intermediate tests as requested.

## 2026-11-21 — P1 native device selection foundation (PENDING-QA)

- [`8acef6b0`](https://github.com/webbase-x/xstage/commit/8acef6b04ba3f41f3cc99f94f0d2fafa136c2578) adds optional explicit native BASS device IDs to the reference-counted device manager while preserving the existing default and offline decode behavior. [`8c9e13ca`](https://github.com/webbase-x/xstage/commit/8c9e13ca1ac1bcf27ae132c3396bb7a459285b6f) adds contract tests for separate device ownership, reentrant acquisition and invalid selection.
- **PENDING-QA:** native bus-to-device renderer and ASIO are still not connected; test results deferred to consolidated verification as requested. No stable release.

## 2026-11-21 — P1 explicit device wiring to MIDI synth (PENDING-QA)

- [`f663b89f`](https://github.com/webbase-x/xstage/commit/f663b89fe91275e5ae1b500fcb4bcb268eb2b032) forwards an optional selected output device ID through `BassSynth` to reference-counted BASS acquisition; [`9c052d9a`](https://github.com/webbase-x/xstage/commit/9c052d9a0af0f236d12f8f5b77b969342ed76566) adds a native-API mock regression confirming the selected device is initialized.
- **P1.1/P1.2 still IN PROGRESS**: this is device selection for a synthesizer, not multi-bus stream splitting, 4/8/16 channel audio rendering or ASIO. Consolidated test evidence pending. Stable release remains gated.

## 2026-11-21 — P1 MIDI bus dispatch (PENDING-QA / DEFERRED-HARDWARE)

- [`9452d785`](https://github.com/webbase-x/xstage/commit/9452d7859dea2f5b05a75204c4edf8d8900dbe56) adds injectable, validated MIDI channel-voice dispatch to configured bus sinks; note-on/note-off/percussion polyphonic aftertouch share the same per-note bus. [`1313b64c`](https://github.com/webbase-x/xstage/commit/1313b64ca60fbb49ad3ed8e877a57b1867533b59) adds routing and malformed-message regressions.
- User requests skipping physical tests now. **PENDING-QA / DEFERRED-HARDWARE**, not PASS. This is a MIDI message dispatcher, not PCM splitting, native multi-output rendering or ASIO; these remain to implement. No stable release claim.

## 2026-11-21 — P1 opt-in multi-bus BASSMIDI synthesis (PENDING-QA)

- [`2f74b80e`](https://github.com/webbase-x/xstage/commit/2f74b80e0bd5e13e990abb251a08894b96b6c2c5) adds `karaoke/multi_bus_synth.py`: separate BASSMIDI synth per logical bus, MIDI message routing and optional per-bus BASS device IDs, with cleanup on partial initialization. [`54fd6e90`](https://github.com/webbase-x/xstage/commit/54fd6e9082dfcdaf95e65c4d0b103dd8e466ebb8) preserves the original initialization exception during cleanup.
- **P1.1/P1.2 IN PROGRESS, PENDING-QA**: opt-in backend is not yet wired into normal playback, device/channel matrix and ASIO not yet implemented. Physical tests deferred at user's request; no claim of measured audio output or stable release.

## 2026-11-21 — P1 opt-in integration into main MIDI player (PENDING-QA)

- [`03c39585`](https://github.com/webbase-x/xstage/commit/03c395851fada4ad89014a7d398e5a34c9ae461e) routes channel EQ/tone and per-note drum tone to selected synthesizer bus. [`b9d746ff`](https://github.com/webbase-x/xstage/commit/b9d746ff2bc29ad06c88b0d9fb50dd67b9c36cd6) enables opt-in `multi_bus.enabled` selection in the main MIDI playback path; legacy stereo remains the default.
- **PENDING-QA**: Settings schema/persistence and GUI controls for this opt-in are not yet established; device routing, channel reset semantics, drum-key note-offs and ASIO require consolidated regression and physical verification. No PASS/stable release claim.

## 2026-11-21 — P1 Multi-Out settings UI (PENDING-QA / DEFERRED-HARDWARE)

- [`0c66e0e2`](https://github.com/webbase-x/xstage/commit/0c66e0e2493d7d8c47d89decb3022f43f7e7dbc6) adds Tk Multi-Out routing dialog for enabling buses, assigning 16 MIDI channels and optional BASS device IDs; [`a9c15499`](https://github.com/webbase-x/xstage/commit/a9c154997de6afc09595316a7c6291c7dc27406f) wires it into Settings and persistence; [`f2a26873`](https://github.com/webbase-x/xstage/commit/f2a26873cf5431a79dfc94cc81d2b08caee2718f) adjusts dialog action placement.
- **PENDING-QA:** no runtime/GUI/device tests performed at user's request. ASIO backend, real multi-output hardware matrix, and complete drum-key routing UI remain outstanding; no stable release claim.

## 2026-11-21 — P1.3 ASIO driver discovery foundation (PENDING-QA)

- [`5f13be7f`](https://github.com/webbase-x/xstage/commit/5f13be7fff5f566d46b95987a1f2c0a0bc568939) introduces read-only BASSASIO 2.4 driver discovery, validates addon version and handles absent DLL without affecting existing BASS stereo output. [`46e6904f`](https://github.com/webbase-x/xstage/commit/46e6904f4dbaccaca243f6f0e1c1ba195182b4b6) adds mocked enumeration and version-contract tests.
- **P1.3 IN PROGRESS, PENDING-QA**: ASIO initialization, PCM callback/output bridge, channel assignment, fallback, UI selection and hardware verification remain. No ASIO playback claim or stable release.

## 2026-11-21 17:12 Asia/Bangkok — P1 percussion state routing hardening

- [510a2818](https://github.com/webbase-x/xstage/commit/510a2818569867225a1cff5914c981339da7f9b2) broadcasts MIDI channel 10 controller/program/pitch state to every bus hosting overridden drum keys, while retaining per-note routing. This addresses loss of drum kit/volume state and incomplete all-notes-off on redirected percussion.
- [daf7ad43](https://github.com/webbase-x/xstage/commit/daf7ad43daca45d57c21e54da4d8e536a007a433) adds independent regression cases for broadcast deduplication, note-on/note-off and state messages. [fff43647](https://github.com/webbase-x/xstage/commit/fff43647d2b136acde3ca71104438dff04332934) constrains channel selectors to active bus count when routing count changes.
- **PENDING-QA:** New regressions not yet executed; run full Windows suite and integration gate after remaining independent implementation. Physical ASIO and multi-output tests **DEFERRED-HARDWARE**. Existing P0 checklist evidence does not validate these new commits; do not publish Stable.

## 2026-11-21 — P1.3 ASIO PCM staging (PENDING-QA)

- [`58b05875`](https://github.com/webbase-x/xstage/commit/58b05875680ba4f7043816a56e2dbf7d34cb6c81) adds bounded stereo float32 PCM staging with overflow and underrun accounting, deterministic silence and a native-buffer copy helper. [`b97b5cb4`](https://github.com/webbase-x/xstage/commit/b97b5cb4fa249afe86255815092f393419722d75) adds offline contract tests (not executed in this turn).
- **PENDING-QA**: no ASIO callback or native ASIO initialization exists yet; a real-time callback must be implemented in native code rather than calling Python from the ASIO audio thread. Hardware validation remains deferred. No ASIO playback or stable release claim.

## 2026-11-21 — P1.3 native PCM bridge foundation (PENDING-QA)

- [`6282e59e`](https://github.com/webbase-x/xstage/commit/6282e59ee90145c5face3285a8de5f7418190f90) adds C++ SPSC lock-free PCM FIFO (float32 stereo, silence on underrun) intended for native ASIO callback consumption; [`1b57bfe6`](https://github.com/webbase-x/xstage/commit/1b57bfe6fd7931740c41a2f55ff45fbb2c79b4ec) adds Python producer-side ctypes wrapper.
- **PENDING-QA**: DLL build/package, native BASSASIO callback, BASSMIDI decode producer, device/channel mapping, fallback and real-device verification remain. No real ASIO output is enabled or claimed.

## 2026-11-21 — P1.3 native callback source and DLL build script (PENDING-QA)

- [`9c82b921`](https://github.com/webbase-x/xstage/commit/9c82b9217f5305fde6e685dc8d8481b6b8897405) exports a native BASSASIO-style PCM callback from C++; [`48464b83`](https://github.com/webbase-x/xstage/commit/48464b83b9a7942cee81ee055d7ee7b8e79c1e04) adds MSVC DLL build script; [`376f7def`](https://github.com/webbase-x/xstage/commit/376f7def068866f9556bf6ce1a2768dc30cd8a8b) exposes callback pointer from Python bridge.
- **PENDING-QA**: no compiled DLL verified; no BASSASIO_ChannelEnable/Join/Start host wired; no ASIO format negotiation or MIDI decode producer. DLL packaging and CI remain pending. Do not enable ASIO as a user-facing audio backend yet.

## 2026-11-21 — P1.3 opt-in ASIO output host (PENDING-QA)

- [`604b48b8`](https://github.com/webbase-x/xstage/commit/604b48b8f089aa24633f0079690b5de8eb6a0f5b) adds an opt-in BASSASIO host for device init, channel enable/join, Float32 48 kHz format, start/stop and native callback user-data; [`74bf0822`](https://github.com/webbase-x/xstage/commit/74bf08227ca1ca8a7db36bbe33d868ffc28c8a9c) improves startup failure cleanup.
- **PENDING-QA**: no compiled native DLL or ASIO driver tests, no BASSMIDI decode producer, no audio channel-format validation against real hardware, no GUI backend switch/fallback and no CI packaging. The host is not used by the main player yet; ASIO playback is not claimed.

## 2026-11-21 — P1.3 experimental decode producer (PENDING-QA)

- [`f8ec4446`](https://github.com/webbase-x/xstage/commit/f8ec4446664a106376ddebb2e853da482e271873) introduces opt-in BASSMIDI decode worker feeding the native PCM queue and ASIO host. [`910113ca`](https://github.com/webbase-x/xstage/commit/910113cae2dec4e1bea64c4216da65294782cef2) exposes native FIFO occupancy, bound in [`25c7698a`](https://github.com/webbase-x/xstage/commit/25c7698a34e7348b65a6260d037bd7227632227d).
- **PENDING-QA**: no compiled DLL, tests or physical playback. Verify BASSASIO callback buffer semantics (mono channel buffers vs interleaved stereo) and output format before enabling. Main player integration, CI build/package and fallback remain incomplete.

## 2026-11-21 — P1.3 native ASIO DLL CI integration (PENDING-QA)

- [`b5ef4b44`](https://github.com/webbase-x/xstage/commit/b5ef4b443e7ba5429c1b9b551e227731c41745e3) adds an MSVC x64 compile step before the Windows app build. [`79875851`](https://github.com/webbase-x/xstage/commit/79875851c530ec0ce654165c474cc0340be44a05) requires the compiled DLL inside the candidate package. The build helper's compiler/linker invocation was adjusted in [`24d58639`](https://github.com/webbase-x/xstage/commit/24d586390be801269b987131777c7c9dc8e08e8e).
- **PENDING-QA**: CI build results are not verified. ASIO output channel format, native callback ABI, BASSMIDI producer lifecycle and fallback remain unverified; main-player ASIO remains disabled. No stable release claim.

## 2026-11-21 — P1.3 producer hardening (PENDING-QA)

- [`98188281`](https://github.com/webbase-x/xstage/commit/98188281aff4e827b627292ae359585d44a324e5) requires native FIFO occupancy and preserves ASIO startup exceptions; [`effd4971`](https://github.com/webbase-x/xstage/commit/effd49711fccb4a1ea7d31f55c9e783081e35015) adds mock-only producer lifecycle tests (not executed).
- **PENDING-QA**: ASIO callback format and hardware operation are not verified; ASIO is not wired into the default player. Native DLL CI outcome and BASS fallback must be verified before release.

## 2026-11-21 — P1.3 explicit ASIO selection with BASS startup fallback (PENDING-QA)

- [`67167199`](https://github.com/webbase-x/xstage/commit/6716719945257afff418c06d7e3495b26e06494c) adds an opt-in ASIO backend factory with BASS fallback when ASIO initialization fails. [`088cce1f`](https://github.com/webbase-x/xstage/commit/088cce1f17ffd33c2c8bce8635614a2fcc12f203) integrates it into the single-output MIDI playback path; [`580628c1`](https://github.com/webbase-x/xstage/commit/580628c146c9a001d47161d9b298e0dfd294a2eb) adds mocked selector tests (not run).
- **PENDING-QA**: no user-facing ASIO settings dialog; ASIO opt-in requires configuration. Multi-bus takes precedence. Fallback handles startup only, not a driver failure during playback. Callback format/hardware tests and DLL CI validation remain pending. Do not label stable.

## 2026-11-21 — P1.3 ASIO settings UI (PENDING-QA)

- [`477a894f`](https://github.com/webbase-x/xstage/commit/477a894f9f5db212c37beddeb9c45398fe65b8ae) adds an opt-in ASIO driver/channel dialog with read-only device enumeration and persistence; [`f8d039b0`](https://github.com/webbase-x/xstage/commit/f8d039b05c9abf33c73bb855844e9703f063092b) adds its Settings menu entry.
- **PENDING-QA**: no UI regression executed; BASSASIO stereo callback ABI and physical playback unverified. Driver enumeration is not a device-ready test. Multi-Out still overrides ASIO; fallback handles initialization failures only.

## 2026-11-21 — P1.3 ASIO callback / FIFO safety (PENDING-QA)

- Official BASSASIO documentation confirms that joined channels deliver **interleaved** samples and ASIOPROC's `length` is **bytes**. Stereo float32 therefore uses 8 bytes/frame.
- [`5306f16b`](https://github.com/webbase-x/xstage/commit/5306f16b9b0c26bd3d1934a289ad11742644c484): input ASIO buffers are no longer overwritten when rejecting unexpected callback invocations. [`f261752c`](https://github.com/webbase-x/xstage/commit/f261752ce7e86af74ab37f32567182399d02ec41) tests this with the compiled DLL and makes its presence optional outside CI.
- [`baa9c3ac`](https://github.com/webbase-x/xstage/commit/baa9c3acbcc5f2a3fff0bb7f5dbf5bcfdea0f77a): Windows candidate build requires native DLL ABI tests; an absent or incompatible bridge is not skipped in CI.
- [`f68a9685`](https://github.com/webbase-x/xstage/commit/f68a968558f9f56254ab4ba2c2f4011aba5248c8): BASSMIDI producer retries partial PCM pushes instead of dropping unaccepted frames; [`0b46274a`](https://github.com/webbase-x/xstage/commit/0b46274ae5377daf0a5f55487163733804f0e758) covers ordering with a fake partial consumer.
- [`dc081f47`](https://github.com/webbase-x/xstage/commit/dc081f47b6a5b2a0153854871d9f345d387829d0): a failed ASIO driver release does not free its callback queue; [`72d4d516`](https://github.com/webbase-x/xstage/commit/72d4d5166dc60ac8ff7ef519849141041acba7ed) adds a mocked regression.
- **PENDING-QA / DEFERRED-HARDWARE**: no verified Windows Actions run or physical playback; native callback ABI tests are added but not confirmed passing. Hardware verification and runtime driver-disconnect fallback still outstanding. Do not promote as a stable release.

## 2026-11-21 — Consolidated ASIO / audio reliability implementation (PENDING-QA)

The user requested batched coding without physical QA. **This is a coding update, not an acceptance claim.** Current implementation overview and deferred-once test plan are in [DEFERRED_QA_CHECKLIST_TH.md](DEFERRED_QA_CHECKLIST_TH.md).

- **Critical BASSASIO ABI correction:** driver discovery previously rejected legitimate BASSASIO 1.4 DLLs by checking for BASS 2.4. Corrected in [453d9c95](https://github.com/webbase-x/xstage/commit/453d9c957f0601cc6f8409cafacc1f5e01ec59ae); output host now verifies binary architecture and addon API before initialization ([a743a630](https://github.com/webbase-x/xstage/commit/a743a63089e7d1f0e2416d0c9028e65c10525a2e)). Source: https://www.un4seen.com/doc/bassasio/BASS_ASIO_GetVersion.html
- **Live driver fallback:** [f466b2c1](https://github.com/webbase-x/xstage/commit/f466b2c1c1aae96aad3be2c4344492c498a04d3d) adds recoverable ASIO→BASS output with bounded MIDI state replay; [8143cc3c](https://github.com/webbase-x/xstage/commit/8143cc3caa2326815ca59d99d7b992e6a2663a55) integrates it and [ad769878](https://github.com/webbase-x/xstage/commit/ad769878d2dbc9d9aff41869857f89c186b9face) checks on play/pump. Thread-safe status forwarding is [63f48a26](https://github.com/webbase-x/xstage/commit/63f48a26ecf6d150549638b8b76ad028f8429f06).
- **Output context and latency:** ASIO uses the selected device on the calling thread ([47d58a00](https://github.com/webbase-x/xstage/commit/47d58a0039c511739583be285100c21e07eafa89)); output health is polled via BASS_ASIO_IsStarted; experimental PCM target reduced from 100ms to 40ms ([3ffe88e1](https://github.com/webbase-x/xstage/commit/3ffe88e117da7084ceaf4b448b05e79ad8de504c)), not a measured total latency.
- **Partial P2 / diagnostics:** opt-in stereo float32 sample-peak limiter ([3b5ec8e9](https://github.com/webbase-x/xstage/commit/3b5ec8e97eb7f1f95c59cad1487784e5ec32129e)), processing prior to ASIO FIFO ([3a9b9f46](https://github.com/webbase-x/xstage/commit/3a9b9f460fb5ac7e3b023bdb4df84d132ee1cf33)), settings checkbox ([ded4a930](https://github.com/webbase-x/xstage/commit/ded4a9303a911ca31021ac65a0299a5be6d40146)), FIFO/dropout metrics and user-visible audio diagnostic menu ([c92c98b5](https://github.com/webbase-x/xstage/commit/c92c98b59744bc76289ff1b30eccc740f084285d)). True-peak/LUFS compensation and bus meters remain unimplemented.
- **New deferred software-only regression files:** `tests/test_asio_failover.py`, `tests/test_asio_player_poll.py`, `tests/test_pcm_dynamics.py`; older ASIO tests updated to the wrapped backend. **Not executed at user's request; automated CI may run on repository push.**
- **Remaining engineering:** VST3 host and crash recovery, complete per-bus dynamics/visual meters, robust ASIO + medley dual-deck transitions, chromakey and configurable lyric line layout, comprehensive formats coverage; P6 physical QA, licensing/release signing and stable gate remain blocked. No all-phases-complete claim.

## 2026-11-21 — ASIO final cleanup hardening in deferred-QA batch

- [21a78242](https://github.com/webbase-x/xstage/commit/21a782426dbced583eeb378931221b7c6c48cd19) keeps the ASIO callback owner pinned if a broken driver refuses shutdown, to avoid releasing memory potentially still referenced by the driver; [9f80d44e](https://github.com/webbase-x/xstage/commit/9f80d44eec3d075c71d6f49ab35008802ca0fd35) adds the deferred regression case.
- [087447b2](https://github.com/webbase-x/xstage/commit/087447b21f39fce0a976e3ae6cf1596c9322ce86) reapplies channel tone/EQ before re-triggering surviving notes during ASIO→BASS fallback.
- **No acceptance upgrade:** Windows build result, hardware playback, and complete P0–P6 acceptance are not verified in this coding batch. Read [DEFERRED_QA_CHECKLIST_TH.md](DEFERRED_QA_CHECKLIST_TH.md) before any production release.


## 2026-11-21 19:18 Asia/Bangkok — P0.6 expected-error diagnostics regression

- Verified [Windows CI run 44902275380](https://github.com/webbase-x/xstage/actions/runs/44902275380) on `62785b721d25f2dd3d6170bec963f786a6fab50c`: **SUCCESS**, 1,119 tests / 0 failures / 0 errors / 80 skipped; isolated native Windows Tk GUI: 17 passed / 0 failed / 1 retired. Log review showed no `##[error]` or `##[warning]` annotations for the previously expected recovery/ASIO exceptions or Node.js 20 upload action.
- Added [ASIO diagnostic regression `ad69513c`](https://github.com/webbase-x/xstage/commit/ad69513cee4da5398e5bbf064a6f4e68d7490349): the simulated failed UI notification must still use BASS, emit exactly one WARNING, and never attach traceback `exc_info`. This prevents expected exceptions being misreported as CI failures without hiding the fallback condition.
- **PENDING-QA** for commit `ad69513c`: rerun full Windows regression and installer/GUI smoke via [CI run 44903241363](https://github.com/webbase-x/xstage/actions/runs/44903241363). No physical audio, multi-device, or soak test was performed; those remain **DEFERRED-HARDWARE**. P0.6 and remaining P1–P6 release gates are **not accepted** based on this narrow diagnostic test.

## 2026-11-21 20:15 Asia/Bangkok — P0.6 installed data retention regression

- Current main audited at `c6467f5d9cf229820d50451b25d5b8b5494ace6c`; P0.6 is still **IN PROGRESS**. User reported that song files survived reinstall but the song DB appeared missing. Installer now creates persistent `{app}\\data` and empty `{app}\\Songs` drop folders and removes the previous shortcut override to LocalAppData. Existing LocalAppData DB is **not automatically migrated or deleted**. This change is not yet a verified recovery of the user's DB.
- Exact failed Windows candidate [run 44907345613](https://github.com/webbase-x/xstage/actions/runs/44907345613): **1,122 tests / 1 failure / 0 errors / 80 skipped**, failure `test_installer_brand_pc.PcBrandingRegression.test_ui_and_installer_names` due to an obsolete assertion requiring the former LocalAppData DB path. Source-only regression correction committed at [a63f7984](https://github.com/webbase-x/xstage/commit/a63f79848bbeb19c21df948da9e58b19c9b11b00).
- **PENDING-QA:** full Windows regression rerun; silent upgrade/uninstall preservation of pre-existing `{app}\\data\\songs.sqlite3` and user song sentinel; inspect whether Inno uninstaller leaves both data and Songs directories intact; test Thai/space paths. No claim of PASS from updated assertions alone.
- **DEFERRED-HARDWARE:** actual existing-user upgrade, physical audio/display soak, and device behavior. **Stable release blocked**; P0.4/P0.5 remain deferred/pending. 24/27 acceptance items remain open pending new evidence.

## 2026-11-21 21:18 Asia/Bangkok — P0.6 linked restore roots hardening

- Re-read main and roadmap before editing. P0.6 incremental safety patch [`24c27ecc`](https://github.com/webbase-x/xstage/commit/24c27eccd5ebb00b3a84d8a41c1097c26e2ec8e6) rejects symbolic-link/junction backup roots and restore destination roots before creating staging files. No existing user data is modified.
- Regression tests [`cd01d043`](https://github.com/webbase-x/xstage/commit/cd01d04327228d940ebbb86f499822ecfe243edb), strengthened [`7970eb3f`](https://github.com/webbase-x/xstage/commit/7970eb3f578c981b8efdafd3aa714061396d2149): linked backup root, linked destination, missing backup root. Symlink tests may skip on systems without permission; require Windows CI evidence.
- **PENDING-QA:** Run `python -m unittest discover -s tests -p 'test_restore_root_safety.py'` from `windows-pc/source` and full Windows build regression/installer smoke. No new PASS claim until CI logs confirm; P0.4/P0.5 hardware evidence remains deferred. Continue other independent P0.6 work next iteration. Stable release remains blocked.

## 2026-11-22 — P0.6 restore temporary-file isolation

- `25b1223891423ed3d315e3877073da089625d607`: replace predictable `*.restore-tmp` copy target with exclusive random temporary file, flush/fsync and atomic rename; reject source/target links and unexpected directories.
- `1219ba50be45237d531d49d68cf16714b4adec98`: regression tests for stale temporary symlink, unsafe target symlink and successful cleanup.
- **PENDING-QA**: run Windows regression and installer smoke on these commits; physical storage/Windows reparse-point behavior **DEFERRED-HARDWARE**. No stable release authorized.

## 2026-11-22 01:11 Asia/Bangkok — Windows regression failure triage

- Reviewed failed Windows candidate [run 44928598764](https://github.com/webbase-x/xstage/actions/runs/44928598764): 1,137 tests, **3 failures**, 0 errors, 80 skipped. Two `test_context_menu` assertions expected six top-level child menus and the old first-four labels, but the six-category navigation intentionally adds one cascade. Updated expectations in [`1c086f8a`](https://github.com/webbase-x/xstage/commit/1c086f8a9443712119d4c31a19ce952b8b48f147).
- The third failure, `test_restore.RestoreTests.test_failed_restore_copy_removes_incomplete_staging_file`, patched obsolete `shutil.copyfile` while `replace_file` now streams with `shutil.copyfileobj` into an exclusive randomized temp. Updated fault injection to raise after a partial write and verify no `*.restore-*.tmp` leak in [`60d6f704`](https://github.com/webbase-x/xstage/commit/60d6f7049bb433cdbe753276347d25bfb5dcd884).
- **PENDING-QA:** full Windows regression + installer smoke on both corrections; no PASS claim until exact CI evidence. **DEFERRED-HARDWARE:** physical output, display and soak. P0–P6 remain incomplete and Stable is blocked.

## 2026-11-22 02:11 Asia/Bangkok — P0.4 GUI menu regression follow-up

- Latest reviewed main at start: `ed1a52723bce8b45ffe377338fa8cf2b602b52c4`.
- Windows CI [run 44934174987](https://github.com/webbase-x/xstage/actions/runs/44934174987) FAILED: 1,137 tests, 1 failure, 0 errors, 80 skipped. Only failure: `test_context_menu.ContextMenuTests.test_category_order_and_action_routing`: 21 top-level entries exceed 20-entry UI limit. EXE was not built.
- Removed redundant root separator after the six-category menu: `058d5e02d00df1e7ca451b815f3892bd6ff60d7e`. Added explicit separator regression check: `f4dd3962ad900eb5cc03527b6d0ad69643c0ef05`.
- **PENDING-QA:** run Windows full regression, context menu category test, executable/installer smoke and capture exact CI outcome on the new commit. No claim of PASS until observed.
- **DEFERRED-HARDWARE:** physical GUI flicker, MIDI/ASIO routing, long playback soak; release remains blocked.

## 2026-11-22 03:12 Asia/Bangkok — P0.6 SQLite journal safety

- Verified previous candidate Windows CI [run 44939612374](https://github.com/webbase-x/xstage/actions/runs/44939612374) concluded SUCCESS for commit f604f405; this is evidence only for that commit, not the newer changes.
- Commit 9e7e22b3: reject symlink/junction/non-regular SQLite -wal/-shm sidecars before restore allocation and interrupted rollback, rather than unlinking unsafe paths. This preserves user data on suspicious files.
- Commit 115de64d: regression cases for regular sidecars, directory sidecars and symlink sidecars (Windows symlink privilege conditional).
- **PENDING-QA:** Run focused test_restore_sqlite_sidecar_safety.py, complete restore regression, Windows integration/installer CI on the new commit. Physical playback and audio-device soak remain **DEFERRED-HARDWARE**. No Stable publication authorized.
