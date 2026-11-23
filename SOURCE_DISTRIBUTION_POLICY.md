# X-Stage distribution access policy

## Public users

The X-Stage Apps website lets everyone view app descriptions and use web apps, but only shows installer download buttons to a Google-signed-in owner account (`teacher.phairat@gmail.com`). This is a **storefront visibility rule only**, not authorization for the files themselves. For that account, the UI displays installable downloads **only** as SHA-256-verified Windows `.exe` and Android `.apk` files, with honest release-channel notices. If a verified binary is unavailable, its download button stays hidden or disabled; do not link end users to source ZIPs, portable ZIPs, GitHub Actions artifacts, or unverified installers as a replacement. Browser-based apps may still be opened from the website. Each download button shows the application's own artwork. The binary itself must carry a branded application/launcher icon (Windows PE icon resources and Android launcher resources). This is a storefront distribution policy, not a prohibition on legally required source availability.

Because GitHub Pages and GitHub Releases currently serve these binaries at public URLs, anyone who already has a direct URL can still download them. Preventing direct downloads requires moving installers to private storage and checking the authenticated Google identity on a server or in a storage policy before issuing an expiring signed URL. Never claim the current client-side filter prevents access to a known public URL.

## Restricted developer source

Only the two explicitly authorized developer accounts identified privately by the project owner are intended to receive proprietary source-only distributions. Their email addresses must NOT be used as a client-side JavaScript allowlist or publicly committed as an access-control substitute.

**Current limitation:** webbase-x/xstage is a PUBLIC repository; all committed source remains accessible to anyone through GitHub, including past revisions. Disabling source ZIP workflows, hiding download links, or deleting files from a new commit does NOT revoke access to existing history, forks, cached archives, or the repository itself. No restricted developer access is claimed until the owner creates a private source repository and assigns access to the GitHub accounts belonging to the two approved email addresses. A separate public distribution repository or build-only Pages deployment is required to keep the consumer website and binaries accessible to everyone. Any browser-delivered JavaScript/HTML remains visible to its recipients and cannot be made proprietary by a UI login gate.

**Migration checklist:** back up the original repository; establish a private source repository with authorized collaborators; preserve a separate public application/distribution website; move source-only release assets and build workflows to the private repository; review historical public source exposure; keep all binary release manifests pointing only to valid, verified public artifacts; maintain license notices and corresponding source for third-party copyleft components.

## Third-party GPLv3 components

X-Stage Mirror TV includes a derivative of GPLv3 AirShow/UxPlay. For publicly distributed binaries, corresponding GPLv3 source and notices must remain available to recipients on comparable terms. It must NOT be placed behind an owner-only gate. Mirror TV test and production release workflows intentionally ship an accompanying GPLv3 source archive.

## Access requests

Do not show unpublished source downloads to general visitors. Real authorization needs server-side validation of GitHub collaborator permissions and/or validated Google identity in a private storage backend. A text-based email check in the public storefront is not an access control mechanism.
