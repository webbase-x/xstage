package com.webbasex.xstage;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
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
import android.webkit.JavascriptInterface;
import android.webkit.SafeBrowsingResponse;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

public final class MainActivity extends Activity {
    private static final String XSTAGE_HOST = "webbase-x.github.io";
    private static final String XSTAGE_PATH_PREFIX = "/xstage";

    private WebView webView;
    private GoogleDeviceAuth googleAuth;

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
        setContentView(webView);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccess(false);
        settings.setLoadsImagesAutomatically(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setSupportMultipleWindows(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setUserAgentString(settings.getUserAgentString() + " XStageAndroidTV/" + BuildConfig.VERSION_NAME);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            WebView.setSafeBrowsingEnabled(true);
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
            }
        });

        webView.loadUrl(buildAppUrl());
        webView.requestFocus();
    }

    private String buildAppUrl() {
        String separator = BuildConfig.XSTAGE_WEB_URL.contains("?") ? "&" : "?";
        return BuildConfig.XSTAGE_WEB_URL + separator +
                "source=android-tv&native_version=" +
                URLEncoder.encode(BuildConfig.VERSION_NAME, StandardCharsets.UTF_8);
    }

    private boolean isTrustedXStageUrl(Uri uri) {
        if (uri == null) return false;
        return "https".equalsIgnoreCase(uri.getScheme())
                && XSTAGE_HOST.equalsIgnoreCase(uri.getHost())
                && uri.getPath() != null
                && uri.getPath().startsWith(XSTAGE_PATH_PREFIX);
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
                clickWebControl("mobile-menu-toggle");
                return true;
            case KeyEvent.KEYCODE_SEARCH:
                focusSearch();
                return true;
            case KeyEvent.KEYCODE_BACK:
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
    }

    @Override
    protected void onPause() {
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (googleAuth != null) googleAuth.close();
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
        public void logoutGoogle() {
            googleAuth.logout();
        }

        @JavascriptInterface
        public String getAppVersion() {
            return BuildConfig.VERSION_NAME;
        }

        @JavascriptInterface
        public boolean isAndroidTvApp() {
            return true;
        }
    }
}
