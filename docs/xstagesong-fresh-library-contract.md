# XStageSong storage contract — fresh library (2026-11-16)

The owner confirmed the library currently contains **no songs**, so new installations
and an empty private Google Drive must start with **one** root named `XStageSong`.
Do not attempt automatic migration of historical catalogs or prepopulate songs.

## Required relative paths

```text
XStageSong/
  AUDIO/<first-code-char>/<code>-<digest>.m4a|.mp3|.wav|.flac|...
  VIDEO/<first-code-char>/<code>-<digest>.mp4|.webm|...
  MIDI/MID/<first-code-char>/<code>-<digest>.mid
  MIDI/KAR/<first-code-char>/<code>-<digest>.kar
  MIDI/XSK/<first-code-char>/<code>-<digest>.xsk
  MIDI/NCN/SONG/<first-code-char>/<code>-<digest>.mid
  MIDI/NCN/LYRICS/<first-code-char>/<code>-<digest>.lyr
  MIDI/NCN/CURSOR/<first-code-char>/<code>-<digest>.cur
  LYRICS/<first-code-char>/<code>-<digest>.json
  SOUNDFONT/<name>-<digest>.sf2|.sf3
  DB/            # local SQLite and portable snapshots
  CACHE/         # local transient only; no private Drive uploads
  BACKUP/        # local backup and verified recovery
  LOGS/          # local logging; never upload secrets
```

The bucket is the first ASCII uppercase digit/letter of **song code**, or `_`
when unavailable. Code and title/artist are **different** properties. Catalog
records must preserve exact relative paths and, on Drive, real Drive file IDs.

## Catalog consistency

- The currently deployed v4 Web/APK reader uses `LYRICS/current.json` and
  immutable `LYRICS/catalog-base-*.json` / `catalog-delta-*.json`. Keep those
  control files in place until *all* readers have been upgraded to another
  location. Merely adding `DB/` is not a reason to move them.
- Karaoke PC uses a local SQLite song index; the portable export writes
  `DB/songs-portable.json`. The Drive catalog is *derived* from the same media
  and metadata, but contains Drive file IDs rather than local paths alone.
- XSK2 stores MIDI and its timed JSON **inside one XSK**. Do not create a
  duplicate standalone Lyrics JSON solely because of XSK2.
- An imported original NCN trio stores all three original files under
  `MIDI/NCN`, with a separately validated timed JSON in `LYRICS/` for Web and
  APK playback. An incomplete trio is rejected; the original CUR timing is
  never fabricated.
- Publishing is additive. Verify complete files and checksums before
  atomically publishing a new catalog pointer. The absence of a previous
  library does *not* authorize deleting other Drive folders, app data,
  credentials or unrelated user files.
- The Web/Android APK use the same hosted WebView player and Drive File-ID
  catalog. Platform-dependent codecs and offline functionality are distinct
  from taxonomy and must be tested independently.

## Implementation notes

The initial code rollout covers typed media upload in the Web importer and
Song Studio Drive publisher, and typed media export/ingest in Karaoke PC.
The legacy Song Studio authoring workspace uses lowercase `audio/`, `lyrics/`
and `current.json` internally, separate from the publishing destination.
Do not treat this description as proof that every end-to-end device build,
Google Drive initialization, source NCN extraction path and database migration
has passed verification. GitHub Actions and Windows/Android device validation
are required before declaring full platform parity.
