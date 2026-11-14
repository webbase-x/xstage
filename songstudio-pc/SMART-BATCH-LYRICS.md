# Smart Batch Lyrics Correction — Song Studio PC

This feature is developed on a separate branch and must pass its pull-request
checks before it is incorporated into a Windows Ready release.

## What it changes

- Only **published local Lyrics JSON** and an existing synchronized local `.lrc`
  companion for the selected songs.
- Original MIDI/KAR, NCN `.lyr` and `.cur`, M4A/video, and private Google Drive
  assets are **never** overwritten.
- New lyrics are **not** uploaded to Google Drive automatically. The owner
  explicitly runs the normal verified Drive upload/publish workflow afterwards.

## Operator workflow for thousands of songs

1. Open **Song Studio PC → Smart Batch / จัดการข้อความหัว–ท้ายเพลง**.
2. Choose the completed local song library and click **วิเคราะห์**. The scan
   reports songs with valid local Lyrics JSON and skipped malformed songs.
3. Choose intro/outro position (first, second, penultimate, last), optionally
   narrow matches using the full-body lyric search, and select up to 200 groups.
4. Enter one replacement line, review the exact number of songs and **lines**,
   and explicitly confirm the operation.
5. The PC engine checks each selected song again. A song with changed/corrupt
   JSON, inconsistent LRC, unsafe timing, or an unsupported encoding is skipped
   without breaking the remaining valid edits; the reason is reported.
6. Valid replacements are staged on the local disk. A **single ZIP backup and
   durable manifest** are prepared before any original JSON/LRC is changed.
7. The UI reports changed songs, changed lines, estimated line timings and
   skipped items. A full local `*.skipped.json` audit is stored beside the ZIP.
8. **Undo** rechecks hashes to avoid overwriting subsequent edits and restores
   the entire batch when the saved files still match.

## Timing policy

- Original line start and end remain fixed.
- If the number of visible units is unchanged, the original cue positions are
  reused. This does not guarantee that new words match sung audio.
- When length changes, unchanged glyphs are located using a deterministic
  Unicode-aware diff and keep their verified original timestamp.
- Only new/replaced spans are interpolated between the surrounding anchors.
- If the original timing runs backward, the line interval is invalid, or no
  time exists between fixed anchors for a new span, that song is **skipped**.
- A line with only line-level timing can use *clearly labelled* estimated
  per-glyph display timing.
- Never insert `.` or `ดนตรี>` into saved lyrics to fake missing cue times.

## Large-library safety

- Streaming disk staging avoids keeping every modified JSON and LRC body in RAM.
- Preflight checks catalog generation and selected-line counts before edits.
- SHA-256 on each source/revision detects concurrent changes at commit time.
- Cancelled or failed writes trigger rollback from the prepared ZIP; a recovery
  manifest is retained if safe rollback is impossible.
- A user editing a file after the batch cannot silently be overwritten by Undo.
- The original scan remains subject to its `MAX_ROWS=400000` guard and system
  disk capacity. Batch staging and backups need local free space.

## Verification

- `python -m unittest discover -s scripts -p 'test_songstudio_lyric_text_groups.py' -v`
- `python -m unittest discover -s scripts -p 'test_songstudio_smart_batch.py' -v`
- `python -u scripts/smart_batch_scale_smoke.py` creates a disposable **10,000
  song** library, performs a grouped edit, and verifies full-batch Undo.
- `node --check studio/app.js` and `node scripts/test_songstudio_ui_contract.mjs`

A passing test suite verifies source-level contracts on CI. A real Windows 10/11
installation, your actual NCN library, audio synchronization on Web/TV and
Google Drive accounts still require separate device/account validation.
