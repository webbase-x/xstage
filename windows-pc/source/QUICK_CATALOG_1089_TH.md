# v1.0.89 / Build 1089 — Quick catalog I/O

- Read and validate media in eight worker threads, bounded to 32 outstanding files. SQLite writes and metadata merge remain single-threaded.
- Cache trusted raw metadata every batch in the existing fast catalog cache; resume only with the same reader revision and complete trusted signature. Reapply current catalog hints and user edits.
- Preserve atomic final catalog transaction and final signature revalidation. No automatic copies, hidden duplicates or deletions. Cancellation retains checkpoints, not partially published songs.
- Windows regression, installer and verified unsigned preview publication remain gated by existing workflows. Actual Google Drive latency and speedup require measurement on a real installation.
