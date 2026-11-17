# X-Stage File Share
Android APK to send and receive files with multiple browser clients via LAN or best-effort WebRTC Internet connections.

- **Offline LAN:** scan the QR, open browser, share files directly. QR pairing key and session cookies; Android stores and opens received files locally.
- **Internet (preview):** encrypted P2P WebRTC. Uses the public PeerJS Cloud only for signaling, not file storage. WebView support varies and some NATs require a TURN relay; not a guaranteed cross-network service.
- **Android:** phones/tablets/Android TV, requires supported Android 6+ system components; test on each device. Foreground service for LAN, activity/WebView must remain active for Internet.
- **Download:** GitHub Actions artifact after branch CI; a public prerelease APK appears under Releases after merging to main.
- **Source:** [source.zip](./source.zip) expands into a standalone Gradle Android project, including JVM LAN tests and a stable public **preview-only** signing certificate. Never treat preview signing as production security.

Build action: [build-xstage-file-share.yml](../.github/workflows/build-xstage-file-share.yml). Browser Internet page: [file-share/index.html](../file-share/index.html).
