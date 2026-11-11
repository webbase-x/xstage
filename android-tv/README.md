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
- ใช้ `sensorLandscape` เพื่อรองรับการหมุนแท็บเล็ตในแนวนอนทั้งสองด้าน
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
