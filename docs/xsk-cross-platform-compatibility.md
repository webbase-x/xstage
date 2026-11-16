# X-Stage XSK cross-platform compatibility contract

Status: implementation specification; **NOT** a claim that Karaoke PC, Web or Android APK can currently play XSK.

## Existing format and non-regression requirements

The existing Song Studio `xsk_package.py` emits `XSK1` + 12-byte nonce + AES-256-GCM ciphertext authenticated with the `XSK1` AAD. Authenticated plaintext is a two-entry ZIP containing a MIDI/KAR file and a JSON document with `format: "XSK"`, `formatVersion: 1`, `songCode`, metadata, timed `lines` and SHA-256 of the enclosed MIDI/KAR. A reader MUST implement the existing v1 format rather than rename or reinterpret it as raw MIDI. Legacy MIDI/KAR/EMK/NCN and playable audio/video with external timed lyrics must remain in their existing import/playback paths.

## Critical prerequisite: authorized decryption

XSK packages are encrypted, not self-describing song files. Importers must support an explicit locked/unavailable state if a matching authorized key is not provisioned. **Do not embed an AES key in browser or APK source, publish a key in Google Drive metadata, assume all archives share one hard-coded key, or expose decrypted ZIP/MIDI/lyrics in the public catalog.** Authorize key access per user's local device/session or equivalent secure, deliberate sharing mechanism. Missing/wrong keys must cause a clear actionable failure without destroying existing DB entries.

## DB and catalog migration

- Add an optional `containerFormat: "XSK"`, `containerVersion: 1`, `mediaKind: "MIDI"`, `locked` state and stable media reference to a shared catalog representation. Preserve all existing columns, IDs, favorites, queue, play history, user-edited title/artist, lyric references and old schemas through additive migrations.
- The PC SQLite catalog must keep the original source path and identify XSK as a container, not classify it as plain MIDI bytes. Existing .mid/.kar/.emk/media rows must retain their meaning and remain searchable/playable.
- The Web/APK Drive catalog must reference the private XSK Drive file ID with authorized access, never use a Windows absolute path. Import/publish should be idempotent by stable file identity and verified content hash where available.
- Do not mark a song playable until key provision, authenticated decryption, bounded ZIP inspection, media SHA-256 verification and MIDI parser readiness pass. A locked XSK can be indexed and displayed separately but cannot be queued as playable.
- Do not destructively reinitialize an existing DB; use transaction/backups and a versioned migration with rollback on error, interruption or insufficient disk space.

## Playback boundaries

PC: decrypt in memory then use the existing MIDI/SoundFont renderer and timed JSON lyrics path. Web: use Web Crypto AES-GCM to authenticate the existing envelope and the MIDI/SoundFont player, with no key in the service-worker cache. APK: match the Web reader for WebView-based clients or implement equivalent platform crypto for native clients. Android TV must retain the existing authentication gate and remote control flow.

## Acceptance tests required before release

1. An old populated PC SQLite DB migrates without losing song count, user-edited metadata, favorites, history or existing playback; reinstall does not require a library rebuild.
2. The same old catalog remains readable on Web and APK; older media plays under the same supported codecs and lyric behavior.
3. A Song Studio-produced known-key XSK can be imported, searched, queued and played to the end on PC, Web and APK; MIDI events and timed lyrics match the original source.
4. Wrong or missing key, tampered GCM tag, forged header, malformed or oversized ZIP, duplicate paths, ZIP traversal, incorrect SHA-256 and cancellation fail closed without plaintext leakage or catalog corruption.
5. Repeated import/Drive upload is idempotent, update does not erase older records, partial upload is not published, and offline/resume behavior remains consistent.
6. Browser e2e, PC runtime e2e and Android device/emulator playback pass before release/build metadata is advanced.

**Release gate:** all three actual players and their import/catalog integrations must be implemented and tested; adding `.xsk` to extension lists or updating documentation alone is insufficient.
