# Smart Batch Lyrics Correction — safety-first engine (LRC phase)

This is a **standalone Node.js 20+ desktop batch engine**, not yet a Song Studio PC UI integration or a Windows installer. It runs offline. It does not contact AI providers, Google Drive or external services. Current correction is deterministic literal replacement using user-reviewed rules; do not describe it as AI transcription or automatically verified spelling.

## Examples

Create a UTF-8 file \`rules.json\`:

\`\`\`json
[
  {"from": "เนื้อรอง", "to": "เนื้อร้อง"},
  {"from": "คำผิดตัวอย่าง", "to": "คำที่ถูกต้อง"}
]
\`\`\`

Preview (default, **no writes**):

\`\`\`sh
node tools/smart-batch-lyrics.mjs --root="D:/Songs" --rules=rules.json
\`\`\`

Apply reviewed rules:

\`\`\`sh
node tools/smart-batch-lyrics.mjs --root="D:/Songs" --rules=rules.json --apply
\`\`\`

The output includes \`runId\`. Roll back a run:

\`\`\`sh
node tools/smart-batch-lyrics.mjs --root="D:/Songs" --undo=RUN_ID
\`\`\`

## Guarantees and limitations

- Only \`.lrc\` is eligible for changes. \`.lyr\`, \`.cur\`, \`.json\`, MIDI and media are **not modified**. NCN per-character timing must have its own parser, CUR monotonicity and visible-glyph count checks before it can be safely enabled.
- LRC time tags and metadata are preserved verbatim; only text after the time tags is replaced. Existing order and structure must validate. Malformed/backward files are skipped.
- No synthetic timestamps, retiming, overwriting from Google Drive or release catalog updates.
- Default dry-run; \`--apply\` required for writes. Original bytes saved under \`.xstage-lyrics-backup/RUN_ID/files/\` before modifications, with SHA-256 journal. Each edited file is validated after writing. Undo only touches a file if its current hash matches the recorded post-edit hash; manual subsequent edits are preserved.
- Files larger than 4 MiB, non-UTF-8, symbolic links and suspicious content are excluded or skipped. Backup directory is excluded from scans. Errors do not abort unrelated files.
- **Do not delete the backup directory until rollback is no longer needed.** This phase does not promise crash-safe recovery for every filesystem, transactional updating of the entire song catalog, or corrected Thai spellings without reviewed replacement rules.
- For very large libraries, run first against a COPY of a representative set and review the summary. No song data is bundled in the repository.

Run: \`node --test scripts/smart-batch-lyrics.test.mjs\`.
