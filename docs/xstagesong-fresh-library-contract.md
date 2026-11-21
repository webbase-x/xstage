# XStageSong storage contract — fresh library (2026-11-16)

The owner confirmed the library currently contains **no songs**, so new installations
and an empty private Google Drive must start with **one** root named `XStageSong`.
Do not attempt automatic migration of historical catalogs or prepopulate songs.

## Agreed relative paths for moving/copying a type folder

```text
XStageSong/
  MIDI/MID/SONG/<bucket>/<code>.mid
  MIDI/MID/LYRICS/<bucket>/<code>.json
  MIDI/KAR/<bucket>/<code>.kar
  MIDI/XSK/<bucket>/<code>.xsk
  MIDI/NCN/SONG/<bucket>/<code>.mid
  MIDI/NCN/LYR/<bucket>/<code>.lyr
  MIDI/NCN/CUR/<bucket>/<code>.cur
  AUDIO/MP3/SONG/<bucket>/<code>.mp3
  AUDIO/MP3/LYRICS/<bucket>/<code>.json
  AUDIO/M4A/SONG/<bucket>/<code>.m4a
  AUDIO/M4A/LYRICS/<bucket>/<code>.json
  AUDIO/WAV|AAC|FLAC|OGG|OGA|WMA/{SONG,LYRICS}/<bucket>/...
  VIDEO/MP4/SONG/<bucket>/<code>.mp4
  VIDEO/MP4/LYRICS/<bucket>/<code>.json
  VIDEO/WEBM|MKV|AVI|MPG|MPEG|DAT|VOB|MOV|WMV|FLV/{SONG,LYRICS}/<bucket>/...
  SOUNDFONT/SF2/<name>.sf2
  SOUNDFONT/SF3/<name>.sf3
  DB/ CACHE/ BACKUP/ LOGS/
```

The bucket is the first ASCII uppercase digit/letter of the **song code**,
or `_` when unavailable. A code/extension pair determines SONG/LYRICS;
KAR and XSK are **standalone**: no redundant SONG or LYRICS directory.
NCN retains original MID+LYR+CUR. The whole format directory may be copied
to another drive and reindexed using relative paths; never store absolute
authoring-machine paths in a portable catalog. Song title/artist come from
validated metadata rather than inferred filenames.

For content-addressed Drive uploads, files may use `<code>-<digest>` as their
basename to avoid overwrites, while the catalog still carries the assigned
song code and exact real Drive file IDs. Changing physical filenames does not
permit unverified reassignment to another song.

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
- Original NCN files stay together under `MIDI/NCN/{SONG,LYR,CUR}`
  by code. If a Web player needs converted timed JSON, store that verified
  derivative in `MIDI/NCN/LYRICS` only as a playback cache; do not change the
  original three-file NCN contract or fabricate missing CUR timing.
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

---
> **Historical reference only**. New online libraries must use `XStageKaraoke/{SONGS,DB,SOUNDFONT}` and never automatically read or migrate `XStageSong`.
