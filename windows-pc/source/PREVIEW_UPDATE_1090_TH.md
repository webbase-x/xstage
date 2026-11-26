# Build 1090 — Preview updater and catalog progress

- Stable remains unavailable until signed production publication; preview is separately validated and explicitly confirmed by users.
- Preserve the registered previous installer directory, DB/data/Songs preservation flags and no forced shutdown. Older stable-only binaries still need one manual installation of 1090.
- Download progress, unique temporary directories, SHA-256 verification, and one concurrent update download. Do not launch during catalog jobs.
- Quick catalog shows actual scan throughput, ETA for scan phase only, checkpoint counts and checkpoint write errors. The existing atomic final song catalog commit is retained; progressive publication and actual 52k Drive benchmark remain pending.
- Real Windows audio, ASIO hardware, long-duration playback and update-in-place on user's hardware remain unverified.
