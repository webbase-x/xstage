# X-Stage Mirror TV: signing and release channels

## Current channels

- **Production-signed APK**: `.github/workflows/release-xstage-mirror-tv.yml` (manually dispatched only). Requires four encrypted GitHub Actions secrets. Only this build updates `mirror-tv/latest.json` and can participate in in-app automatic updates. No unsigned or preview-signed APK can be promoted to this feed.
- **Test APK (Build 108+)**: `.github/workflows/build-xstage-mirror-tv.yml`. Assembles the pinned GPLv3 receiver as a **non-debuggable release variant**, signs with the SAME **private persistent** key as the official production channel, verifies the signing certificate fingerprint and APK version, publishes a prerelease and corresponding GPLv3 source and SHA-256, and writes `mirror-tv/test-latest.json`. This channel now **requires** the same four private signing secrets as production and fails closed if any is missing. No debug-signed fallback or private signing material is published. Older Builds 107 and below were debug-signed by CI and are NOT guaranteed to match the new identity.

## Configure official production signing (repository owner required)

In [GitHub Actions repository secrets](https://github.com/webbase-x/xstage/settings/secrets/actions) add these **four** secrets. Never paste values in an issue, commit, public logs or a chat:

1. `XSTAGE_MIRROR_KEYSTORE_BASE64`: Base64 of the encrypted Android signing keystore (.jks), generated locally and kept backed up offline.
2. `XSTAGE_MIRROR_STORE_PASSWORD`: Password of that keystore.
3. `XSTAGE_MIRROR_KEY_ALIAS`: Alias of the Android signing key.
4. `XSTAGE_MIRROR_KEY_PASSWORD`: Password for the signing key.

On Windows, a first-time owner can generate a new signing keystore on a **private** machine with Android Studio/JDK's `keytool`. For example, create `C:\\secure` privately, then run the following command in PowerShell. Choose strong passwords when prompted and never share them in chat:

```powershell
keytool -genkeypair -keystore C:\\secure\\XStageMirrorRelease.jks -storetype PKCS12 -alias xstage-mirror -keyalg RSA -keysize 3072 -validity 10000 -dname "CN=X-Stage Mirror TV, O=X-Stage"
```

Keep a durable private backup of that one keystore and its passwords; losing them prevents in-place updates of subsequent APKs. For PKCS12, the store and key passwords may be the same (GitHub still requires both secret fields). You can obtain Base64 locally with PowerShell:
```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("C:\secure\XStageMirrorRelease.jks")) |
    Set-Clipboard
```
Paste the clipboard value into the encrypted secret in GitHub (not a repo file).

After configuring all four, rerun **X-Stage Mirror TV - AirPlay APK** on the `main` branch to publish the first persistent-key preview (v0.2.6 Build 108 or later). This step intentionally cannot be performed until the secrets exist. Also note that the 0.2.5 / Build 107 legacy debug APK cannot inherit the new signing identity: a one-time uninstall may be necessary. For subsequent production releases, manually dispatch the **Release X-Stage Mirror TV signed APK** workflow from the Actions tab. It checks the secrets, builds and verifies the release signature, publishes an immutable release with corresponding GPLv3 source and only then activates `mirror-tv/latest.json`.

Do not attempt to reuse a Karaoke Android signing key, ship passwords or keys in public source, or copy the test APK into the production feed. The app package name is `com.webbasex.xstagemirror.tv` and should retain the **same signing identity** for future production updates.

## Preview availability notifications

Starting with v0.2.5 (Build 107), the installed app checks the signed `latest.json` channel and also the separately published `test-latest.json` channel at startup. The preview channel announces newer versions, but **never attempts an in-place preview install**. Debug signing identities may change across CI runners, so the Android package installer can refuse to install a preview over a previous preview. The app explains this risk and offers the X-Stage first-party APK URL. Uninstalling the previous app can erase settings, such as the receiver name. Existing v0.2.4 or older apps lack this preview check and need a one-time manual download and reinstall before the new prompt will appear.

## Stable signing and in-place updates for TrueID / Android TV

1. The repository owner creates ONE dedicated signing keystore locally, backs it up securely, and configures the four GitHub Actions Secrets above. Do not enter the keystore contents or passwords in ChatGPT or a public GitHub issue.
2. The test/prerelease and official release workflows use the same keystore identity. The first successful signed preview records a **public SHA-256 certificate fingerprint** as `signer_sha256` in `mirror-tv/test-latest.json`. Later preview builds reject any differing fingerprint.
3. The installed app (Build 108+) checks `latest.json` and `test-latest.json` when opened. For a newer persistent preview, it compares the **actual installed Android signing certificate** against the published fingerprint. Only matching signatures enable a checked APK download and Android's standard user-confirmed in-place installer; a mismatch prompts a manual download with an explanation of the one-time migration.
4. Previously issued debug APKs (Build 107 or older) are not re-signable to match any new key without access to their original private keys. Android does not allow bypassing the signature continuity requirement. Back up preferences and use a one-time uninstall if that transition is required.

**Do not** put `.jks`, passwords, `local.properties`, signing environment dumps, or keystore bundles in source archives, logs, public workflow artifacts, or the web download directory. The workflow excludes these from its GPLv3 source archive. The certificate fingerprint itself is public, not a secret.
