## APK + Mobile Remote reliability and design — v1.0.77 / Build 1077

This is the Android/Web **source revision**. It is not a confirmation that the
versioned APK has been built, signed or published. The published test-APK
version is tracked separately in `downloads/android-tv-latest.json`.

- Android TV stage stays display-first, with X-Stage branding, lyrics, playback
  summary, and a larger square pairing QR anchored in separate corners.
- TV remote **MENU** or **SEARCH** opens a high-contrast, D-pad-focusable quick
  menu: display pairing QR, regenerate QR explicitly, play/pause, check updates
  and return to the stage. **Back** dismisses modal controls before exiting.
- Mobile remote has touch targets of at least 48px, a visible connection
  indicator, legible queue controls, responsive owner settings, and accessible
  keyboard tab navigation.
- Google device-login QR and mobile-remote pairing QR share the same library
  loader, so the two concurrent operations do not remove each other's script.
- Remote pairing times out until the **ready** acknowledgement arrives.
  Disconnects retry with bounded backoff, and a manual reconnect/QR scanner
  remain available. An explicit QR regenerate action can recover a broken
  pairing session.
- Each song request has a unique acknowledgement ID and an 18-second timeout;
  invalid selections, full queues, missing libraries and rate limits are
  reported on the phone. Songs requested while idle are immediately passed
  to the existing playback pipeline, with earlier requests preserved in queue.
- The Android app stores refresh tokens with AES-GCM in Android Keystore;
  old SharedPreferences plaintext tokens are migrated once, and invalidated
  tokens prompt a fresh login. The Google OAuth installed-app client identity
  must still be configured correctly; APK-embedded values are not a secret
  vault and should not be treated as private server credentials.
- **Signing matters**: the repository's public test signing key is for
  development/testing only. For production Android and Google Play, use
  separately managed private signing credentials. Do not claim that an APK
  signed with the public test key is production-trustworthy.

### Device test gate before release

1. On TrueID TV (Android 10), confirm MENU/SEARCH/DPAD/OK/Back and focus
   indicators, display legibility at 720p/1080p, device login QR and
   permanent mobile-remote QR.
2. Scan using iPhone Safari and Android Chrome; check Guest request
   and Owner verification with the same Google account as the TV.
3. Request a valid song with an empty queue: it should start loading/playing.
   Request another during playback: it should join the queue in order.
4. Test invalid song indices, delayed authorization, PeerJS outage,
   reconnection after sleep, and slow/failed QR downloads.
5. Test updates with the matching Android **test** package/signing lineage,
   then separately verify the Google Play channel and signing policy.
6. Confirm tokens, song IDs, Google Drive files and account data never
   appear in the shared QR URL; the QR carries only pairing credentials
   in the URL fragment. Verify Logout and token storage migration.

Do not mark the release as device-verified solely from syntax or source-level
regression tests.

---

## Android Studio: fix Gradle 9.6 / AGP 8.9.3 sync error

If Sync fails with `InternalProblems` removed in Gradle 9.6, the cause is an incompatible Gradle version, **not** an app Java compilation error.

Use **AGP 8.9.3 + Gradle 8.11.1 + JDK 17**. Do not upgrade the project to AGP 9 just to fix this Sync error.

1. Open **only** `android-tv/` as the Gradle project in Android Studio (not repository root `xstage/`).
2. Under **File > Settings > Build, Execution, Deployment > Build Tools > Gradle**, set **Gradle JDK = JDK 17** and select the **Gradle wrapper / gradle-wrapper.properties** distribution if the IDE supports it.
3. The pinned distribution is `android-tv/gradle/wrapper/gradle-wrapper.properties` → `gradle-8.11.1-bin.zip`. If your local checkout has not pulled that new file, run `git pull` from the repository root and re-open `android-tv/`.
4. If Android Studio cannot use the wrapper because the checked-out project lacks `gradle-wrapper.jar` or launcher scripts, generate the wrapper with an existing **Gradle 8.11.1** installation: from `android-tv` run `gradle wrapper --gradle-version 8.11.1 --distribution-type bin`. Use the resulting `gradlew.bat` and **do not commit a generated JAR without verifying its provenance**.
5. Click **Sync Project with Gradle Files**, then choose `Build > Build APK(s)` with `debug` variant.

