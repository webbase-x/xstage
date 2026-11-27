package com.webbasex.xstage;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.ActivityManager;
import android.app.UiModeManager;
import android.content.ActivityNotFoundException;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Button;
import android.view.Gravity;
import android.webkit.WebResourceError;
import android.webkit.JavascriptInterface;
import android.webkit.SafeBrowsingResponse;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;


public final class MainActivity extends Activity {
    private static final String XSTAGE_HOST = "webbase-x.github.io";
    private static final String XSTAGE_PATH_PREFIX = "/xstage";

    private WebView webView;
    private final java.util.concurrent.ExecutorService catalogExecutor =
            java.util.concurrent.Executors.newSingleThreadExecutor();
    private final Object catalogLock = new Object();
    private volatile String catalogAccessToken = "";
    private volatile long catalogEpoch;
    private NativeCatalogStore activeCatalog, stagedCatalog;
    private String activeCatalogCapability = "", stagedCatalogCapability = "";
    private java.util.concurrent.Future<?> catalogTask;
    private FrameLayout appRoot;
    private ImageView startupBanner;
    private GoogleDeviceAuth googleAuth;
    private XStageUpdateManager updateManager;
    private boolean webAppReady;
    private boolean loginScreenReady;
    private LinearLayout startupRecovery;
    private TextView startupStatus;
    private Button startupRetry;
    private final Handler startupHandler = new Handler(Looper.getMainLooper());
    private final Runnable startupTimeout = () -> showStartupRecovery("หน้าเข้าสู่ระบบยังไม่พร้อม · ตรวจอินเทอร์เน็ตแล้วลองใหม่");
    private volatile boolean webTextEditingActive;
    private volatile boolean playbackAudioFocusHeld;
    private AudioManager audioManager;
    private AudioFocusRequest playbackFocusRequest;
    private final AudioManager.OnAudioFocusChangeListener playbackFocusListener = change -> {
        if (change == AudioManager.AUDIOFOCUS_GAIN) {
            playbackAudioFocusHeld = true;
            dispatchPlaybackFocusState("gain");
        } else if (change == AudioManager.AUDIOFOCUS_LOSS) {
            playbackAudioFocusHeld = false;
            dispatchPlaybackFocusState("loss-permanent");
        } else if (change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT ||
                   change == AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK) {
            // Pause karaoke rather than mixing its vocals with another audio source.
            dispatchPlaybackFocusState("loss-transient");
        }
    };

    private void dispatchPlaybackFocusState(String state) {
        callJavascript("window.dispatchEvent(new CustomEvent('xstage-native-audio-focus'," +
                "{detail:{state:" + JSONObject.quote(state) + "}}));");
    }

