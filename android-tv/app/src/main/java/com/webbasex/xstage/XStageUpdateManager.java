package com.webbasex.xstage;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class XStageUpdateManager {
    interface Listener {
        void onUpdateAvailable(String version, int build);
        void onUpdateStatus(String message);
        void onUpdateError(String message);
        void onNoUpdate();
    }

    private static final long CHECK_INTERVAL_MS = 6L * 60L * 60L * 1000L;
    private static final long DOWNLOAD_POLL_MS = 850L;
    private static final String APK_MIME = "application/vnd.android.package-archive";

    private final Activity activity;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    private volatile LatestUpdate latest;
    private volatile boolean closed;
    private boolean waitingInstallPermission;
    private long lastCheckAt;
    private long activeDownloadId = -1L;
    private File activeDownloadFile;

    XStageUpdateManager(Activity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
    }

    void checkForUpdates(boolean force) {
        if (!BuildConfig.DEBUG || closed) return;
        long now = System.currentTimeMillis();
        if (!force && now - lastCheckAt < CHECK_INTERVAL_MS) return;
        lastCheckAt = now;

        executor.execute(() -> {
            try {
                LatestUpdate update = fetchLatest();
                if (closed) return;
                latest = update;
                if (update.build > BuildConfig.VERSION_CODE) {
                    main.post(() -> listener.onUpdateAvailable(update.version, update.build));
                } else {
                    main.post(listener::onNoUpdate);
                }
            } catch (Exception e) {
                if (!closed) main.post(() -> listener.onUpdateError(readable(e)));
            }
        });
    }

    void installLatestUpdate() {
        if (!BuildConfig.DEBUG || closed) return;
        LatestUpdate update = latest;
        if (update == null || update.build <= BuildConfig.VERSION_CODE) {
            listener.onUpdateStatus("กำลังตรวจสอบเวอร์ชันล่าสุด…");
            checkForUpdates(true);
            return;
        }
        if (!canRequestPackageInstalls()) {
            waitingInstallPermission = true;
            listener.onUpdateStatus("อนุญาตให้ X-Stage ติดตั้งแอปจากแหล่งนี้ก่อน แล้วระบบจะอัปเดตต่ออัตโนมัติ");
            try {
                Intent settings = new Intent(
                        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + activity.getPackageName())
                );
                activity.startActivity(settings);
            } catch (Exception e) {
                waitingInstallPermission = false;
                listener.onUpdateError("เปิดหน้าตั้งค่าอนุญาตติดตั้ง APK ไม่สำเร็จ");
            }
            return;
        }
        download(update);
    }

    void onResume() {
        if (!BuildConfig.DEBUG || closed) return;
        if (waitingInstallPermission) {
            if (canRequestPackageInstalls()) {
                waitingInstallPermission = false;
                LatestUpdate update = latest;
                if (update != null && update.build > BuildConfig.VERSION_CODE) {
                    main.post(() -> listener.onUpdateStatus("ได้รับสิทธิ์แล้ว · กำลังดาวน์โหลดอัปเดต…"));
                    download(update);
                }
            }
        } else {
            checkForUpdates(false);
        }
    }

    void close() {
        closed = true;
        executor.shutdownNow();
        main.removeCallbacksAndMessages(null);
    }

    private boolean canRequestPackageInstalls() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return true;
        PackageManager pm = activity.getPackageManager();
        return pm.canRequestPackageInstalls();
    }

    private LatestUpdate fetchLatest() throws Exception {
        String endpoint = BuildConfig.XSTAGE_WEB_URL + "downloads/android-tv-latest.json?t=" + System.currentTimeMillis();
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
        connection.setRequestMethod("GET");
        connection.setConnectTimeout(12000);
        connection.setReadTimeout(12000);
        connection.setUseCaches(false);
        connection.setRequestProperty("Cache-Control", "no-cache");
        int code = connection.getResponseCode();
        InputStream stream = code >= 200 && code < 300
                ? connection.getInputStream()
                : connection.getErrorStream();
        StringBuilder body = new StringBuilder();
        if (stream != null) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) body.append(line);
            }
        }
        connection.disconnect();
        if (code < 200 || code >= 300) throw new IllegalStateException("ตรวจเวอร์ชันไม่สำเร็จ (HTTP " + code + ")");

        JSONObject json = new JSONObject(body.toString());
        int build = json.optInt("build", 0);
        String version = json.optString("version", "");
        String file = json.optString("file", "");
        String sha256 = json.optString("sha256", "").toLowerCase(Locale.ROOT);
        if (build <= 0 || version.isEmpty()) {
            throw new IllegalStateException("ข้อมูลเวอร์ชัน APK ไม่สมบูรณ์");
        }
        if (file.isEmpty()) {
            file = "X-Stage-Karaoke-Android-v" + version + "-build" + build + ".apk";
        }
        String apkUrl = BuildConfig.XSTAGE_WEB_URL + "downloads/" + Uri.encode(file, "/");
        return new LatestUpdate(version, build, apkUrl, sha256, file);
    }

    private void download(LatestUpdate update) {
        if (activeDownloadId >= 0L || closed) return;
        try {
            File directory = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);
            if (directory == null) throw new IllegalStateException("อุปกรณ์ไม่มีพื้นที่ดาวน์โหลดสำหรับอัปเดต");
            if (!directory.exists() && !directory.mkdirs()) {
                throw new IllegalStateException("สร้างโฟลเดอร์อัปเดตไม่สำเร็จ");
            }
            File target = new File(directory, "X-Stage-Karaoke-Android-TV-" + update.version + ".apk");
            if (target.exists() && !target.delete()) {
                throw new IllegalStateException("ลบไฟล์อัปเดตเก่าไม่สำเร็จ");
            }

            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(update.apkUrl + "?build=" + update.build));
            request.setTitle("X-Stage Karaoke " + update.version);
            request.setDescription("กำลังดาวน์โหลดอัปเดต Android TV");
            request.setMimeType(APK_MIME);
            request.setAllowedOverMetered(true);
            request.setAllowedOverRoaming(true);
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE);
            request.setDestinationInExternalFilesDir(activity, Environment.DIRECTORY_DOWNLOADS, target.getName());

            DownloadManager manager = (DownloadManager) activity.getSystemService(Context.DOWNLOAD_SERVICE);
            if (manager == null) throw new IllegalStateException("ระบบดาวน์โหลดของ Android ไม่พร้อม");
            activeDownloadId = manager.enqueue(request);
            activeDownloadFile = target;
            listener.onUpdateStatus("กำลังดาวน์โหลด X-Stage " + update.version + "…");
            pollDownload(manager, update);
        } catch (Exception e) {
            activeDownloadId = -1L;
            activeDownloadFile = null;
            listener.onUpdateError(readable(e));
        }
    }

    private void pollDownload(DownloadManager manager, LatestUpdate update) {
        main.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (closed || activeDownloadId < 0L) return;
                DownloadManager.Query query = new DownloadManager.Query().setFilterById(activeDownloadId);
                try (Cursor cursor = manager.query(query)) {
                    if (cursor == null || !cursor.moveToFirst()) {
                        failDownload("ไม่พบสถานะไฟล์อัปเดต");
                        return;
                    }
                    int statusIndex = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS);
                    int reasonIndex = cursor.getColumnIndex(DownloadManager.COLUMN_REASON);
                    long status = statusIndex >= 0 ? cursor.getLong(statusIndex) : DownloadManager.STATUS_FAILED;
                    if (status == DownloadManager.STATUS_SUCCESSFUL) {
                        long id = activeDownloadId;
                        activeDownloadId = -1L;
                        verifyAndInstall(manager, id, update);
                        return;
                    }
                    if (status == DownloadManager.STATUS_FAILED) {
                        long reason = reasonIndex >= 0 ? cursor.getLong(reasonIndex) : -1L;
                        failDownload("ดาวน์โหลดอัปเดตไม่สำเร็จ (" + reason + ")");
                        return;
                    }
                } catch (Exception e) {
                    failDownload(readable(e));
                    return;
                }
                main.postDelayed(this, DOWNLOAD_POLL_MS);
            }
        }, DOWNLOAD_POLL_MS);
    }

    private void verifyAndInstall(DownloadManager manager, long id, LatestUpdate update) {
        listener.onUpdateStatus("ดาวน์โหลดเสร็จแล้ว · กำลังตรวจสอบไฟล์…");
        executor.execute(() -> {
            try {
                File file = activeDownloadFile;
                if (file == null || !file.isFile()) throw new IllegalStateException("ไม่พบไฟล์ APK ที่ดาวน์โหลด");
                if (!update.sha256.isEmpty()) {
                    String actual = sha256(file);
                    if (!actual.equalsIgnoreCase(update.sha256)) {
                        file.delete();
                        throw new IllegalStateException("ไฟล์อัปเดตไม่ผ่านการตรวจสอบ SHA-256");
                    }
                }
                Uri uri = manager.getUriForDownloadedFile(id);
                if (uri == null) throw new IllegalStateException("Android ไม่คืน URI ของไฟล์อัปเดต");
                main.post(() -> launchInstaller(uri, update.version));
            } catch (Exception e) {
                main.post(() -> listener.onUpdateError(readable(e)));
            } finally {
                activeDownloadFile = null;
            }
        });
    }

    private void launchInstaller(Uri uri, String version) {
        listener.onUpdateStatus("พร้อมติดตั้ง X-Stage " + version + " · ยืนยันในหน้าติดตั้งของ Android");
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, APK_MIME);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            activity.startActivity(intent);
        } catch (Exception e) {
            listener.onUpdateError("เปิดตัวติดตั้ง Android ไม่สำเร็จ");
        }
    }

    private void failDownload(String message) {
        activeDownloadId = -1L;
        activeDownloadFile = null;
        listener.onUpdateError(message);
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) > 0) digest.update(buffer, 0, read);
        }
        StringBuilder out = new StringBuilder();
        for (byte b : digest.digest()) out.append(String.format(Locale.ROOT, "%02x", b));
        return out.toString();
    }

    private static String readable(Exception e) {
        String message = e.getMessage();
        return message == null || message.trim().isEmpty()
                ? "อัปเดต X-Stage ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่"
                : message;
    }

    private static final class LatestUpdate {
        final String version;
        final int build;
        final String apkUrl;
        final String sha256;
        final String fileName;

        LatestUpdate(String version, int build, String apkUrl, String sha256, String fileName) {
            this.version = version;
            this.build = build;
            this.apkUrl = apkUrl;
            this.sha256 = sha256;
            this.fileName = fileName;
        }
    }
}
