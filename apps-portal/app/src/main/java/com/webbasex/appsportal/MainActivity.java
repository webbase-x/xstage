package com.webbasex.appsportal;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.net.http.SslError;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;

/** Signed Android shell for the live public X-Stage Apps storefront.
 * A site update is picked up at next page load. Native Android updates are NOT automatic.
 * Google OAuth is opened in the external browser; WebView Google login is not used.
 */
public final class MainActivity extends Activity {
    private static final String HOME =
        "https://webbase-x.github.io/xstage/?source=apps-portal-android";
    private WebView browser;
    private LinearLayout networkError;
    private String pendingCallback;
    private boolean loaded = false;
    private boolean pageFailed = false;
    private long lastLoad = 0;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(11,23,49));
        getWindow().setNavigationBarColor(Color.rgb(11,23,49));
        FrameLayout frame = new FrameLayout(this);
        browser = new WebView(this);
        frame.addView(browser,new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        networkError = createOfflineView();
        frame.addView(networkError,new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        networkError.setVisibility(View.GONE);
        setContentView(frame);

        WebSettings settings=browser.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setUserAgentString(settings.getUserAgentString()+" XStageAppsPortal/1");
        browser.setWebContentsDebuggingEnabled(false);
        browser.addJavascriptInterface(new PortalBridge(),"XStagePortalAndroid");
        browser.setWebChromeClient(new WebChromeClient());
        browser.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request){
                Uri url=request.getUrl();
                if("xstageapps".equals(url.getScheme()) && "auth".equals(url.getHost())){
                    onAuthCallback(url);return true;
                }
                if(isAllowedPage(url))return false;
                openExternal(url);
                return true;
            }
            @Override public void onPageStarted(WebView view,String url,android.graphics.Bitmap icon){
                pageFailed=false;
            }
            @Override public void onPageFinished(WebView view,String url){
                super.onPageFinished(view,url);
                loaded=true;
                if(!pageFailed)networkError.setVisibility(View.GONE);
                deliverCallback();
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
                if(request.isForMainFrame()){pageFailed=true;networkError.setVisibility(View.VISIBLE);}
            }
            @Override public void onReceivedSslError(WebView view,SslErrorHandler handler,SslError error){
                handler.cancel();pageFailed=true;networkError.setVisibility(View.VISIBLE);
            }
        });
        // Let Android's trusted browser/download manager handle APK, EXE and ZIP files.
        browser.setDownloadListener((url,userAgent,contentDisposition,mimetype,contentLength)->
            openExternal(Uri.parse(url)));
        if(state!=null){
            browser.restoreState(state);
            loaded=true;
        }else{
            loadFresh();
        }
        if(getIntent()!=null&&getIntent().getData()!=null)onAuthCallback(getIntent().getData());
    }
    private boolean isAllowedPage(Uri url){
        return "https".equalsIgnoreCase(url.getScheme())
          &&"webbase-x.github.io".equalsIgnoreCase(url.getHost())
          &&(url.getPath().equals("/xstage")||url.getPath().startsWith("/xstage/"));
    }
    private void openExternal(Uri url){
        if(!"https".equalsIgnoreCase(url.getScheme()))return;
        try{
            Intent intent=new Intent(Intent.ACTION_VIEW,url);
            intent.addCategory(Intent.CATEGORY_BROWSABLE);
            startActivity(intent);
        }catch(ActivityNotFoundException ignored){
            new AlertDialog.Builder(this).setMessage("ไม่พบเบราว์เซอร์สำหรับเปิดลิงก์")
                .setPositiveButton("ตกลง",null).show();
        }
    }
    private LinearLayout createOfflineView(){
        LinearLayout panel=new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setGravity(Gravity.CENTER);
        panel.setPadding(28,28,28,28);
        panel.setBackgroundColor(Color.rgb(11,23,49));
        TextView message=new TextView(this);
        message.setText("X-Stage Apps Portal\\n\\nไม่มีการเชื่อมต่อเว็บไซต์\\nตรวจสอบอินเทอร์เน็ต แล้วลองใหม่");
        message.setTextColor(Color.WHITE);
        message.setTextSize(20);
        message.setGravity(Gravity.CENTER);
        panel.addView(message,new LinearLayout.LayoutParams(-1,-2));
        Button retry=new Button(this);
        retry.setText("ลองใหม่");
        retry.setOnClickListener(v->loadFresh());
        panel.addView(retry);
        return panel;
    }
    private void loadFresh(){
        loaded=false;
        lastLoad=System.currentTimeMillis();
        networkError.setVisibility(View.GONE);
        browser.loadUrl(HOME);
    }
    public final class PortalBridge {
        @JavascriptInterface
        public void openOAuth(String rawUrl){
            Uri uri=Uri.parse(rawUrl);
            // Browser-only Google OAuth, never an embedded WebView credential form.
            boolean valid="https".equalsIgnoreCase(uri.getScheme())&&
                uri.getHost()!=null&&uri.getHost().matches("[a-z0-9-]+\\.supabase\\.co")&&
                "/auth/v1/authorize".equals(uri.getPath())&&
                "google".equals(uri.getQueryParameter("provider"));
            if(valid)runOnUiThread(()->openExternal(uri));
        }
    }
    private void onAuthCallback(Uri uri){
        if(uri==null||!"xstageapps".equals(uri.getScheme())||!"auth".equals(uri.getHost()))return;
        pendingCallback=uri.toString();
        deliverCallback();
    }
    private void deliverCallback(){
        if(!loaded||pendingCallback==null||browser==null)return;
        String quoted=JSONObject.quote(pendingCallback);
        browser.evaluateJavascript(
          "if(window.XStagePortal&&window.XStagePortal.completeNativeOAuth){"+
            "window.XStagePortal.completeNativeOAuth("+quoted+");true}else{false}",value->{
              if("true".equals(value))pendingCallback=null;
            });
    }
    @Override protected void onNewIntent(Intent intent){
        super.onNewIntent(intent);
        setIntent(intent);
        onAuthCallback(intent.getData());
    }
    @Override protected void onResume(){
        super.onResume();
        if(browser!=null)browser.onResume();
        // Refresh hosted content after a long absence; avoid disrupting OAuth return.
        if(loaded && pendingCallback==null &&
          System.currentTimeMillis()-lastLoad>10L*60L*1000L){
          lastLoad=System.currentTimeMillis();
          browser.reload();
        }
    }
    @Override protected void onPause(){
        if(browser!=null)browser.onPause();
        super.onPause();
    }
    @Override protected void onSaveInstanceState(Bundle out){
        if(browser!=null)browser.saveState(out);
        super.onSaveInstanceState(out);
    }
    @Override public void onBackPressed(){
        if(browser!=null&&browser.canGoBack()){
            browser.goBack();return;
        }
        new AlertDialog.Builder(this).setTitle("ปิด X-Stage Apps Portal?")
            .setMessage("ต้องการปิดแอปหรือไม่")
            .setNegativeButton("ไม่ปิด",null)
            .setPositiveButton("ปิด",(d,w)->finish()).show();
    }
    @Override protected void onDestroy(){
        if(browser!=null){
            ((ViewGroup)browser.getParent()).removeView(browser);
            browser.destroy();
            browser=null;
        }
        super.onDestroy();
    }
}
