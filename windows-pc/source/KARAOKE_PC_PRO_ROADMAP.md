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
| P0.1 | Build and tests | Re-run full Windows regression on the latest P0 source/workflow; **0 fail, 0 errors** and review skips | OPEN | 1,014/0/0/78 is prior source only; trigger a new main candidate |
| P0.2 | EXE and integrity | Native 64-bit BASS DLLs, icon, executable, SHA-256 and signed package manifest verified | OPEN | Previous candidate passes; re-verify new build |
| P0.3 | Real installer smoke | Silent install to Thai/space path; installed EXE dependency preflight; clean uninstall | OPEN | New CI step not yet evidenced |
| P0.4 | GUI & queue safety | Windows UI open/close, search, hotkeys, queue, mixer lifecycle and no stalling/flicker | OPEN | Add GUI smoke evidence and review failures |
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

**Current outstanding:** **27 of 27** checklist items, including **6 P0** gates. Prior candidate test success provides evidence but **does not automatically close an item** on newer code/workflow.

## Rules for every hourly development iteration

1. Read current `main`, workflow runs, relevant code/tests and this file; avoid concurrent-work conflicts.
2. Select only the first unfinished acceptance ID within the current phase. Make the smallest safe code/test fix, or collect concrete missing evidence.
3. Run unit/regression checks and GitHub Actions on the exact source revision. If an error occurs, **fix and re-run**; do not mark PASS on source-only inspection.
4. On a blocking requirement (e.g. no real hardware or unavailable credentials), mark `BLOCKED-HARDWARE`/`BLOCKED-ACCESS`, document reproducible checks, and remain in the same phase. Never fabricate device QA.
5. Record dated commit SHA, CI run URL, tests run/passed/failed/errors/skipped, any artifacts, and exact remaining count. Do not mutate Release/installer availability flags without verified evidence.
6. Continue to the next task **only after the current task passes**; advance to P1 only when **all 6 P0 items pass**.

## Hourly report format

- **Working on:** `P?.?` + one-line objective
- **Changed:** exact file paths, Git commit SHA and/or CI run
- **Verification:** tests X, failed Y, errors Z, skipped S; Windows hardware checked / not checked
- **Decision:** PASS / FAIL / BLOCKED
- **Remaining:** P0 6−accepted, total 27−accepted (explicitly show count)
- **Next:** stay on same item if not PASS; otherwise first remaining item in phase
