package com.webbasex.xstage;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.ActivityManager;
import android.content.Context;
import android.app.UiModeManager;
import android.content.ActivityNotFoundException;
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
import android.webkit.JavascriptInterface;
import android.webkit.SafeBrowsingResponse;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

import org.json.JSONObject;


public final class MainActivity extends Activity {
    private static final String XSTAGE_HOST = "webbase-x.github.io";
    private static final String XSTAGE_PATH_PREFIX = "/xstage";

    private WebView webView;
    private FrameLayout appRoot;
    private ImageView startupBanner;
    private GoogleDeviceAuth googleAuth;
    private XStageUpdateManager updateManager;
    private boolean webAppReady;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        enterImmersiveMode();

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
                callJavascript("window.XStageAndroidSignedOut&&window.XStageAndroidSignedOut();");
            }
        });

        updateManager = new XStageUpdateManager(this, new XStageUpdateManager.Listener() {
            @Override
            public void onUpdateAvailable(String version, int build) {
                callJavascript("window.XStageAndroidUpdateAvailable&&window.XStageAndroidUpdateAvailable(" +
                        JSONObject.quote(version) + "," + build + ");");
            }

            @Override
            public void onUpdateStatus(String message) {
                callJavascript("window.XStageAndroidUpdateStatus&&window.XStageAndroidUpdateStatus(" +
                        JSONObject.quote(message) + ");");
            }

            @Override
            public void onUpdateError(String message) {
                callJavascript("window.XStageAndroidUpdateError&&window.XStageAndroidUpdateError(" +
                        JSONObject.quote(message) + ");");
            }

            @Override
            public void onNoUpdate() {
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
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                // Bundle only public, audited synth assets with the APK. Music,
                // lyrics, tokens and private Google Drive API responses must
                // NEVER pass through the native asset interceptor.
                final String prefix = XSTAGE_PATH_PREFIX + "/assets/vendor/";
                if (request.isForMainFrame() || !"GET".equalsIgnoreCase(request.getMethod())
                        || !isTrustedXStageUrl(uri) || !uri.getPath().startsWith(prefix))
                    return super.shouldInterceptRequest(view, request);

                String name = uri.getPath().substring(prefix.length());
                Set<String> allowed = new HashSet<>(Arrays.asList(
                        "spessasynth-lib.min.js", "spessasynth_processor.min.js",
                        "FluidR3Mono_GM.sf3", "midi-assets.json"));
                if (!allowed.contains(name)) return super.shouldInterceptRequest(view, request);
                String mime = name.endsWith(".js") ? "application/javascript"
                        : name.endsWith(".json") ? "application/json"
                        : "application/octet-stream";
                try {
                    InputStream stream = getAssets().open("xstage/vendor/" + name);
                    WebResourceResponse response = new WebResourceResponse(mime, null, stream);
                    response.setResponseHeaders(java.util.Collections.singletonMap(
                            "Cache-Control", "public, max-age=31536000, immutable"));
                    return response;
                } catch (IOException error) {
                    android.util.Log.e("XStage", "Packaged MIDI asset missing: " + name);
                    return new WebResourceResponse("text/plain", "utf-8",
                            new java.io.ByteArrayInputStream(
                                    "Packaged MIDI engine missing; reinstall verified X-Stage APK."
                                            .getBytes(java.nio.charset.StandardCharsets.UTF_8)));
                }
            }

            @Override
            public void onSafeBrowsingHit(WebView view, WebResourceRequest request, int threatType, SafeBrowsingResponse callback) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) callback.backToSafety(true);
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse errorResponse) {
                super.onReceivedHttpError(view, request, errorResponse);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                Uri uri = Uri.parse(url);
                if (isTrustedXStageUrl(uri) && updateManager != null) {
                    // Report device resource limits; never grant a WebView file or Drive permission.
                    ActivityManager manager=(ActivityManager)getSystemService(Context.ACTIVITY_SERVICE);
                    if(manager!=null){
                        JSONObject profile=new JSONObject();
                        try {
                            profile.put("memoryClassMb",manager.getMemoryClass());
                            profile.put("lowRam",manager.isLowRamDevice());
                            profile.put("androidSdk",Build.VERSION.SDK_INT);
                        }catch(Exception ignored){}
                        view.evaluateJavascript("window.XStageDeviceProfile="+profile.toString()+";",null);
                    }
                    // Wait until the web UI and its deferred scripts are ready before the native
                    // updater reports availability. Otherwise a fast version check can finish
                    // before window.XStageAndroidUpdateAvailable exists and the notice is lost.
                    webAppReady = true;
                    updateManager.checkForUpdates(true);
                    updateManager.startMonitoring();
                }
            }
        });

        webView.loadUrl(buildAppUrl());
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
        if (isTelevisionDevice() && event != null && event.getAction() == KeyEvent.ACTION_DOWN) {
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
                    activateWebFocus();
                    return true;
                default:
                    break;
            }
        }
        return super.dispatchKeyEvent(event);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
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
        if (updateManager != null && webAppReady) {
            updateManager.onResume();
            updateManager.startMonitoring();
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

    public final class AndroidBridge {
        @JavascriptInterface
        public void onLoginScreenReady() {
            runOnUiThread(() -> {
                if (startupBanner != null) startupBanner.setVisibility(View.GONE);
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
        public boolean isAndroidTvApp() {
            return isTelevisionDevice();
        }
    }
}
