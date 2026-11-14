# X-Stage Karaoke Online — On-stage piano (Web)

The Web stage has a 49-note C3–C7 piano keyboard based on familiar GM karaoke keyboard conventions. The original Windows PC binary/widget is not in this repository, so this is a new Web implementation rather than a byte-identical port of the PC control.

- Open **🎹 เปียโน** in the stage toolbar (desktop) or **🎹 เปียโน MIDI บนเวที** in the mobile stage menu; close at any time.
- On desktop-sized Web views a MIDI song opens the piano automatically unless the user has explicitly hidden it. On phones it opens on demand.
- White/black keys can be touched, clicked or activated with keyboard Space/Enter. These produce **basic sine-wave preview notes**, not the selected SoundFont preset.
- When a MIDI/KAR/NCN-backed track renders, its note start/end events are obtained from the same tempo map as the synthesized WAV and are highlighted according to the player's current time. Seek, pause, resume and changing tracks are supported. The **Ch** selector filters **visual highlights only**; it does not mute channels or edit MIDI data.
- MP3/M4A/video files do **not** contain playable MIDI note events, so there is no invented or AI-derived note visualization for those files. The piano can still be opened for manually playing notes.
- The piano docks above the transport, shrinks for landscape/phone, and reserves lyric drawing space. Native Android TV remains a display-only stage, so its piano panel is hidden.
- No Drive permissions, original song files, NCN LYR/CUR or Lyrics JSON are changed.

Quality and limits: 49-key visualization (not full 88-note hardware range), simple oscillator for manually pressed keys, no ASIO support, no MIDI input device connection, no channel mute/solo, and no real-time MIDI synthesis (the existing browser engine pre-renders the MIDI track). These features must not be claimed as implemented.

Tests: `npm test` includes `scripts/stage-piano-test.mjs` and MIDI render timing assertions. Check real mobile-browser touch behavior and lyric overlap before public deployment.
