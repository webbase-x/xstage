# X-Stage Download Manager — Implementation and Release Gates

Scope: Enhance the **existing** `download-manager/` application in `webbase-x/xstage`. Never replace it with a new unrelated product. The public download remains **one Windows x64 Setup EXE**. The installer may remain unsigned until an independently verified code-signing certificate is provisioned. Never claim an EXE is released until GitHub Actions, GitHub Release asset and public SHA-256 feed all agree.

## Gate for every milestone

1. Preserve installed users' data, existing output media and prior working capabilities.
2. Compile and run deterministic .NET integration tests on GitHub Actions Windows runner, including failure/recovery cases.
3. Validate real downloaded bytes for HTTP, full media streams using FFprobe/FFmpeg, and verified SHA-256 for update binaries. Do not mark partial media Completed.
4. Package verified self-contained Windows EXE; require successful GitHub Release asset publication and matching public update manifest.
5. Clearly distinguish CI verification from real-device field testing. If field testing is absent, state that explicitly.
6. Progress is visible; no silent indefinite waits, hidden failures, automatic execution of downloaded files or bypassing protected media.

## Ordered work

- [x] **01 — Transactional state** (v0.2.16 Build 19): SQLite WAL, `xstage_download_jobs`, `xstage_download_chunks`, `xstage_download_settings`; migration from old `downloads.json` while keeping original; per-chunk checkpoints; transaction rollback and crash-reopen tests. Live-device migration test still needed.
- [x] **02 — Fault-tolerant HTTP transfer** (v0.2.17 Build 20): verified per-chunk retry/resume after disconnection, 45s network idle deadline, exponential backoff, HTTP 503 Retry-After, permanent-error classification, validated Range-to-HTTP-200 fallback and configurable retry count (1–10) persisted to SQLite. GitHub Actions [run 44730562080](https://github.com/webbase-x/xstage/actions/runs/44730562080) passed, verified EXE asset and SHA-256 manifest published. Real-world intermittent network testing remains necessary.
- [ ] **03 — Adaptive performance** (major capabilities released in v0.2.19 Build 22): global/per-host job limits (1–8), priority aging, cancellation-safe slot scheduler, per-job/global native-HTTP bandwidth caps, SQLite persistence and EWMA speed/ETA. GitHub Actions [run 44739622315](https://github.com/webbase-x/xstage/actions/runs/44739622315) succeeded, the verified [Build 22 installer](https://github.com/webbase-x/xstage/releases/tag/xstage-download-manager-v0.2.19-build22-preview) and public SHA-256 manifest agree. **Still pending before fully checked:** measured backpressure on 1/8/32 ranges, dynamic throughput-driven segment count, unified throttling across native HTTP and yt-dlp, and real-device field tests.
- [ ] **04 — Queue scheduler and power/network recovery**: multiple named queues, calendar/time windows, auto-resume on network restoration / sleep resume, durable transitions without duplicate work.
- [ ] **05 — Media acquisition**: robust manifest recognition HLS/DASH, quality/bitrate, multi-audio/subtitle/metadata choice, safe remux/transcode and resume; yt-dlp plugin updates tested independently; no DRM bypass.
- [ ] **06 — Integrity and disk safety**: user-supplied SHA-256/SHA-1/MD5 (weak algorithms only for compatibility; avoid implying collision resistance), disk preflight and low-disk pause, atomic final naming, stable server identity, verified media output, duplicate policy.
- [ ] **07 — Automation and organization**: optional category/routing rules, safe batch URL import/pattern expansion, clipboard filters, user-approved post-download actions (no implicit shell execution), browser-native message registration and session permissions.
- [ ] **08 — Diagnostics and observability**: per-chunk progress, smoothed speed/ETA and network errors, per-job structured logs, exportable diagnostics with sensitive URL tokens redacted, crash reports and accessibility / high-DPI checks.
- [ ] **09 — Desktop separation/CLI**: extract download orchestrator into independent testable core; optional headless/CLI and authorized local API without exposing a public network server.
- [ ] **10 — Release hardening**: failure-safe rollback to previous verified installed version; digitally sign app, setup and uninstaller with publisher-authorized certificate and timestamp; protected update manifest, signature verification and manual Windows field tests.
- [ ] **11 — Optional protocols**: SFTP/FTP and BitTorrent/Magnet only after explicit design review of security, privacy, tracker exposure, licensing and sandboxing.
- [ ] **12 — Final full regression**: all milestones jointly exercised on real Windows 10/11 with DPI and sleep/network/storage edge cases, signed update from an older version, interrupted update rollback, large transfers, multiple platform video samples with rights to download.

## Durable engineering rules

- Treat the physical `.part` byte count as the authority for resume; never append a mismatched HTTP 206/200 response or merge fragments with different validators.
- SQLite checkpoints must be transactional. Never delete the original legacy JSON or an existing completed file as part of migration/retry.
- Limit site rate/fragment concurrency and honor retry windows. Reject unsafe, expired or unauthorized media URLs instead of bypassing authentication.
- UI sorting and filtering must not mutate the queue, overwrite files or cause actions on the wrong job.
- Release every milestone independently with tests and verifiable EXE checksum; proceed to the next implementation only after the preceding gate passes.