    private synchronized boolean acquirePlaybackAudioFocus() {
        if (audioManager == null) return false;
        if (playbackAudioFocusHeld) return true;
        int result;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (playbackFocusRequest == null) {
                AudioAttributes attributes = new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build();
                playbackFocusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                        .setAudioAttributes(attributes)
                        .setWillPauseWhenDucked(true)
                        .setOnAudioFocusChangeListener(playbackFocusListener, new Handler(Looper.getMainLooper()))
                        .build();
            }
            result = audioManager.requestAudioFocus(playbackFocusRequest);
        } else {
            result = audioManager.requestAudioFocus(playbackFocusListener,
                    AudioManager.STREAM_MUSIC, AudioManager.AUDIOFOCUS_GAIN);
        }
        playbackAudioFocusHeld = result == AudioManager.AUDIOFOCUS_REQUEST_GRANTED;
        return playbackAudioFocusHeld;
    }

    private synchronized void releasePlaybackAudioFocus() {
        if (audioManager == null || !playbackAudioFocusHeld) return;
        playbackAudioFocusHeld = false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && playbackFocusRequest != null) {
            audioManager.abandonAudioFocusRequest(playbackFocusRequest);
        } else {
            audioManager.abandonAudioFocus(playbackFocusListener);
        }
    }

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        enterImmersiveMode();
        audioManager = (AudioManager) getSystemService(AUDIO_SERVICE);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(6,19,33));
        webView.setFocusable(true);
        webView.setFocusableInTouchMode(true);
        // Native startup splash shows the official logo until the QR login UI
        // is ready. The hosted stage itself stays locked until Drive access.
        appRoot = new FrameLayout(this);
        appRoot.setBackgroundColor(Color.rgb(6,19,33));
        appRoot.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        startupBanner = new ImageView(this);
        startupBanner.setImageResource(R.drawable.xstage_tv_splash);
        startupBanner.setScaleType(ImageView.ScaleType.FIT_CENTER);
        startupBanner.setBackgroundColor(Color.rgb(6,19,33));
        int padding = Math.round(24f * getResources().getDisplayMetrics().density);
        startupBanner.setPadding(padding,padding,padding,padding);
        appRoot.addView(startupBanner, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(appRoot);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        settings.setTextZoom(100);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccess(false);
        settings.setLoadsImagesAutomatically(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUserAgentString(settings.getUserAgentString() + " XStageAndroidTV/" + BuildConfig.VERSION_NAME);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            settings.setSafeBrowsingEnabled(true);
        }

        googleAuth = new GoogleDeviceAuth(this, new GoogleDeviceAuth.Listener() {
            @Override
            public void onDeviceCode(String userCode, String verificationUrl, long expiresInSeconds) {
                JSONObject payload = new JSONObject();
                try {
                    payload.put("user_code", userCode);
                    payload.put("verification_url", verificationUrl);
                    payload.put("expires_in", expiresInSeconds);
                } catch (Exception ignored) {}
                callJavascript("window.XStageAndroidDeviceCode&&window.XStageAndroidDeviceCode(" +
                        JSONObject.quote(payload.toString()) + ");");
            }

            @Override
            public void onStatus(String message) {
                callJavascript("window.XStageAndroidAuthStatus&&window.XStageAndroidAuthStatus(" +
                        JSONObject.quote(message) + ");");
            }

            @Override
            public void onToken(String accessToken, long expiresInSeconds) {
                catalogAccessToken = accessToken;
                callJavascript("window.XStageReceiveAndroidToken&&window.XStageReceiveAndroidToken(" +
                        JSONObject.quote(accessToken) + "," + expiresInSeconds + ");");
            }

            @Override
            public void onError(String message) {
                callJavascript("window.XStageAndroidAuthError&&window.XStageAndroidAuthError(" +
                        JSONObject.quote(message) + ");");
            }

            @Override
            public void onSignedOut() {
                catalogAccessToken = "";
                resetNativeCatalog();
                callJavascript("window.XStageAndroidSignedOut&&window.XStageAndroidSignedOut();");
            }
        });

        updateManager = new XStageUpdateManager(this, new XStageUpdateManager.Listener() {
            @Override
            public void onUpdateAvailable(String version, int build) {
                if (isStartupRecoveryVisible()) startupStatus.setText("พบรุ่นใหม่ v" + version + " · Build " + build + " · กดอัปเดต APK");
                callJavascript("window.XStageAndroidUpdateAvailable&&window.XStageAndroidUpdateAvailable(" +
                        JSONObject.quote(version) + "," + build + ");");
            }

            @Override
            public void onUpdateStatus(String message) {
                if (isStartupRecoveryVisible()) startupStatus.setText(message);
                callJavascript("window.XStageAndroidUpdateStatus&&window.XStageAndroidUpdateStatus(" +
                        JSONObject.quote(message) + ");");
            }

            @Override
            public void onUpdateError(String message) {
                if (isStartupRecoveryVisible()) startupStatus.setText(message);
                callJavascript("window.XStageAndroidUpdateError&&window.XStageAndroidUpdateError(" +
                        JSONObject.quote(message) + ");");
            }

            @Override
            public void onNoUpdate() {
                if (isStartupRecoveryVisible()) startupStatus.setText("ยังไม่มี APK รุ่นใหม่ · ลองเปิดหน้าเข้าสู่ระบบอีกครั้ง");
                callJavascript("window.XStageAndroidNoUpdate&&window.XStageAndroidNoUpdate();");
            }
        });

        webView.addJavascriptInterface(new AndroidBridge(), "XStageAndroid");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (isTrustedXStageUrl(uri)) return false;
                openExternal(uri);
                return true;
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                Uri uri = Uri.parse(url);
                if (isTrustedXStageUrl(uri)) return false;
                openExternal(uri);
                return true;
            }

            @Override
            public void onSafeBrowsingHit(WebView view, WebResourceRequest request, int threatType, SafeBrowsingResponse callback) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) callback.backToSafety(true);
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
                super.onReceivedHttpError(view, request, errorResponse);
                if (request.isForMainFrame()) showStartupRecovery("เปิด X-Stage ไม่สำเร็จ · HTTP " + errorResponse.getStatusCode());
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                super.onReceivedError(view, request, error);
                if (request.isForMainFrame()) showStartupRecovery("เชื่อมต่อ X-Stage ไม่สำเร็จ · ตรวจอินเทอร์เน็ตแล้วลองใหม่");
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                webTextEditingActive = false;
                Uri uri = Uri.parse(url);
                if (isTrustedXStageUrl(uri) && updateManager != null) {
                    // Wait until the web UI and its deferred scripts are ready before the native
                    // updater reports availability. Otherwise a fast version check can finish
                    // before window.XStageAndroidUpdateAvailable exists and the notice is lost.
                    webAppReady = true;
                    updateManager.checkForUpdates(true);
                    updateManager.startMonitoring();
                }
            }
        });

        startupHandler.postDelayed(startupTimeout, 15000L);
        webView.loadUrl(buildAppUrl());
        webView.requestFocus();
    }

    private boolean isStartupRecoveryVisible() {
        return startupRecovery != null && startupRecovery.getVisibility() == View.VISIBLE;
    }

    private void showStartupRecovery(String message) {
        if (loginScreenReady || isFinishing() || isDestroyed() || appRoot == null) return;
        startupHandler.removeCallbacks(startupTimeout);
        if (startupRecovery == null) {
            startupRecovery = new LinearLayout(this);
            startupRecovery.setOrientation(LinearLayout.VERTICAL);
            startupRecovery.setGravity(Gravity.CENTER);
            startupRecovery.setBackgroundColor(Color.rgb(6,19,33));
            int padding = Math.round(24f * getResources().getDisplayMetrics().density);
            startupRecovery.setPadding(padding,padding,padding,padding);
            startupStatus = new TextView(this);
            startupStatus.setTextColor(Color.WHITE);
            startupStatus.setTextSize(22);
            startupStatus.setGravity(Gravity.CENTER);
            startupRecovery.addView(startupStatus);
            startupRetry = new Button(this);
            startupRetry.setText("ลองเปิดหน้าเข้าสู่ระบบใหม่");
            startupRetry.setOnClickListener(v -> retryStartup());
            startupRecovery.addView(startupRetry);
            Button update = new Button(this);
            update.setText("ตรวจสอบ APK รุ่นใหม่");
            update.setOnClickListener(v -> {
                if (updateManager != null) updateManager.checkForUpdates(true);
                startupStatus.setText("กำลังตรวจสอบ APK รุ่นใหม่…");
            });
            startupRecovery.addView(update);
            Button install = new Button(this);
            install.setText("อัปเดต APK");
            install.setOnClickListener(v -> {
                if (updateManager != null) updateManager.installLatestUpdate();
            });
            startupRecovery.addView(install);
            Button exit = new Button(this);
            exit.setText("ออกจากแอป");
            exit.setOnClickListener(v -> finish());
            startupRecovery.addView(exit);
            appRoot.addView(startupRecovery, new FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        }
        startupStatus.setText(message);
        startupRecovery.setVisibility(View.VISIBLE);
        startupRetry.requestFocus();
    }

    private void retryStartup() {
        if (webView == null || loginScreenReady) return;
        startupRecovery.setVisibility(View.GONE);
        startupBanner.setVisibility(View.VISIBLE);
        webAppReady = false;
        webView.stopLoading();
        if (googleAuth != null) googleAuth.cancel();
        startupHandler.removeCallbacks(startupTimeout);
        startupHandler.postDelayed(startupTimeout, 15000L);
        // Bypass stale HTTP cache without clearing credentials or song data.
        webView.getSettings().setCacheMode(WebSettings.LOAD_NO_CACHE);
        webView.loadUrl(buildAppUrl() + "&startup_retry=" + System.currentTimeMillis());
        webView.requestFocus();
    }

    private boolean isTelevisionDevice() {
        UiModeManager uiModeManager = (UiModeManager) getSystemService(UI_MODE_SERVICE);
        if (uiModeManager != null
                && uiModeManager.getCurrentModeType() == Configuration.UI_MODE_TYPE_TELEVISION) {
            return true;
        }
        return getPackageManager().hasSystemFeature(PackageManager.FEATURE_LEANBACK);
    }

    private String buildAppUrl() {
        String separator = BuildConfig.XSTAGE_WEB_URL.contains("?") ? "&" : "?";
        String source = isTelevisionDevice() ? "android-tv" : "android-tablet";
        return BuildConfig.XSTAGE_WEB_URL + separator +
                "source=" + source + "&native_version=" +
                Uri.encode(BuildConfig.VERSION_NAME);
    }

    private boolean isTrustedXStageUrl(Uri uri) {
        if (uri == null) return false;
        return "https".equalsIgnoreCase(uri.getScheme())
                && XSTAGE_HOST.equalsIgnoreCase(uri.getHost())
                && uri.getPath() != null
                && (uri.getPath().equals(XSTAGE_PATH_PREFIX) || uri.getPath().startsWith(XSTAGE_PATH_PREFIX + "/"));
    }

    private void openExternal(Uri uri) {
        if (uri == null) return;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException ignored) {
            callJavascript("window.XStageAndroidAuthError&&window.XStageAndroidAuthError(" +
                    JSONObject.quote("อุปกรณ์นี้ไม่มีแอปที่เปิดลิงก์ภายนอกได้") + ");");
        }
    }

    private void callJavascript(String script) {
        if (webView == null) return;
        runOnUiThread(() -> {
            if (webView != null) webView.evaluateJavascript(script, null);
        });
    }

    private void clickWebControl(String id) {
        callJavascript("(function(){var e=document.getElementById(" + JSONObject.quote(id) +
                ");if(e){e.click();return true}return false})()");
    }

    private void focusSearch() {
        callJavascript("(function(){var e=document.getElementById('search');if(e){e.focus();return true}return false})()");
    }

    private void moveWebFocus(String direction) {
        callJavascript("window.XStageTvMoveFocus&&window.XStageTvMoveFocus(" +
                JSONObject.quote(direction) + ");");
    }

    private void activateWebFocus() {
        callJavascript("window.XStageTvActivateFocused&&window.XStageTvActivateFocused();");
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        if (isStartupRecoveryVisible()) return super.dispatchKeyEvent(event);
        if (isTelevisionDevice() && event != null && event.getAction() == KeyEvent.ACTION_DOWN && !webTextEditingActive) {
            switch (event.getKeyCode()) {
                case KeyEvent.KEYCODE_DPAD_LEFT:
                    moveWebFocus("left");
                    return true;
                case KeyEvent.KEYCODE_DPAD_RIGHT:
                    moveWebFocus("right");
                    return true;
                case KeyEvent.KEYCODE_DPAD_UP:
                    moveWebFocus("up");
                    return true;
                case KeyEvent.KEYCODE_DPAD_DOWN:
                    moveWebFocus("down");
                    return true;
                case KeyEvent.KEYCODE_DPAD_CENTER:
                case KeyEvent.KEYCODE_ENTER:
                case KeyEvent.KEYCODE_NUMPAD_ENTER:
                case KeyEvent.KEYCODE_BUTTON_A:
                    // Holding OK must not activate playback or change songs repeatedly.
                    if (event.getRepeatCount() == 0) activateWebFocus();
                    return true;
                default:
                    break;
            }
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (isStartupRecoveryVisible()) {
            if (keyCode == KeyEvent.KEYCODE_BACK) { finish(); return true; }
            return super.onKeyDown(keyCode, event);
        }
        // Repeat arrows for navigation but never auto-repeat transport actions.
        if (event != null && event.getRepeatCount() > 0) {
            switch (keyCode) {
                case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                case KeyEvent.KEYCODE_HEADSETHOOK:
                case KeyEvent.KEYCODE_MEDIA_NEXT:
                case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                case KeyEvent.KEYCODE_MENU:
                case KeyEvent.KEYCODE_SEARCH:
                    return true;
                default:
                    break;
            }
        }
        switch (keyCode) {
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
            case KeyEvent.KEYCODE_HEADSETHOOK:
                clickWebControl("play-pause");
                return true;
            case KeyEvent.KEYCODE_MEDIA_NEXT:
                clickWebControl("next");
                return true;
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                clickWebControl("previous");
                return true;
            case KeyEvent.KEYCODE_MENU:
                if (isTelevisionDevice()) {
                    callJavascript("window.XStageTvOpenMenu&&window.XStageTvOpenMenu();");
                } else {
                    clickWebControl("mobile-menu-toggle");
                }
                return true;
            case KeyEvent.KEYCODE_SEARCH:
                if (isTelevisionDevice()) {
                    callJavascript("window.XStageTvOpenMenu&&window.XStageTvOpenMenu();");
                } else {
                    focusSearch();
                }
                return true;
            case KeyEvent.KEYCODE_BACK:
                if (isTelevisionDevice() && webView != null) {
                    webView.evaluateJavascript(
                            "Boolean(window.XStageTvHandleBack&&window.XStageTvHandleBack())",
                            handled -> {
                                // Back closes a TV dialog first; otherwise exits the app
                                // instead of browsing away to an arbitrary WebView page.
                                if (!"true".equals(handled) && !isFinishing()) finish();
                            });
                    return true;
                }
                if (webView != null && webView.canGoBack()) {
                    webView.goBack();
                    return true;
                }
                break;
            default:
                break;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    protected void onResume() {
        super.onResume();
        enterImmersiveMode();
        if (webView != null) webView.onResume();
        if (updateManager != null && (webAppReady || isStartupRecoveryVisible())) {
            updateManager.onResume();
            if (webAppReady) updateManager.startMonitoring();
        }
    }

    @Override
    protected void onPause() {
        if (updateManager != null) updateManager.stopMonitoring();
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        startupHandler.removeCallbacksAndMessages(null);
        catalogAccessToken = "";
        resetNativeCatalog();
        catalogExecutor.shutdownNow();
        releasePlaybackAudioFocus();
        if (googleAuth != null) googleAuth.close();
        if (updateManager != null) updateManager.close();
        if (webView != null) {
            webView.removeJavascriptInterface("XStageAndroid");
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private void enterImmersiveMode() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.statusBars() | WindowInsets.Type.navigationBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                    View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN |
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION |
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            );
        }
    }

    private void resetNativeCatalog() {
        synchronized (catalogLock) {
            catalogEpoch++;
            if (catalogTask != null) catalogTask.cancel(true);
            catalogTask = null;
            if (activeCatalog != null) activeCatalog.close();
            if (stagedCatalog != null) stagedCatalog.close();
            activeCatalog = stagedCatalog = null;
            activeCatalogCapability = stagedCatalogCapability = "";
        }
    }

    private void catalogCallback(String requestId, String kind, JSONObject data) {
        callJavascript("window.XStageNativeCatalogEvent&&window.XStageNativeCatalogEvent(" +
                JSONObject.quote(requestId) + "," + JSONObject.quote(kind) + "," +
                JSONObject.quote(data.toString()) + ");");
    }

    private JSONObject catalogError(Exception error) {
        JSONObject data = new JSONObject();
        try { data.put("error", error.getMessage() == null ? "Native catalog operation failed" : error.getMessage()); }
        catch (Exception ignored) {}
        return data;
    }

    public final class AndroidBridge {
        @JavascriptInterface
        public void catalogOpen(String requestId, String sub, String root, String db, String file) {
            catalogOpenInternal(requestId, sub, root, db, file, "", "", 0, false);
        }

        @JavascriptInterface
        public void catalogOpenVerified(String requestId, String sub, String root, String db, String file,
                                        String sourceId, String sourceMD5, String sourceSize) {
            try {
                if (sourceId == null || sourceId.isEmpty() || sourceMD5 == null || !sourceMD5.matches("[a-f0-9]{32}")) throw new IllegalArgumentException("Invalid source catalog identity");
                long bytes = Long.parseLong(sourceSize);
                if (bytes < 100) throw new IllegalArgumentException("Invalid source size");
                catalogOpenInternal(requestId, sub, root, db, file, sourceId, sourceMD5, bytes, false);
            } catch (Exception e) { catalogCallback(requestId, "error", catalogError(e)); }
        }

        @JavascriptInterface
        public void catalogOpenPreview(String requestId, String sub, String root, String db, String file,
                                        String sourceId, String sourceMD5, String sourceSize) {
            try {
                if (sourceId == null || sourceId.isEmpty() || sourceMD5 == null || !sourceMD5.matches("[a-f0-9]{32}")) throw new IllegalArgumentException("Invalid source catalog identity");
                long bytes = Long.parseLong(sourceSize);
                if (bytes < 100) throw new IllegalArgumentException("Invalid source size");
                catalogOpenInternal(requestId, sub, root, db, file, sourceId, sourceMD5, bytes, true);
            } catch (Exception e) { catalogCallback(requestId, "error", catalogError(e)); }
        }

        private void catalogOpenInternal(String requestId, String sub, String root, String db, String file,
                                         String sourceId, String sourceMD5, long sourceBytes, boolean preview) {
            if (requestId == null || !requestId.matches("[A-Za-z0-9_-]{8,128}")) return;
            final String token = catalogAccessToken;
            if (token.isEmpty()) {
                catalogCallback(requestId, "error", catalogError(new IllegalStateException("Google session unavailable")));
                return;
            }
            synchronized (catalogLock) {
                final long epoch = ++catalogEpoch;
                if (catalogTask != null) catalogTask.cancel(true);
                if (stagedCatalog != null) stagedCatalog.close();
                stagedCatalog = null;
                stagedCatalogCapability = "";
                catalogTask = catalogExecutor.submit(() -> {
                    NativeCatalogStore next = new NativeCatalogStore(MainActivity.this);
                    boolean kept = false;
                    try {
                        JSONObject result = next.open(token, sub, root, db, file, sourceId, sourceMD5, sourceBytes, preview, (received, total) -> {
                            if (epoch != catalogEpoch) return;
                            try {
                                catalogCallback(requestId, "progress", new JSONObject().put("received", received).put("total", total));
                            } catch (Exception ignored) {}
                        });
                        synchronized (catalogLock) {
                            if (epoch != catalogEpoch || Thread.currentThread().isInterrupted()) return;
                            String capability = java.util.UUID.randomUUID().toString();
                            result.put("capability", capability);
                            stagedCatalog = next;
                            stagedCatalogCapability = capability;
                            kept = true;
                            catalogCallback(requestId, "ready", result);
                        }
                    } catch (Exception e) {
                        if (epoch == catalogEpoch) catalogCallback(requestId, "error", catalogError(e));
                    } finally {
                        if (!kept) next.close();
                    }
                });
            }
        }

        @JavascriptInterface
        public boolean catalogActivate(String capability) {
            synchronized (catalogLock) {
                if (stagedCatalog == null || capability == null || !capability.equals(stagedCatalogCapability)) return false;
                if (activeCatalog != null) activeCatalog.close();
                activeCatalog = stagedCatalog;
                activeCatalogCapability = stagedCatalogCapability;
                stagedCatalog = null;
                stagedCatalogCapability = "";
                activeCatalog.cleanupObsolete();
                return true;
            }
        }

        @JavascriptInterface
        public void catalogReset() {
            resetNativeCatalog();
        }

        private NativeCatalogStore checkedCatalog(String capability) {
            if (activeCatalog == null || capability == null || !capability.equals(activeCatalogCapability))
                throw new IllegalStateException("Native catalog session changed");
            return activeCatalog;
        }

        @JavascriptInterface
        public String catalogSearch(String cap, String sub, String root, String revision, String term, long offset) {
            synchronized (catalogLock) {
                try { return checkedCatalog(cap).search(sub, root, revision, term, offset).toString(); }
                catch (Exception e) { return catalogError(e).toString(); }
            }
        }

        @JavascriptInterface
        public String catalogLookup(String cap, String sub, String root, String revision, String id, String code, String title, String artist) {
            synchronized (catalogLock) {
                try {
                    JSONObject song = checkedCatalog(cap).lookup(sub, root, revision, id, code, title, artist);
                    return song == null ? "null" : song.toString();
                } catch (Exception e) { return catalogError(e).toString(); }
            }
        }

        @JavascriptInterface
        public String catalogRandom(String cap, String sub, String root, String revision) {
            synchronized (catalogLock) {
                try {
                    JSONObject song = checkedCatalog(cap).randomSong(sub, root, revision);
                    return song == null ? "null" : song.toString();
                } catch (Exception e) { return catalogError(e).toString(); }
            }
        }

        @JavascriptInterface
        public String memorySnapshot() {
            // Android supplies actual available physical RAM and its low-memory
            // threshold. Never expose user identity, applications or process IDs.
            try {
                ActivityManager manager = (ActivityManager) getSystemService(ACTIVITY_SERVICE);
                if (manager == null) return "";
                ActivityManager.MemoryInfo info = new ActivityManager.MemoryInfo();
                manager.getMemoryInfo(info);
                JSONObject data = new JSONObject();
                data.put("total", info.totalMem);
                data.put("available", info.availMem);
                data.put("threshold", info.threshold);
                data.put("lowMemory", info.lowMemory);
                return data.toString();
            } catch (Exception ignored) {
                return "";
            }
        }

        @JavascriptInterface
        public void setTextEditingActive(boolean active) {
            // DOM focus state is supplied by the trusted hosted application.
            webTextEditingActive = active;
        }

        @JavascriptInterface
        public boolean requestPlaybackAudioFocus() {
            return acquirePlaybackAudioFocus();
        }

        @JavascriptInterface
        public void releasePlaybackAudioFocus() {
            MainActivity.this.releasePlaybackAudioFocus();
        }

        @JavascriptInterface
        public void onLoginScreenReady() {
            runOnUiThread(() -> {
                if (webView == null || !isTrustedXStageUrl(Uri.parse(webView.getUrl() == null ? "" : webView.getUrl()))) return;
                loginScreenReady = true;
                startupHandler.removeCallbacks(startupTimeout);
                if (startupBanner != null) startupBanner.setVisibility(View.GONE);
                if (startupRecovery != null) startupRecovery.setVisibility(View.GONE);
                webView.getSettings().setCacheMode(WebSettings.LOAD_DEFAULT);
                webView.requestFocus();
            });
        }

        @JavascriptInterface
        public void requestGoogleLogin() {
            runOnUiThread(() -> googleAuth.startDeviceLogin());
        }

        @JavascriptInterface
        public void cancelGoogleLogin() {
            googleAuth.cancel();
        }

        @JavascriptInterface
        public void restoreGoogleSession() {
            googleAuth.restoreSession();
        }

        @JavascriptInterface
        public boolean hasStoredGoogleSession() {
            return googleAuth.hasStoredSession();
        }

        @JavascriptInterface
        public void logoutGoogle() {
            catalogAccessToken = "";
            resetNativeCatalog();
            googleAuth.logout();
        }

        @JavascriptInterface
        public String getAppVersion() {
            return BuildConfig.VERSION_NAME;
        }

        @JavascriptInterface
        public int getAppBuild() {
            return BuildConfig.VERSION_CODE;
        }

        @JavascriptInterface
        public boolean usesGooglePlayUpdates() {
            return !BuildConfig.DEBUG;
        }

        @JavascriptInterface
        public void checkForAppUpdate() {
            if (updateManager != null) updateManager.checkForUpdates(true);
        }

        @JavascriptInterface
        public void installAvailableUpdate() {
            if (updateManager != null) runOnUiThread(updateManager::installLatestUpdate);
        }

        @JavascriptInterface
        public void requestHomeIcon() {
            // UI-thread handoff from the signed, trusted Karaoke WebView.
            runOnUiThread(() -> TvHomeShortcut.request(MainActivity.this));
        }

        @JavascriptInterface
        public boolean isAndroidTvApp() {
            return isTelevisionDevice();
        }
    }
}
