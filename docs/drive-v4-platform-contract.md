# XStageWeb V4 — PC, Web and Android data contract

**Authoritative write layout:** `XStageWeb/AUDIO/` (flat, immutable media and SoundFonts), `XStageWeb/LYRICS/` (timed per-song JSON, immutable catalog base/delta, and one `current.json`). These are the only two content folders created by the V4 publisher. Video sources are retained only where the corresponding validated importer supports them; no claim of browser codec support is implied by storing an original video.

**PC → Drive → Web/Android:** Song Studio PC stages validated audio/video/MIDI and real Lyrics JSON; uploads verified immutable objects, then base/delta snapshots, then switches the pointer *last*. Web and Android APK both load the hosted X-Stage player, resolve catalog file IDs and read `current.json` changes; generation changes do not interrupt an actively playing song. These pathways still require a real Google Drive permission and target-device playback test before release.

**Edits:** Changing a local Lyrics JSON never changes the published library automatically. The new verified JSON must be uploaded and its catalog row upserted before a new generation is visible on Web/Android. Unsupported, corrupt or conflicting items are excluded. The automatic editing of original NCN `.LYR/.CUR` is out of scope; conversion to a separate timed Lyrics JSON does not mutate them.

**Strict V4 only:** There are no previous-version users to support. Cloud discovery only considers `XStageWeb`; PC, Web and Android require its V4 `LYRICS/current.json` pointer and flat `AUDIO`/`LYRICS` objects. There is no legacy reader, converter or migration path. Local `StageWeb` remains an internal PC working directory, **not** an old cloud library. No Drive data is deleted automatically.

**No-pointer protection:** A folder named `AUDIO` is not proof of an empty library. Without a verified `current.json` or our staging marker, both PC and Web now refuse to create a catalog over stranded media, MIDI or video. A genuinely empty library or one containing only SoundFont files may be initialized. Do **not** delete orphan files to bypass this safeguard: inspect their origin and recover the missing pointer where possible.

**Release gate:** run the new `drive-v4-contract.yml` workflow (Linux + Windows), existing full `npm test`, Song Studio PC Drive round-trip and publishing tests, browser E2E, and Android APK tests. After green CI, manually verify on one Google account: create → publish → Web read/play → Android TV read/play → correct lyrics → republish delta → observe same words without audio timestamp drift → simulate cancellation before pointer switch. Do not assert physical device validation without testing the device.

Status: contract and guard changes are proposed on a review branch; not a published application update.
