package com.webbasex.ag06studio;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.OutputStream;

public class MainActivity extends Activity {
    private static final String BASE_URL="https://webbase-x.github.io/xstage/ag06/";
    private static final String TRUSTED_ORIGIN="https://webbase-x.github.io";
    private static final int RECORD_PERMISSION_REQUEST=721;
    private static final int MAX_DATA_URL_CHARS=33_000_000;
    private WebView web;
    private PermissionRequest waitingMicrophone;

    @SuppressLint("SetJavaScriptEnabled")
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        web=new WebView(this);
        setContentView(web);
        WebSettings settings=web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                final Uri uri=request.getUrl();
                final String url=uri.toString();
                if(url.startsWith(BASE_URL))return false;
                if("https".equals(uri.getScheme())){
                    try{startActivity(new Intent(Intent.ACTION_VIEW,uri));}catch(Exception error){
                        Toast.makeText(MainActivity.this,"ไม่สามารถเปิดลิงก์",Toast.LENGTH_SHORT).show();
                    }
                }
                return true;
            }
            @Override public void onReceivedError(WebView view,WebResourceRequest request,WebResourceError error){
                if(request.isForMainFrame()){
                    Toast.makeText(MainActivity.this,"ไม่สามารถโหลดหน้า AG06 Studio - ตรวจสอบอินเทอร์เน็ต",Toast.LENGTH_LONG).show();
                }
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onPermissionRequest(PermissionRequest request){
                runOnUiThread(()->handleWebPermission(request));
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request){
                if(waitingMicrophone==request)waitingMicrophone=null;
            }
        });
        // Narrow native operation: accept only a bounded audio recording and save it to Music.
        web.addJavascriptInterface(new RecordingBridge(),"AG06Android");
        web.loadUrl(BASE_URL);
    }

    private void handleWebPermission(PermissionRequest request){
        if(web==null||!web.getUrl().startsWith(BASE_URL)
                ||!TRUSTED_ORIGIN.equals(request.getOrigin().toString())){
            request.deny();return;
        }
        String[] resources=request.getResources();
        if(resources.length!=1||!PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0])){
            request.deny();return;
        }
        if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED){
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        }else{
            waitingMicrophone=request;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},RECORD_PERMISSION_REQUEST);
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] grantResults){
        super.onRequestPermissionsResult(requestCode,permissions,grantResults);
        if(requestCode!=RECORD_PERMISSION_REQUEST)return;
        PermissionRequest request=waitingMicrophone;
        waitingMicrophone=null;
        if(request==null)return;
        if(grantResults.length>0&&grantResults[0]==PackageManager.PERMISSION_GRANTED
                &&web!=null&&web.getUrl().startsWith(BASE_URL)){
            request.grant(new String[]{PermissionRequest.RESOURCE_AUDIO_CAPTURE});
        }else request.deny();
    }

    private boolean trustedPage(){
        return web!=null&&web.getUrl()!=null&&web.getUrl().startsWith(BASE_URL);
    }

    private void notifyWeb(boolean success,String message){
        runOnUiThread(()->{
            if(trustedPage())web.evaluateJavascript("window.AG06SaveResult("+success+","+JSONObject.quote(message)+")",null);
        });
    }

    private void saveRecording(String dataUrl){
        if(dataUrl==null||dataUrl.length()>MAX_DATA_URL_CHARS){
            notifyWeb(false,"ไฟล์เสียงใหญ่เกิน 24 MB สำหรับการส่งจาก WebView");return;
        }
        final int comma=dataUrl.indexOf(',');
        if(comma<0||comma>100||!dataUrl.substring(0,comma).endsWith(";base64")){
            notifyWeb(false,"ไฟล์เสียงไม่อยู่ในรูปแบบที่รองรับ");return;
        }
        final String meta=dataUrl.substring(0,comma);
        final String mime,extension;
        if(meta.startsWith("data:audio/webm")){mime="audio/webm";extension="webm";}
        else if(meta.startsWith("data:audio/ogg")){mime="audio/ogg";extension="ogg";}
        else if(meta.startsWith("data:audio/mp4")){mime="audio/mp4";extension="m4a";}
        else{notifyWeb(false,"รองรับเฉพาะเสียง WebM, Ogg หรือ MP4");return;}
        Uri created=null;
        try{
            byte[] bytes=Base64.decode(dataUrl.substring(comma+1),Base64.DEFAULT);
            if(bytes.length==0||bytes.length>24*1024*1024)throw new IllegalArgumentException("ไฟล์ใหญ่เกิน 24 MB");
            ContentValues values=new ContentValues();
            values.put(MediaStore.MediaColumns.DISPLAY_NAME,"X-Stage-AG06-"+System.currentTimeMillis()+"."+extension);
            values.put(MediaStore.MediaColumns.MIME_TYPE,mime);
            values.put(MediaStore.MediaColumns.RELATIVE_PATH,Environment.DIRECTORY_MUSIC+"/XStageAG06");
            values.put(MediaStore.MediaColumns.IS_PENDING,1);
            created=getContentResolver().insert(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,values);
            if(created==null)throw new IllegalStateException("ไม่สามารถสร้างไฟล์เสียง");
            try(OutputStream out=getContentResolver().openOutputStream(created)){
                if(out==null)throw new IllegalStateException("ไม่สามารถเปิดไฟล์เสียง");
                out.write(bytes);
                out.flush();
            }
            ContentValues ready=new ContentValues();
            ready.put(MediaStore.MediaColumns.IS_PENDING,0);
            getContentResolver().update(created,ready,null,null);
            notifyWeb(true,"บันทึกแล้วใน Music/XStageAG06");
        }catch(Exception error){
            if(created!=null)getContentResolver().delete(created,null,null);
            notifyWeb(false,"บันทึกเสียงไม่สำเร็จ: "+error.getMessage());
        }
    }

    public final class RecordingBridge {
        @JavascriptInterface public void saveAudio(String dataUrl){
            // JavaScriptInterface runs off UI thread; validate current top-level page on UI thread.
            runOnUiThread(()->{
                if(!trustedPage())return;
                new Thread(()->saveRecording(dataUrl),"ag06-audio-export").start();
            });
        }
    }

    @Override public void onBackPressed(){
        if(web!=null&&web.canGoBack())web.goBack();
        else super.onBackPressed();
    }
    @Override protected void onDestroy(){
        if(waitingMicrophone!=null){waitingMicrophone.deny();waitingMicrophone=null;}
        if(web!=null){web.destroy();web=null;}
        super.onDestroy();
    }
}
