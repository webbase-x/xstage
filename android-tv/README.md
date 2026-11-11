# X-Stage Android TV

โปรเจกต์ Android TV ชุดเดียวสำหรับ X-Stage Karaoke Online

## ไฟล์ที่ได้จากการ build

จาก source เดียวกัน GitHub Actions สร้าง:

- `.aab` — ใช้อัปโหลด Google Play
- `.apk` — ใช้ติดตั้งตรง/ทดสอบบน TrueID TV และ Android TV
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
- ใช้ `LEANBACK_LAUNCHER`
- ไม่บังคับ touchscreen
- D-pad/remote ใช้งานได้
- WebView ใช้ hardware acceleration และเปิด X-Stage จาก GitHub Pages

## Google Login บน TV

Android TV app ไม่ใช้ Google popup ใน WebView แต่ใช้ OAuth 2.0 Device Flow:

1. ทีวีขอ user code จาก Google
2. X-Stage แสดง `google.com/device` และรหัสบนทีวี
3. ผู้ใช้อนุญาตบนมือถือ
4. TV poll token จาก Google
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