This repo also builds Android through GitHub Actions using pinned Gradle **8.11.1**.

---

# X-Stage Android (TV + Tablet)

โปรเจกต์ Android ชุดเดียวสำหรับ X-Stage Karaoke Online รองรับทั้ง Android TV และแท็บเล็ต Android

## ไฟล์ที่ได้จากการ build

จาก source เดียวกัน GitHub Actions สร้าง:

- `.aab` — ใช้อัปโหลด Google Play
- `.apk` — ไฟล์เดียวสำหรับติดตั้งตรง/ทดสอบบน TrueID TV, Android TV และแท็บเล็ต Android
- ชื่อไฟล์เผยแพร่ใช้รูปแบบ `X-Stage-Karaoke-Android-v<version>-build<build>.apk`
- Play Store icon 512×512
- Android TV banner 320×180

Google Play ใช้ Android App Bundle (AAB) เป็นไฟล์เผยแพร่หลัก ส่วน APK ใช้สำหรับทดสอบหรือ sideload เท่านั้น

## Package name

`com.webbasex.xstage`

ชื่อนี้ควรถือเป็นค่าถาวร เพราะ package name บน Google Play เปลี่ยนภายหลังไม่ได้โดยไม่สร้างแอปใหม่

## Android compatibility

- minSdk 23 (Android 6)
- targetSdk 34 (Android 14)
- compileSdk 35
- TrueID TV Android 10 / API 29 รองรับ
- ใช้ `LEANBACK_LAUNCHER` สำหรับ TV และ `LAUNCHER` สำหรับแท็บเล็ต
- `android.software.leanback` เป็น optional จึงไม่กีดกันแท็บเล็ต
- ไม่บังคับ touchscreen; TV ใช้ D-pad/remote และแท็บเล็ตใช้ touch ได้
- ใช้ `android:screenOrientation="unspecified"` เพื่อให้แท็บเล็ตหมุนตามอุปกรณ์ได้ และ Android TV แสดงผลแนวนอนตามจอ
- WebView ใช้ hardware acceleration และเปิด X-Stage จาก GitHub Pages

## Google Login ในแอป Android

Native Android app ใช้ OAuth 2.0 Device Flow เพื่อให้ทำงานสม่ำเสมอทั้งบน TV และแท็บเล็ตโดยไม่พึ่ง popup ใน WebView:

1. ทีวีขอ user code จาก Google
2. X-Stage แสดง `google.com/device` และรหัสบนอุปกรณ์
3. ผู้ใช้อนุญาตบนมือถือ
4. แอป Android poll token จาก Google
5. ส่ง access token เข้า X-Stage web runtime
6. refresh token เก็บใน private app storage เพื่อกู้ session

ต้องสร้าง OAuth Client ใน Google Cloud Console ชนิด **TVs and Limited Input devices** แล้วเพิ่ม GitHub Secrets:

- `XSTAGE_TV_OAUTH_CLIENT_ID`
- `XSTAGE_TV_OAUTH_CLIENT_SECRET`

Scope ที่ใช้:

- `openid`
- `email`
- `https://www.googleapis.com/auth/drive.file`

## Signing สำหรับ Google Play

แนะนำเปิด **Play App Signing** และใช้ upload key ของโครงการนี้ โดยเพิ่ม GitHub Secrets:

- `XSTAGE_ANDROID_KEYSTORE_BASE64`
- `XSTAGE_ANDROID_KEYSTORE_PASSWORD`
- `XSTAGE_ANDROID_KEY_ALIAS`
- `XSTAGE_ANDROID_KEY_PASSWORD`

ถ้ายังไม่ใส่ signing secrets:
- debug APK ยังติดตั้งทดสอบได้
- release APK/AAB จะ build ได้แต่ยังไม่พร้อมอัป Play จนกว่าจะ sign ด้วย upload key

