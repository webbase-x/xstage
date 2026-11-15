## 0.5.86 audit validation

572 tests: 562 passed, 10 skipped; Linux Python 3.12.14, 20.897 seconds. Python syntax validation passed for 183 files. New tests cover remote GET/POST failure logging and module categories. No native Windows build, live audio, GUI or hardware testing performed in this audit. See AUDIT_0586_TH.md and AUDIT_0586_TESTS.txt.

## 0.5.85 validation

- Full suite: 569 tests, 559 passed, 10 skipped, 20.315 seconds on Linux Python 3.12.
- GUI checks passed on Linux Tk 8.6 / Python 3.13 / Xvfb 1440x900: EQ grip mapped, drag resizing retains size after fit, meter area at least 140 px, log viewer opens a UTF-8 log, singer window starts borderless and remains borderless after fullscreen exit. EQ screenshot inspected. Capture replaced by no-op for UI testing; no real audio measured.
- Unit checks: resize bounds/control space, bounded Unicode log tail, actual diagnostic directory, category labels, borderless fullscreen exit. Updated metadata test excludes code/duration.
- Native Windows / multi-monitor hardware / real audio not tested here.

## 0.5.84 validation

- Full suite: 564 tests, 554 passed, 10 skipped, 20.492 seconds on Linux Python 3.12.
- SoundFont suite including GUI: 14 passed, 1.587 seconds, Linux Tk 8.6 / Python 3.13 / Xvfb 1440x900.
- New regression: resize/move window to 880x640+25+30 then switch every tab; verify geometry remains identical.
- Includes 0.5.83 diagnostics, consistently named XStageKaraoke.log and XStageKaraoke-native-<session>.log.
- Native Windows flicker/hang and real hardware playback remain unverified.

## 0.5.83 validation

- Full suite: 564 tests, 554 passed, 10 skipped, 20.417 seconds (Linux / Python 3.12).
- After final log filename change, all three runtime diagnostics tests passed.
- Covers callback/worker traceback persistence, error queue, watchdog episode/rate bounds, and releasing only the hidden dialog own grab.
- Native Windows freeze has not been reproduced. Native crash interception and hardware audio need Windows verification. GUI-specific tests were skipped; separate GUI attempt could not run because Xvfb is unavailable.
- Log names: XStageKaraoke.log and XStageKaraoke-native-<session>.log. No automatic upload.

## 0.5.82 validation

- Full suite: 561 tests, 551 passed, 10 skipped, 21.425 seconds on Linux / Python 3.12.
- User Windows 0.5.81 log: 561 tests, one failure, seven skipped. Failure was a short TEMP alias versus resolved Unicode path comparison in test_component_requires_all_matching_hashes.
- Corrected expected canonical path and added samefile identity assertion. Every component hash is tested against tampering. Production validator and build gate are unchanged.
- Native Windows EXE build and hardware playback were not run in this environment.

# Version 0.5.81 verification

- Full Linux/Python automated suite: 561 tests, 551 passed, 10 skipped, 20.969 seconds.
- Separate Tk 8.6/Xvfb SoundFont suites: 14 passed, including GUI tests skipped by the headless suite.
- Verified cancellation during blocked synth initialization causes cleanup without sending notes; native synth lifetime stays on the worker thread. Audio tests use doubles, not a Windows speaker.
- Verified pending gain commit, selection-only clean state, invalid gain rejection, close cancellation, save and view restoration; note/chord boundaries; exact/missing/LSB/invalid-mapping coverage statuses.
- Inspected preset and populated coverage tabs. Footer bounds checked at Tk scaling factors 1, 1.25, 1.5 and 2 on a 900x650 window. This is not native Windows DPI validation.
- No Windows EXE build or real SoundFont listening test was performed in this environment. The source installer test gate remains enabled.

---
Previous release evidence:

# Version 0.5.80 verification

- Full Linux/Python automated suite: 553 tests, 544 passed, 9 skipped, 20.761 seconds.
- Separate SoundFont Tk 8.6/Xvfb suite: 6 passed (including one GUI test skipped in the headless full suite).
- Verified a single file uses all-preset native configuration, bank/program message forwarding, exact temporary preset audition settings, all-bank search/filter, UTF-8 Thai names, empty browser after removing fonts and save-failure rollback.
- Native BASS calls in these tests use API doubles; metadata fixtures are not authentic Thai instrument samples. No claim of an acoustic test on Windows.
- Visually inspected all five tabs on Tk 8.6. Native Windows DPI/fonts and live audio still need machine testing.
- Source archive only; installer test gate retained. No Windows EXE was built in this environment.

---
Previous release evidence:

# Version 0.5.79 verification

- Full automated suite on Linux / Python 3.12: 547 tests, 539 passed, 8 skipped, 74.976 seconds.
- Separate Tk 8.6 / Xvfb workspace tests: 3 passed, including the GUI test skipped by the headless suite. Covers independent catalog search, refresh after edits, missing database, window reuse, cancel/reset, result rows and footer bounds at 1100x740 and 760x600.
- Visually inspected the unified workspace with a populated test library using Tk 8.6; Thai labels render correctly in that runtime.
- Native Windows DPI/font rendering, production-scale library responsiveness, installer EXE and live audio were not tested on Windows here.
- Build test gate remains enabled. This deliverable is source, not a prebuilt Windows EXE.

---
Previous release evidence follows:

# Validation — 0.5.78

- Full suite: 544 tests in 24.586 seconds; 537 passed, 7 skipped.
- Tk/Xvfb interaction suite: 7 tests passed in 3.599 seconds, including debounce, bypass/FLAT, child-window protection and wide control layout.
- GUI regression: first open via public entry point, preset/A-B, intensity, mouse-wheel/live drag, song EQ/default isolation, recall, dock/reopen, 800px and 1400px layouts, offscreen recovery and cleanup passed with native audio mocked.
- New tests check first open calls show exactly once, both entry points reuse the same window and a destroyed window is recreated/shown.
- Screenshots inspected for grouping and numeric label placement. Linux font rendering differs from Windows.

Not verified: actual Windows first-click focus behavior, Thai font/DPI, native audio and Windows EXE build. This change fixes the identified creation/reopen code-path difference but still requires native confirmation of the reported symptom.
