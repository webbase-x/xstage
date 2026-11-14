# X-Stage Karaoke Windows PC — Unified DB V2 (offline only)

The Windows player **does not include X-Stage Karaoke Online sync, Google
Login or cloud publishing**. The local `data/songs.sqlite3` remains its
primary searchable database, with its existing SQLite WAL/FTS indexes.

## Export a portable metadata catalog

Right click → เครื่องมือ → **ส่งออกฐานเพลง Unified V2…** and choose a
`.json` destination. Export runs in a worker and does **not write** to
SQLite or change the music. It writes a complete output atomically.

The exported JSON uses `schemaVersion:2`,
`format:"xstage-unified-v2"`, and `catalogScope:"local-offline"`.
Each song has the common fields `id`, `webSongId`, `code`,
`title`, `artist`, `media` and `lyrics`. Media references are
absolute **localPath** values, not Google Drive IDs. NCN requires a
verified same-code LYR and CUR component. Missing or unsupported
source formats are reported as skipped, never invented.

**The export is metadata only.** It does not copy audio/video,
SoundFont, queue.json, settings.json, or files into other computers.
Check the skipped count before treating the export as complete.

## Import a local Unified V2 catalog

Right click → เครื่องมือ → **นำเข้าฐานเพลง Unified V2…**

1. The app validates the complete JSON, every required local media
   path and every NCN companion in a background thread.
2. Preview does not modify SQLite. The user must explicitly approve.
3. A new `songs-before-unified-v2-*.sqlite3` backup is created and
   checked using SQLite integrity_check **before** the database is updated.
4. Existing rows are merged by canonical local file path through
   SongLibrary, respecting user-edited names and existing favorites.
5. A failed preflight leaves the original SQLite and queue unchanged.

Cloud-only catalogs with `fileId` cannot be imported as local
media. Do not replace them with guessed disk paths; use Song Studio
to transfer authorized media explicitly.

## Tests / release

Unit tests: `windows-pc/source/tests/test_unified_catalog_v2.py`.
CI: `.github/workflows/test-windows-unified-db-v2.yml` plus
the existing full Windows installer regression. Before publishing
a new public installer, confirm the complete Windows build,
installer checksum, real-device installation and sample playback.
