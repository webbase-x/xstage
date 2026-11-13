# XStageWeb private Google Drive layout — staged migration

```text
XStageWeb/
  AUDIO/
    MP3/
      Songs/{0..9,A..Z}/
      Lyrics/{0..9,A..Z}/
    M4A/
      Songs/{0..9,A..Z}/
      Lyrics/{0..9,A..Z}/
  VIDEO/
    AVI/
    MPG/
    VCD/
    WMV/
  MIDI/
    NCN/
      Songs/{0..9,A..Z}/
      Lyrics/{0..9,A..Z}/
      Cursor/{0..9,A..Z}/
    E-MK/{0..9,A..Z}/
  DB/
  current.json                  # Legacy root pointer retained for web clients
  catalog-base-<generation>.json
  catalog-delta-<generation>.json
```

## Behavioral contract
- New Drive libraries use **XStageWeb**. If **StageWeb** already exists and is accessible, reuse it and preserve its exact ID; if both are visible, refuse to fork the database. No automatic folder rename, move, deletion, or old-path rewrites.
- **Current implementation publishes converted AAC M4A + validated timed JSON/LRC** into `AUDIO/M4A/Songs/{bucket}` and `AUDIO/M4A/Lyrics/{bucket}`; even when a recording originated from NCN, the *rendered* M4A and timed JSON go in the AUDIO/M4A tree.
- Bucket = first ASCII character of song code, uppercase, when alphanumeric; otherwise a deterministic hex SHA-256 first character. Only directories actively needed are created. Filenames remain content-hash suffixed to prevent overwriting.
- `MP3`, `VIDEO`, and native `MIDI/NCN` triplets are **reserved routes only** until import/publisher protocol and player support land. A NCN MIDI song is complete only if Songs/.MID + Lyrics/.LYR + Cursor/.CUR form a verified matching trio. Do not create fake native MIDI catalog entries from the M4A export.
- `MIDI/E-MK` is the requested explicit destination name for non-NCN MIDI format files; parser/compatibility verification required separately.
- `DB/` is created as a reserved database directory. For backward compatibility, **current.json and the immutable catalog snapshots remain at the root**, since existing web players look there. Do not relocate them without a versioned reader/writer migration.
- Catalog entries hold private Drive fileId+checksum+path. A previous catalog's `audio/`, `m4a/`, `lyrics/` paths remain valid; checksum-verified downloads accept both legacy and new typed paths.
- Never store OAuth secrets or private music files in GitHub. Google Drive access scope and ACLs remain unchanged.

## Verification
- `python scripts/test_songstudio_online_publish.py` checks mock Google Drive upload, catalog merging, incremental uploads, restart/recovery, downloads and path routing.
- Real Google Drive account, existing shared libraries, native MIDI triplet upload, Android TV, codecs and browser media playback need independent device-level verification.
