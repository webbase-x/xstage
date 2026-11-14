# XStageWeb Google Drive layout · V2 only

The previous root-level `current.json` and `StageWeb` scheme are retired. The only active catalog pointer is **`XStageWeb/DB/current.json`** with `schemaVersion: 2`.

```text
XStageWeb/
  AUDIO/
    MP3/Songs/{0-9,A-Z}/    MP3/Lyrics/{0-9,A-Z}/
    M4A/Songs/{0-9,A-Z}/    M4A/Lyrics/{0-9,A-Z}/
  VIDEO/
    AVI/ MPG/ VCD/ WMV/
  MIDI/
    NCN/Songs/{0-9,A-Z}/
    NCN/Lyrics/{0-9,A-Z}/
    NCN/Cursor/{0-9,A-Z}/
    E-MK/{0-9,A-Z}/
  DB/
    current.json
    catalog-base-v2-<generation>.json
    catalogs/catalog-v2-<bucket>-<part>-<generation>.json
    deltas/catalog-delta-v2-<generation>.json
```

Song Studio creates V2 folders from a verified new Google Drive and publishes valid M4A/timed JSON as private files; the native media uploader publishes original MP3, video, NCN MID/LYR/CUR and E-MK formats as verified components. The catalog uses private Drive file IDs and checksums, not public URLs.

The Web/Android app downloads the V2 metadata after login, creating a zero-song private V2 DB only when no visible root exists. Actual song files and lyrics are fetched on demand. The account's `drive.file` OAuth permissions must allow access to the specific app files; credentials are never embedded in the catalog.

The active `DB/current.json` pointer changes only after immutable media and catalog files are uploaded and validated. Catalogs use shards (max 2,500 songs/file) and compact after 32 deltas. Automatic folder creation does not mean that a codec can decode every source media file on every device.

See `docs/unified-song-database-v2.md` for full format, tests and production caveats.
