# X-Stage Karaoke PC — Right-click menu QA matrix

The right-click menu is grouped and numbered for operator discovery. Numbered groups do not imply that hardware/integration acceptance has passed.

| Group | Required verification | Status |
|---|---|---|
| 1. เพลงและคิว | Import/search song, queue insertion, history, empty/stale search, persisted SQLite, next-song preloading | PENDING-QA |
| 2. เสียงและ SoundFont | MIDI output enumeration, mixer F9, instrument SoundFont map, EQ persistence, unplug/replug mock device, real ASIO/BASS routing | PENDING-QA / DEFERRED-HARDWARE |
| 3. เนื้อร้องและภาพ | Thai combining vowels, LRC synchronization, stage background, second-display open/close and display fallback | PENDING-QA / DEFERRED-HARDWARE |
| 4. การควบคุม | Help shortcuts, remote authorization/reconnect, MIDI keyboard F4 and mock note events | PENDING-QA |
| 5. เครื่องมือแสดงสด | Medley no-silence transitions, record start/stop, FX display/CPU, no effects inserted in dry output | PENDING-QA / DEFERRED-HARDWARE |
| 6. ระบบและสถานะ | Audio diagnostics and dependency state, capabilities truthfulness, update check when playback active | PENDING-QA |
| 7. ตัวเลือกและตัวกรอง | Filter changes refresh results, no accidental selection, persisted lyric display settings | PENDING-QA |
| 8. พื้นหลัง | Set/clear background, absent image, resize and second-display propagation | PENDING-QA |
| 9. เครื่องมือขั้นสูง | Every nested action dispatches; medley cancellation; repair consent; log/report windows; LRC editing; restore atomicity | PENDING-QA |
| 10. ตัวควบคุมเสียง / การเล่น | F5–F8, empty queue disabled states, key/tempo/volume, Ch4 melody only for MIDI, A–B loop | PENDING-QA |
| 11. ระบบ 2 หน้าจอ | 0/1/2+ virtual monitors, fullscreen toggles, resolution and hot-unplug | PENDING-QA / DEFERRED-HARDWARE |
| 12. หน้าต่าง | F11, pin/unpin transport, dismiss overlays Esc, minimize and restore | PENDING-QA |
| 13. ทางลัด MIDI และเพลง | F2/F4/F9 parity with categories, no duplicate invocation, SoundFont controls and fallback | PENDING-QA |
| 14. โปรแกรมและการออก | Update dialog, About metadata, Alt+F4 exit and safe shutdown | PENDING-QA |

## Automated gates
- Run `python -m unittest tests.test_context_menu tests.test_six_category_menu tests.test_menu_dispatch` from `windows-pc/source`.
- Windows CI: full regression, menu routing, Tk virtual display sizes, installer build, install and installed-runtime smoke.
- Physical audio, actual second monitor, MIDI controller, long soak: **DEFERRED-HARDWARE** until available.
- Do not mark any group PASS solely from a successful static/menu-dispatch test.
