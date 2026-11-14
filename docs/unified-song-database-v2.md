# X-Stage Unified Song Database V2

**Status:** Development contract and tested migration path. Do not claim a live
production cutover until the dependent Web/Android PRs have been reviewed,
merged, and the private Google Drive integration has been tested on devices.

## One logical contract, not one physical file

The semantic catalog is **Unified Song Catalog V2**, with
`schemaVersion: 2` and `format: "xstage-unified-v2"`.
The formal contract lives in `contracts/xstage-unified-v2.schema.json`.
Python and JavaScript validators reject incomplete, duplicate and unsafe entries.

- **Windows PC:** keeps `data/songs.sqlite3`, FTS indexes, queue.json and
  settings.json. It can export/import **local-path-only** Unified V2 JSON using
  the offline tools menu. Neither SQL tables nor local song files are moved
  to Google Drive. All import writes require an explicit confirmation and a
  SQLite backup.
- **Song Studio:** keeps `song-index.sqlite3` as its local source scan cache
  and supports V1 → V2 catalog migration in a separate user-authorized
  Google Drive job (`migrate-catalog-v2`, `dryRun: true` by default).
  Native media publishing uses the same V2 fields.
- **Web + Android TV:** load the *same* private Drive Catalog V2 through
  `XStageWeb/DB/current.json`, with a device-local cache of catalog
  **metadata only**. Google Drive OAuth, song downloads and device playback
  remain independent of Windows PC.

A V2 song record has `id`, `webSongId`, `code`, `title`, `artist`,
`media`, and optionally `lyrics`. The `media` object may contain `m4a`,
`mp3`, `midi` and `video`. `midi.type = "ncn"` requires both `lyr`
and `cur` companions. `video.type` describes the original container.

Each media reference has **one** storage locator:
- Local PC: `localPath` (absolute path, never uploaded as a public catalog)
- Private Drive: `fileId` (opaque Google Drive file ID, never a public URL)

Source file fingerprints and size may be present as `sha256`,
`md5Checksum`, `size`, `path`; no private OAuth token appears in either
catalog.

## Private Google Drive tree

```text
XStageWeb/
  DB/
    current.json                    # mutable validated pointer
    catalog-base-v2-<gen>.json      # small complete catalog
    catalogs/
      catalog-v2-<bucket>-<part>-<gen>.json  # immutable, ≤2500 songs each
    deltas/
      catalog-delta-v2-<gen>.json    # immutable upserts, removes
  AUDIO/
    MP3/Songs/...    MP3/Lyrics/...
    M4A/Songs/...    M4A/Lyrics/...
  VIDEO/
    AVI/... MPG/... VCD/... WMV/...
  MIDI/
    NCN/Songs/... NCN/Lyrics/... NCN/Cursor/...
    E-MK/...
```

A small library's pointer has `catalogFileId`; a larger library has
`catalogFiles: [{fileId,bucket,songCount}]`. Never mix both. Each shard
contains no more than 2,500 song rows. Small changes append bounded
`deltaFileIds`, with up to 32 deltas before compaction. The pointer updates
**only after** every referenced immutable catalog and media upload has
returned successfully. The player checks counts, unique IDs and media
references before applying a new generation. It downloads at most three
catalog shards concurrently. Songs and lyrics are downloaded separately
when needed; they are not cached by the public service worker.

**Concurrency caveat:** a read/recheck of a Drive generation detects many
stale writers, but is not a truly atomic compare-and-swap. Avoid concurrent
publishers for the same library. A future production writer lock/transaction
mechanism should be tested before multiuser editing is enabled.

## Safe migration sequence

1. Back up the **existing** `XStageWeb/current.json` and any reachable
   immutable catalogs. Confirm that the user's Google account can read all
   referenced media. Never infer that an unseen Drive folder is empty.
2. In Song Studio with Google Login connected, request
   `action: "migrate-catalog-v2", dryRun: true`. This reads V1 base + deltas,
   checks all IDs, paths, count, and future V2 collisions. It does **not**
   mutate any Google Drive file.
3. Compare source song counts, code collisions and skipped/unsupported
   formats. Do not continue when dry run detects a mismatch.
4. After deliberate approval, request
   `action: "migrate-catalog-v2", dryRun: false,
   confirmation: "MIGRATE_XSTAGEWEB_V2"`. The writer only creates an
   immutable V2 catalog and publishes `DB/current.json`.
5. On Web/Android V2, sign in with the original Google account and verify
   search counts, multiple media formats, sample playback, lyric timing,
   queue/resume behavior and cache isolation.
6. Keep the V1 root `XStageWeb/current.json` and original media until the
   V2 system has been verified by the owner. Migration never auto-deletes
   V1. A rollback is to use the older V1 reader; no files need be restored
   if the V1 pointer was preserved.

**Do not feed Windows `songs.sqlite3` to Google Drive as a playable
Catalog.** Use export/import V2 for structured metadata exchange.
Offline Windows import only accepts `catalogScope:"local-offline"` with
existing local source paths and explicit confirmation. `queue.json` and
`settings.json` are outside this schema and are never overwritten.

## Test matrix / evidence

Automated tests cover Python local/cloud schema validation, JS WebView
validation, path traversal, duplicate stable IDs, NCN companion requirements,
V1 migration dry run, pointer rollback, full Web regression, Android APK
build, Windows SQLite import/export/backup, 2501-song shard partitioning,
incremental delta replay and failed precommit. See:
- `scripts/test_unified_catalog_v2.py`
- `scripts/unified-catalog-v2-test.mjs`
- `windows-pc/source/tests/test_unified_catalog_v2.py`
- `.github/workflows/test-unified-catalog-v2.yml`
- `.github/workflows/test-windows-unified-db-v2.yml`

**Not proven by automated CI:** real user Google Drive permissions,
multi-writer synchronization, codec compatibility for original AVI/WMV/VCD,
all MIDI/SoundFont combinations, audio latency and lyric timing on actual
TrueID/Android TV hardware, and performance against the user's full
song archive. The code should remain in review until those tests pass.
