# X-Stage Karaoke · Google Drive V2 Only

## Current development contract

The private Google Drive library is **XStageWeb only**. The old
`StageWeb`, root-level `XStageWeb/current.json`, desktop backup tree
`X-Stage Song Studio/songs`, and V1 delta/pointer readers are no longer
part of the cloud workflow. The Google Drive user does **not** have to
create folders manually.

The logical song contract is the same across products:
`schemaVersion:2` and `format:"xstage-unified-v2"`,
defined in `contracts/xstage-unified-v2.schema.json`.

**Distinct storage locations:** Windows PC retains its local
`songs.sqlite3` searchable catalog; Song Studio maintains local scanning
data; Web and Android TV read the user's authenticated **private Drive**
catalog. A local absolute path must never become a Google Drive URL or
public media link. Google OAuth credentials are never included in the
catalog or GitHub Pages.

## Cloud folders

```text
XStageWeb/
  AUDIO/
    MP3/Songs/{0-9,A-Z}/
    MP3/Lyrics/{0-9,A-Z}/
    M4A/Songs/{0-9,A-Z}/
    M4A/Lyrics/{0-9,A-Z}/
  VIDEO/
    AVI/
    MPG/
    VCD/
    WMV/
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

A first-run **Song Studio** user can press **เตรียมและตรวจสอบคลัง
XStageWeb V2** after Google Login. That creates the skeleton folders
and a validated **zero-song** catalog if missing. Pressing the same
button again reads the current V2 pointer without resetting it.
Alternatively, simply upload a verified M4A/Lyrics song: the publisher
creates the missing folders automatically.

**Web/Android TV** now try to create the private `XStageWeb/DB` and
the zero-song V2 pointer after the Google account is authenticated
and no accessible library exists. Existing V2 libraries are read
instead of overwritten. The Web implementation does not require
a PC database to open a new, empty stage.

Folder creation is lazy for individual song-code subfolders on the
Web and upload paths. This avoids creating hundreds of empty folders
before the first song exists.

## Catalog structure and safe publishing

Each record contains `id`, `webSongId`, `code`, `title`,
`artist`, `media` and optional `lyrics`. Media is keyed by
`m4a`, `mp3`, `midi`, or `video` and refers to a private
Google Drive `fileId`. NCN requires complete MID/LYR/CUR components.

- Native MP3, M4A, AVI, MPG/VCD, WMV, NCN and E-MK files are uploaded
  through the verified V2 original-media publisher. Codec capability
  is checked at playback; a file's catalog presence is **not**
  proof a device can decode it.
- Locally produced M4A and timed JSON are published from Song Studio
  directly to V2 with code collision and MD5 checks, without uploading
  the entire local `songs.sqlite3` or lyrics workspace.
- DB publishing is **last**: uploaded media and immutable catalog shards
  must succeed before `DB/current.json` changes.
- Single-catalog pointers are allowed for smaller libraries. For
  larger libraries, `catalogFiles` references immutable shards of
  up to 2,500 songs. Small updates add bounded deltas; at 32 deltas,
  the publisher compacts to new immutable base data.
- The Web reader downloads at most 3 catalog shards simultaneously,
  validates IDs and song counts and reuses a private local metadata
  cache. Actual audio and lyrics remain private and are loaded
  separately when required.

A failed upload, cancelled job, conflicting song code, duplicate ID,
missing media component or corrupt catalog must **not** publish a
new active DB pointer. Previously published data stays available.
Private Drive folders are never shared publicly as part of publishing.

## Download / restore

Song Studio downloads from the **V2 pointer only**.
The `DB` option saves the referenced V2 base/shards/deltas plus
`DB/current.json`. The `songs` option saves all referenced V2
media/lyrics and DB metadata. The `zip` option assembles the
same verified private snapshot. Every downloaded file must have a
matching Google Drive MD5. Existing different local files are not
overwritten. Download commands are **read-only** on Google Drive.

If the account has no published V2 pointer, the download command
reports that there is no library yet. It must not fall back to an
unrelated old backup tree or create a new cloud folder in response.

## Tests / remaining production validation

Automated tests:
- `scripts/test_songstudio_online_publish.py`: first-run creation,
  MD5 duplicate/conflict, interrupted upload, private V2 download.
- `scripts/test_v2_native_publish.py`: original file types and NCN
  component integrity.
- `scripts/test_unified_catalog_v2.py`: schema, shards/deltas,
  zero-song pointer, integrity and generation checks.
- `scripts/unified-catalog-v2-test.mjs`: browser catalog contract.
- `scripts/xstage-v2-first-run-test.mjs`: simulate authenticated Web
  Drive API create/re-open without touching actual user data.
- Existing Web, Android and Song Studio regression/Build workflows.

**Not yet validated by mocked CI:** real Google OAuth cross-client
permissions between Song Studio and Web, first-time CORS upload of the
Web zero-song catalog on a real account, playback of every MIDI and
video container on real TV hardware, synchronization under multiple
simultaneous writers, and a full user-sized private Drive library.
A CI-passing development branch is not automatically a deployed update.

The Desktop Google OAuth client and Web Google OAuth client must use
correctly authorized scopes and apps. With `drive.file`, files that
one OAuth app cannot see may require the user to authorize them
with a Google Picker or choose an aligned Google Cloud app
configuration. Do not silently assume lack of visibility proves
an unrelated file has been deleted.

No live Google Drive file deletion or real-account migration was
performed while preparing this code.
