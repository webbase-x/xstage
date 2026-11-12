# X-Stage Song Studio — Online UI

**Public UI:** https://webbase-x.github.io/xstage/studio/

The files `index.html`, `app.js`, and `style.css` are identical to
the UI bundled in the **X-Stage Song Studio Windows v0.2.5 Build 205** source.

## Using it

This website is a control panel, not a remote rendering server.
It does not upload or process your music on GitHub Pages.

1. Start the v0.2.5+ Local Engine on the Windows PC.
2. Click **เปิด Web Control** in the desktop app, or run
   `Run-Song-Studio-Web.vbs`.
3. The PC creates an unguessable per-session token and opens the
   online UI with a pairing link in the URL fragment only.
4. Click **เชื่อมต่อ Engine บน PC เครื่องนี้**. When Chrome/Edge requests
   local/loopback network permission, allow the connection.
5. Work in the online UI, while the local Windows Engine runs song
   conversion, SoundFont, file and Drive operations.

The Local API listens on `127.0.0.1` only, requires a strong bearer
token, and accepts cross-origin requests only from
`https://webbase-x.github.io`. It does not allow arbitrary websites to
read your private song library. Pairing credentials are never sent to
the GitHub Pages server; the URL fragment is erased after loading.

**Current limitation:** Opening this public link directly on a phone,
tablet or different PC displays the UI and setup screen, but cannot
control the original Windows PC. Cross-device remote access requires a
separate authenticated HTTPS relay/tunnel with explicit owner pairing.
Never publicly forward a Local Engine port.

To keep the PC and Web layouts identical, change the canonical UI in
`songstudio/web/` inside the Windows source and deploy the same three
files to this directory. If they drift, the two modes may be incompatible.
