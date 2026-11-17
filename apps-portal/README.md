# X-Stage Apps Portal (Android APK)

A lightweight Android launcher for **https://webbase-x.github.io/xstage/**.
The storefront stays on the website. Opening the APK fetches that website, so **normal site
changes do not require rebuilding the APK**. Changes to native Android code do require
a new, correctly signed APK. The top-level download card for this app is hidden inside
the Android shell, while other apps remain visible.

## Supported devices

Android API 23+ with Android System WebView and an external browser, including many
phones, tablets and Android TV / Google TV boxes. Internet is required. Android TV
remote navigation follows web focus behavior. No other installation is silently performed.

## Secure Google Login in the shell

The Android WebView starts OAuth with PKCE; the Android bridge opens the *Supabase
OAuth authorization URL* in the system browser. After Google redirects to the Supabase
callback, Supabase redirects to `xstageapps://auth?code=...`, bringing the authorization
code back to this app. The JS uses `exchangeCodeForSession` with the original PKCE verifier.
**Do not put the Google login form inside WebView.** Browser and WebView storage are
distinct and cannot share sessions directly.

The Supabase Auth redirect allowlist must include `xstageapps://auth` as well as
`https://webbase-x.github.io/xstage/**`. The website must have its dedicated Supabase
URL and *public* publishable key configured in `portal-config.js`. Do not commit secrets.

## Build and publish

`gradle -p apps-portal assembleDebug` builds a developer APK.
`gradle -p apps-portal assembleRelease` builds the release APK, signed only when
the expected keystore environment variables are set.

Workflow `.github/workflows/build-xstage-apps-portal.yml` runs Android CI and
uploads a test APK artifact. A direct public download is **blocked** until a stable
signing keystore is available. GitHub Actions Secrets can be:

- `XSTAGE_PORTAL_KEYSTORE_BASE64`, `XSTAGE_PORTAL_STORE_PASSWORD`,
  `XSTAGE_PORTAL_KEY_ALIAS`, `XSTAGE_PORTAL_KEY_PASSWORD`; or
- existing shared X-Stage Android signing secrets `XSTAGE_ANDROID_KEYSTORE_BASE64`,
  `XSTAGE_ANDROID_KEYSTORE_PASSWORD`, `XSTAGE_ANDROID_KEY_ALIAS`,
  `XSTAGE_ANDROID_KEY_PASSWORD`.

The workflow verifies the APK signature and refuses to change the signing certificate
relative to an existing published feed. It publishes only a verified APK under
`downloads/` and updates `downloads/apps-portal-latest.json`. Never
publish an ephemeral debug-signed APK as an update to installed production versions.

## Portal backend

Run `supabase/xstage_portal.sql` in the **correct selected X-Stage Supabase project**.
All tables, relevant policies, indexes and triggers are prefixed `xstage_`.
After adding the public URL + publishable key to `portal-config.js`, enable the
Google provider in Supabase. Grant admins only through the SQL editor
(`xstage_admins`); mere Google sign-in never makes someone admin.

The browser records **download clicks** and optional, user-confirmed installations,
not verified Android package install events. Users can delete their recorded history.
Reviews are public-read and user-write (one per account per app); administrators can
remove inappropriate reviews. Use rate limiting, abuse reporting and retention rules
before a large public rollout.
