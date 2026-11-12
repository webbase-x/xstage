package com.webbasex.xstage;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

final class GoogleDeviceAuth {
    interface Listener {
        void onDeviceCode(String userCode, String verificationUrl, long expiresInSeconds);
        void onStatus(String message);
        void onToken(String accessToken, long expiresInSeconds);
        void onError(String message);
        void onSignedOut();
    }

    private static final String DEVICE_ENDPOINT = "https://oauth2.googleapis.com/device/code";
    private static final String TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token";
    private static final String REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke";
    private static final String SCOPE = "openid email https://www.googleapis.com/auth/drive.file";

    private final GoogleTokenStore tokenStore;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());
    // A cancelled Google HTTP call may remain in socket read until timeout.
    // A fresh login must not sit behind that cancelled call in a single queue.
    private final ExecutorService executor = Executors.newCachedThreadPool();
    private final AtomicInteger generation = new AtomicInteger();
    private Future<?> activeAuthJob;

    // A previous OAuth device poll can sleep for several seconds. Interrupt it
    // when Cancel/Retry is pressed so the next QR request never waits behind it.
    private void cancelActiveJob() {
        Future<?> job = activeAuthJob;
        activeAuthJob = null;
        if (job != null) job.cancel(true);
    }

    GoogleDeviceAuth(Context context, Listener listener) {
        this.tokenStore = new GoogleTokenStore(context);
        this.listener = listener;
    }

    boolean hasStoredSession() {
        String refreshToken = tokenStore.read();
        return refreshToken != null && !refreshToken.isEmpty();
    }

    synchronized void startDeviceLogin() {
        final int run = generation.incrementAndGet();
        cancelActiveJob();
        if (!configured()) {
            error(run, "ยังไม่ได้ตั้งค่า Google OAuth สำหรับ Android build: ต้องมี XSTAGE_TV_OAUTH_CLIENT_ID และ XSTAGE_TV_OAUTH_CLIENT_SECRET แล้ว Build APK ใหม่");
            return;
        }
        status(run, "กำลังสร้างรหัสสำหรับเข้าสู่ระบบผ่านมือถือ…");
        activeAuthJob = executor.submit(() -> {
            try {
                JSONObject code = postForm(DEVICE_ENDPOINT, mapOf(
                        "client_id", BuildConfig.XSTAGE_TV_OAUTH_CLIENT_ID,
                        "scope", SCOPE
                ));
                if (!isCurrent(run)) return;

                String deviceCode = code.optString("device_code");
                String userCode = code.optString("user_code");
                String verificationUrl = code.optString("verification_url", "https://www.google.com/device");
                long expiresIn = code.optLong("expires_in", 1800L);
                long interval = Math.max(5L, code.optLong("interval", 5L));

                if (deviceCode.isEmpty() || userCode.isEmpty()) {
                    throw new IllegalStateException(readError(code, "Google ไม่ส่งรหัสอุปกรณ์กลับมา"));
                }

                main.post(() -> { if (isCurrent(run)) listener.onDeviceCode(userCode, verificationUrl, expiresIn); });
                pollToken(run, deviceCode, expiresIn, interval);
            } catch (Exception e) {
                if (isCurrent(run)) error(run, readable(e));
            }
        });
    }

    synchronized void restoreSession() {
        final int run = generation.incrementAndGet();
        cancelActiveJob();
        String refreshToken = tokenStore.read();
        if (refreshToken == null || refreshToken.isEmpty()) {
            error(run, "ไม่มีเซสชัน Google ที่บันทึกไว้ · กรุณาเข้าสู่ระบบผ่าน QR ใหม่");
            return;
        }
        if (!configured()) {
            error(run, "ยังไม่ได้ตั้งค่า Google OAuth สำหรับ Android build · โปรดตรวจสอบ APK และการตั้งค่าผู้ดูแล");
            return;
        }
        status(run, "กำลังกู้คืนการเชื่อมต่อ Google Drive…");
        activeAuthJob = executor.submit(() -> {
            try {
                JSONObject token = postForm(TOKEN_ENDPOINT, mapOf(
                        "client_id", BuildConfig.XSTAGE_TV_OAUTH_CLIENT_ID,
                        "client_secret", BuildConfig.XSTAGE_TV_OAUTH_CLIENT_SECRET,
                        "refresh_token", refreshToken,
                        "grant_type", "refresh_token"
                ));
                if (!isCurrent(run)) return;
                String accessToken = token.optString("access_token");
                if (accessToken.isEmpty()) {
                    String code = token.optString("error");
                    if ("invalid_grant".equals(code)) tokenStore.clear();
                    throw new IllegalStateException(readError(token, "กู้คืน Google Login ไม่สำเร็จ"));
                }
                long expiresIn = token.optLong("expires_in", 3600L);
                main.post(() -> { if (isCurrent(run)) listener.onToken(accessToken, expiresIn); });
            } catch (Exception e) {
                if (isCurrent(run)) error(readable(e));
            }
        });
    }

    synchronized void logout() {
        final int run = generation.incrementAndGet();
        cancelActiveJob();
        String refreshToken = tokenStore.read();
        tokenStore.clear();
        if (refreshToken == null || refreshToken.isEmpty()) {
            main.post(() -> { if (isCurrent(run)) listener.onSignedOut(); });
            return;
        }
        executor.execute(() -> {
            try {
                postForm(REVOKE_ENDPOINT, mapOf("token", refreshToken));
            } catch (Exception ignored) {
                // Local sign-out still completes even if Google is temporarily unreachable.
            }
            if (isCurrent(run)) main.post(() -> { if (isCurrent(run)) listener.onSignedOut(); });
        });
    }

    synchronized void cancel() {
        generation.incrementAndGet();
        cancelActiveJob();
        // The hosted UI owns Cancel feedback. A stale native callback must
        // not re-open QR Login after the user has dismissed it.
    }

    synchronized void close() {
        generation.incrementAndGet();
        cancelActiveJob();
        executor.shutdownNow();
    }

    private void pollToken(int run, String deviceCode, long expiresIn, long intervalSeconds) throws Exception {
        long deadline = System.currentTimeMillis() + expiresIn * 1000L;
        long interval = intervalSeconds;

        while (isCurrent(run) && System.currentTimeMillis() < deadline) {
            Thread.sleep(interval * 1000L);
            if (!isCurrent(run)) return;

            JSONObject token = postForm(TOKEN_ENDPOINT, mapOf(
                    "client_id", BuildConfig.XSTAGE_TV_OAUTH_CLIENT_ID,
                    "client_secret", BuildConfig.XSTAGE_TV_OAUTH_CLIENT_SECRET,
                    "device_code", deviceCode,
                    "grant_type", "urn:ietf:params:oauth:grant-type:device_code"
            ));
            // Cancellation can happen while the HTTP request is on the wire.
            // Never save a refresh token from a cancelled QR session.
            if (!isCurrent(run)) return;

            String accessToken = token.optString("access_token");
            if (!accessToken.isEmpty()) {
                String refreshToken = token.optString("refresh_token");
                if (!refreshToken.isEmpty()) tokenStore.write(refreshToken);
                long tokenExpires = token.optLong("expires_in", 3600L);
                main.post(() -> { if (isCurrent(run)) listener.onToken(accessToken, tokenExpires); });
                return;
            }

            String code = token.optString("error");
            if ("authorization_pending".equals(code)) {
                status(run, "รอการอนุญาตจากมือถือ…");
                continue;
            }
            if ("slow_down".equals(code)) {
                interval += 5L;
                continue;
            }
            if ("access_denied".equals(code)) throw new IllegalStateException("ผู้ใช้ไม่อนุญาตการเข้าถึง Google Drive");
            if ("expired_token".equals(code)) throw new IllegalStateException("รหัสเข้าสู่ระบบหมดอายุ กรุณาลองใหม่");
            if ("invalid_client".equals(code)) throw new IllegalStateException("Google TV OAuth Client ไม่ถูกต้อง ต้องเป็นชนิด TVs and Limited Input devices");
            throw new IllegalStateException(readError(token, "เข้าสู่ระบบ Google ไม่สำเร็จ"));
        }

        if (isCurrent(run)) throw new IllegalStateException("รหัสเข้าสู่ระบบหมดอายุ กรุณากดเข้าสู่ระบบใหม่");
    }

    private boolean configured() {
        return !BuildConfig.XSTAGE_TV_OAUTH_CLIENT_ID.trim().isEmpty()
                && !BuildConfig.XSTAGE_TV_OAUTH_CLIENT_SECRET.trim().isEmpty();
    }

    private boolean isCurrent(int run) {
        return generation.get() == run && !Thread.currentThread().isInterrupted();
    }

    private void status(int run, String message) {
        main.post(() -> { if (isCurrent(run)) listener.onStatus(message); });
    }

    private void error(int run, String message) {
        main.post(() -> { if (isCurrent(run)) listener.onError(message); });
    }

    private static String readable(Exception e) {
        String message = e.getMessage();
        return message == null || message.trim().isEmpty()
                ? "เชื่อมต่อ Google ไม่สำเร็จ กรุณาตรวจอินเทอร์เน็ตแล้วลองใหม่"
                : message;
    }

    private static String readError(JSONObject json, String fallback) {
        String description = json.optString("error_description");
        if (!description.isEmpty()) return description;
        String error = json.optString("error");
        if (!error.isEmpty()) return error;
        return fallback;
    }

    private static Map<String,String> mapOf(String... pairs) {
        Map<String,String> map = new LinkedHashMap<>();
        for (int i = 0; i + 1 < pairs.length; i += 2) map.put(pairs[i], pairs[i + 1]);
        return map;
    }

    private static JSONObject postForm(String endpoint, Map<String,String> params) throws Exception {
        StringBuilder body = new StringBuilder();
        for (Map.Entry<String,String> entry : params.entrySet()) {
            if (entry.getValue() == null || entry.getValue().isEmpty()) continue;
            if (body.length() > 0) body.append('&');
            body.append(URLEncoder.encode(entry.getKey(), StandardCharsets.UTF_8.name()));
            body.append('=');
            body.append(URLEncoder.encode(entry.getValue(), StandardCharsets.UTF_8.name()));
        }

        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint).openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(15000);
        connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        connection.setFixedLengthStreamingMode(bytes.length);
        try (OutputStream output = connection.getOutputStream()) {
            output.write(bytes);
        }

        int status = connection.getResponseCode();
        InputStream stream = status >= 200 && status < 300
                ? connection.getInputStream()
                : connection.getErrorStream();
        StringBuilder response = new StringBuilder();
        if (stream != null) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) response.append(line);
            }
        }
        connection.disconnect();

        if (response.length() == 0) {
            JSONObject empty = new JSONObject();
            empty.put("http_status", status);
            if (status >= 200 && status < 300) return empty;
            empty.put("error", "HTTP " + status);
            return empty;
        }
        return new JSONObject(response.toString());
    }
}