## Build APK บน Windows โดยไม่ชน Gradle 9.6

ดาวน์โหลดหรือ Pull โครงการล่าสุด จากนั้นเปิดโฟลเดอร์ `android-tv/`
แล้วดับเบิลคลิก **`Build-Debug-APK.cmd`** โดยไม่ต้องสร้างโครงการใหม่
สคริปต์จะดาวน์โหลด **Gradle 8.11.1** จากเว็บไซต์ทางการและตรวจ SHA-256
`f397b287023acdba1e9f6fc5ea72d22dd63669d59ed4a289a29b1a76eee151c6`
ก่อน Build โดยไม่ใช้ Gradle 9.6 ของ Android Studio

ต้องมี Android SDK Platform 35 และ JDK 17 หรือใหม่กว่า (สคริปต์ตรวจ
Android Studio JBR หากยังไม่กำหนด JAVA_HOME) ผลลัพธ์คือ
`android-tv/app/build/outputs/apk/debug/app-debug.apk`.

**ข้อควรระวัง:** APK ที่ Build ในเครื่องเป็น `debug` ที่ลงนามด้วย
public test key เท่านั้น ไม่ใช่ไฟล์ส่ง Google Play และจะล็อกอิน Google
Drive ไม่ได้จนกว่าจะกำหนด OAuth Client ID / Client Secret สำหรับ
**TVs and Limited Input devices** อย่างถูกต้อง

---

## Build ในเครื่อง

ต้องมี JDK 17, Android SDK 35 และ Gradle 8.11.1

```bash
gradle -p android-tv clean assembleDebug assembleRelease bundleRelease
```

ไฟล์ผลลัพธ์อยู่ที่:

```
android-tv/app/build/outputs/apk/
android-tv/app/build/outputs/bundle/
```

## หลักการอัปเดต

หน้า UI, EQ, ค้นเพลง, คิว, stage, remote และ logic ฝั่งเว็บยังอยู่ที่ GitHub Pages เดิม จึงอัปเดตเว็บได้โดยไม่ต้องส่ง Google Play ใหม่ทุกครั้ง

ต้องอัป AAB ใหม่เมื่อแก้ส่วน native เช่น:
- Android permissions / manifest
- Google TV device login bridge
- WebView/native behavior
- package/version/native code


## อัปเดต Test APK อัตโนมัติ

ตั้งแต่ X-Stage 1.0.58 เป็นต้นไป APK ทดสอบที่เผยแพร่ผ่าน GitHub Pages ใช้ test signing key แบบคงที่ เพื่อให้ Android ติดตั้งรุ่นใหม่ทับรุ่นเดิมได้

เมื่อเปิด Test APK บน TV หรือแท็บเล็ต:
1. แอปตรวจ `downloads/android-tv-latest.json` อัตโนมัติ และตรวจซ้ำเป็นระยะ
2. ถ้ามี build ใหม่กว่า จะแจ้งบนหน้าจออุปกรณ์
3. กด **อัปเดตตอนนี้**
4. ครั้งแรก Android อาจให้อนุญาต “ติดตั้งแอปที่ไม่รู้จัก” สำหรับ X-Stage
5. แอปดาวน์โหลด APK จาก GitHub Pages
6. ตรวจ SHA-256 ก่อนเปิด Android Package Installer
7. ผู้ใช้ยืนยันติดตั้งตามข้อกำหนดของ Android

สิทธิ์ `REQUEST_INSTALL_PACKAGES` อยู่เฉพาะ debug/Test APK ผ่าน `src/debug/AndroidManifest.xml` เท่านั้น ไม่ถูกรวมใน Google Play release AAB

**สำคัญ:** APK 1.0.57 และเก่ากว่าเคยใช้ debug signing key ที่สร้างใหม่บน CI จึงต้องถอนการติดตั้งรุ่นเก่าแล้วติดตั้ง 1.0.58 หนึ่งครั้ง หลังจากนั้น Test APK รุ่นใหม่สามารถอัปเดตทับกันได้
