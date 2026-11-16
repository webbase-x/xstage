# X-Stage Song Studio PC — Workflow audit and Build 361 plan

Scope: `webbase-x/xstage` Song Studio PC Ready. No new product or database.
The Karaoke PC, Web and APK library contracts remain unchanged.

## Findings and safe simplifications

| Menu | Previous work | Build 361 decision | Safety boundary |
|---|---|---|---|
| MIDI to .XSK | Already uses bounded source batches (32 files / four queued batches) | Retain incremental pipeline; do not rescan/force song selection | Validate each XSK, original MIDI bytes, timed cues, identity and destination collisions |
| MIDI to Lyrics JSON | `folder_upload.scan` collects up to a million source files, groups all pairs, then returns a full list before conversion | **Replace** with `json_source_stream.stream`: discover media one item at a time; match same-code existing LYR/CUR/LRC; allow embedded KAR/MIDI timing; emit first song immediately. No prerequisite JSON or global inspect | Validate actual cue timing during conversion, verify copied audio SHA-256, journal each song, never overwrite originals |
| Lyrics AI | Work is initiated for a chosen audio/video/lyrics source; no required full-library scan | Keep user-triggered work, reuse source metadata | ASR output is a draft; do not auto-publish unreviewed lyrics |
| Edit Lyrics JSON | User requests global group analysis to find repeated text | Keep explicit scan for groups; never pre-scan on app launch | Preserve timestamped source, backup, undo and mismatch skips |
| Import X-Stage Karaoke Online | Check candidate files and merge catalog on explicit upload | Keep required preflight; do not run on Song Studio startup | Cloud permissions, checksum, duplicate and safe publish checks cannot be removed |
| Import X-Stage Karaoke PC | Previously did inspect then repeated source/catalog/file planning before copying | Reuse one verified plan per publish; keep separate optional UI inspection when explicitly requested | Preserve file SHA-256 at copy, current.json/SQLite consistency and no destructive overwrite |
| Download / Drive | Explicit user action to read/download selected library content | No automatic downloads during startup | Verify downloaded files and Google account permissions |
| Settings / local source | Restore saved preferences and catalog, no conversion on app launch | Keep lightweight restore, no proactive global scan | Preserve stored OAuth and user data between versions |

## MIDI to Lyrics JSON source contract

1. Select a source and a distinct destination once.
2. Walk directories lazily without computing a total number of songs first.
3. Prioritize actual SONG folders; do not recursively enumerate a sibling LYR/CUR/LYRICS directory when its files can be opened by filename directly.\n4. For each **existing** `00001.mid` and same-code `00001.lyr` + `00001.cur`, use the original timed NCN input. Sibling SON(G)/LYR/CUR buckets are supported; files must actually exist.
5. For `.kar` or an SMF with embedded lyric events, parse its real lyric cues at the conversion stage.
6. A previously created `.json` or `.lrc` can still be imported as an optional compatibility source, but no generated `.json` is demanded before conversion.
7. Per-song validation, collision prevention and SHA-256 verification stay enabled. No synthetic lyric timestamps.
8. Journal each completed output. On a repeat run, existing source fingerprints/catalog records prevent duplicates. Interrupted work remains recoverable from the journal.
9. Show real `discovered/created/skipped/errors` counts without pretending that a full-library denominator is known.

## Practical performance constraints

- First conversion starts after the first usable media file, instead of waiting for full-library discovery.
- The source iterator keeps only pending directories plus one media group, not 280,820 song groups.
- The post-copy hash and catalog checkpoint are intentional integrity costs and are **not** removed.
- NCN companions must have the same filename stem in the recognized source layout. A matching name alone does not prove valid timing; cue validation happens before publication.
- The redundant *full-library inspect* button and API are removed from the default MIDI to Lyrics JSON workflow. Dedicated import/publish checks remain.

## Release gates

- Python compile and node UI contract checks.
- Unit tests: NCN sibling matching, KAR single-file, MID without prerequired JSON, incomplete source skip, preexisting audio+JSON compatibility, user cancellation.
- Existing JSON Pro original/transcode/resume and dedup regression tests.
- Windows native Qt smoke and complete offline Ready ZIP conversion tests.
- Publish only a **candidate** artifact until these pass; merge/release separately.
