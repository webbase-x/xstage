"use strict";
/* X-Stage Apps Portal: authenticated download history and app reviews.
 * UI is public; writes are guarded by Supabase RLS, not client-side role checks.
 * A browser cannot detect whether an APK or EXE was actually installed.
 */
(function () {
  const config=window.XSTAGE_PORTAL_CONFIG||{};
  const configured=/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(config.supabaseUrl||"") &&
    /^(sb_publishable_|eyJ)/.test(config.supabasePublishableKey||"");
  const $=id=>document.getElementById(id);
  const login=$("portal-login"), logout=$("portal-logout"), userLabel=$("portal-user");
  const historySection=$("portal-history"), historyList=$("portal-history-list");
  const reviewForm=$("portal-review-form"), reviewStatus=$("portal-reviews-status");
  const reviewList=$("portal-review-list"), reviewSummary=$("portal-rating-summary");
  const adminPanel=$("portal-admin"), adminEvents=$("portal-admin-events");
  const appIds=()=>Array.from(document.querySelectorAll(".app-card[data-app]")).map(c=>c.dataset.app);
  let client=null,user=null,isAdmin=false,activeApp=null,latestReviews=[];
  const safeText=value=>String(value==null?"":value);
  function message(node,value){if(node)node.textContent=value;}
  function currentApp(){const id=new URLSearchParams(location.search).get("app");return id&&appIds().includes(id)?id:null;}
  function dateLabel(value){return new Date(value).toLocaleString("th-TH",{dateStyle:"medium",timeStyle:"short"});}
  function resetReviewArea(){
    if(!reviewList)return;
    reviewList.replaceChildren();
    reviewSummary.textContent="กำลังโหลดคะแนน…";
    reviewForm.hidden=true;
  }
  function element(tag,css,textContent){
    const node=document.createElement(tag);
    if(css)node.className=css;
    if(textContent!==undefined)node.textContent=safeText(textContent);
    return node;
  }
  function showInfo(parent,value){parent.appendChild(element("p","portal-muted",value));}
  function canUsePortal(){return client!==null;}
  function refreshAccount(){
    login.hidden=!!user;
    logout.hidden=!user;
    userLabel.textContent=user?"เข้าสู่ระบบ: "+safeText(user.user_metadata?.name||user.email||"สมาชิก X-Stage"):"ผู้เยี่ยมชม · ดูรายการได้";
    historySection.hidden=!user;
    reviewForm.hidden=!user||!activeApp||!canUsePortal();
  }
  async function loadAdmin(){
    isAdmin=false;adminPanel.hidden=true;
    if(!user||!client)return;
    const {data,error}=await client.from("xstage_admins").select("user_id").eq("user_id",user.id).limit(1);
    if(error||!data?.length)return;
    isAdmin=true;adminPanel.hidden=false;adminEvents.replaceChildren();
    const response=await client.from("xstage_download_events")
      .select("app_id,event_type,app_version,created_at")
      .order("created_at",{ascending:false}).limit(50);
    if(response.error){showInfo(adminEvents,"ไม่สามารถอ่านข้อมูลกิจกรรมได้");return;}
    (response.data||[]).forEach(item=>{
      adminEvents.appendChild(element("div","portal-event",
        dateLabel(item.created_at)+" · "+item.app_id+" · "+item.event_type));
    });
    if(!response.data?.length)showInfo(adminEvents,"ยังไม่มีกิจกรรมที่บันทึก");
  }
  async function loadHistory(){
    if(!user||!client)return;
    historyList.replaceChildren();
    const response=await client.from("xstage_download_events")
      .select("id,app_id,event_type,app_version,created_at")
      .eq("user_id",user.id).order("created_at",{ascending:false}).limit(100);
    if(response.error){showInfo(historyList,"อ่านประวัติไม่ได้: "+response.error.message);return;}
    if(!response.data?.length){showInfo(historyList,"ยังไม่มีประวัติการดาวน์โหลด");return;}
    for(const item of response.data){
      const line=element("div","portal-event");
      const label=item.event_type==="installation_confirmed"?"ยืนยันการติดตั้งแล้ว":
        item.event_type==="download_clicked"?"กดดาวน์โหลด":"เปิดรายละเอียด";
      line.appendChild(element("span","",item.app_id+" · "+label+" · "+dateLabel(item.created_at)));
      if(item.event_type==="download_clicked"){
        const confirm=element("button","portal-small-button","ยืนยันว่าติดตั้งแล้ว");
        confirm.type="button";
        confirm.addEventListener("click",async()=>{
          await saveEvent(item.app_id,"installation_confirmed",item.app_version||null);
          await loadHistory();
        });
        line.appendChild(confirm);
      }
      historyList.appendChild(line);
    }
    const clear=element("button","portal-small-button portal-danger","ลบประวัติของฉัน");
    clear.type="button";
    clear.addEventListener("click",async()=>{
      if(!window.confirm("ลบประวัติการดาวน์โหลดและการติดตั้งของบัญชีนี้ทั้งหมด?"))return;
      const {error}=await client.from("xstage_download_events").delete().eq("user_id",user.id);
      if(error)window.alert(error.message);else await loadHistory();
    });
    historyList.appendChild(clear);
  }
  async function saveEvent(appId,eventType,version){
    if(!client||!user||!appIds().includes(appId))return;
    const {error}=await client.from("xstage_download_events").insert({
      user_id:user.id,app_id:appId,event_type:eventType,
      app_version:typeof version==="string"?version.slice(0,64):null,
      client_platform:navigator.userAgent.includes("XStageAppsPortal/")?"android-portal":"web"
    });
    if(error)console.warn("X-Stage history unavailable:",error.message);
  }
  function reviewRow(item){
    const row=element("article","portal-review-item");
    const head=element("div","portal-review-header");
    head.appendChild(element("strong","portal-stars","★".repeat(item.rating)+"☆".repeat(5-item.rating)));
    head.appendChild(element("span","portal-muted","สมาชิก X-Stage · "+dateLabel(item.updated_at||item.created_at)));
    row.appendChild(head);
    if(item.comment)row.appendChild(element("p","",item.comment));
    if(user&&item.user_id===user.id){
      const edit=element("button","portal-small-button","แก้ไขรีวิวของฉัน");
      edit.type="button";
      edit.addEventListener("click",()=>{
        $("portal-rating").value=String(item.rating);
        $("portal-comment").value=item.comment||"";
        reviewForm.scrollIntoView({behavior:"smooth",block:"center"});
        $("portal-comment").focus();
      });
      row.appendChild(edit);
      const removeMine=element("button","portal-small-button portal-danger","ลบรีวิวของฉัน");
      removeMine.type="button";
      removeMine.addEventListener("click",async()=>{
        if(!window.confirm("ลบคะแนนและความคิดเห็นของคุณสำหรับแอปนี้?"))return;
        const result=await client.from("xstage_reviews").delete().eq("app_id",item.app_id).eq("user_id",user.id);
        if(result.error)window.alert(result.error.message);
        else await loadReviews(activeApp);
      });
      row.appendChild(removeMine);
    }
    if(isAdmin){
      const remove=element("button","portal-small-button portal-danger","ลบรีวิวผิดกฎ");
      remove.type="button";remove.addEventListener("click",async()=>{
        if(!window.confirm("ลบความคิดเห็นนี้?"))return;
        const r=await client.from("xstage_reviews").delete().eq("app_id",item.app_id).eq("user_id",item.user_id);
        if(r.error)window.alert(r.error.message);else await loadReviews(activeApp);
      });row.appendChild(remove);
    }
    return row;
  }
  async function loadReviews(appId){
    if(!reviewList||!reviewSummary||!appId)return;
    resetReviewArea();
    activeApp=appId;
    reviewForm.hidden=!user;
    if(!client){
      message(reviewSummary,"ยังไม่เปิดระบบรีวิว");
      message(reviewStatus,"กำลังรอเชื่อมต่อฐานข้อมูล X-Stage · เปิดดูรายละเอียดแอปได้ตามปกติ");
      return;
    }
    const [reviews,stats]=await Promise.all([
      client.from("xstage_reviews")
        .select("app_id,user_id,rating,comment,created_at,updated_at")
        .eq("app_id",appId).order("updated_at",{ascending:false}).limit(100),
      client.from("xstage_review_stats")
        .select("review_count,avg_rating").eq("app_id",appId).maybeSingle()
    ]);
    const {data,error}=reviews;
    if(activeApp!==appId)return;
    if(error){
      message(reviewSummary,"ไม่สามารถอ่านคะแนนได้");
      message(reviewStatus,error.message);
      return;
    }
    latestReviews=data||[];
    const shownCount=latestReviews.length;
    const exactCount=Number(stats.data?.review_count);
    const mean=Number(stats.data?.avg_rating);
    const fallbackAverage=shownCount?
      latestReviews.reduce((n,x)=>n+Number(x.rating||0),0)/shownCount:0;
    const count=stats.error?shownCount:exactCount||0;
    const average=stats.error?fallbackAverage:mean||0;
    message(reviewSummary,count?average.toFixed(1)+" / 5 ★ · "+count+" รีวิว"+
      (stats.error&&shownCount===100?" (คะแนนจาก 100 รีวิวล่าสุด)":""):"ยังไม่มีคะแนน");
    message(reviewStatus,user?"ให้คะแนน 1–5 ดาวและแสดงความคิดเห็นได้ 1 รีวิวต่อแอป":"ลงชื่อเข้าใช้ด้วย Google เพื่อเขียนรีวิว · ผู้เยี่ยมชมอ่านได้");
    reviewList.replaceChildren();
    if(!count)showInfo(reviewList,"ยังไม่มีความคิดเห็นสำหรับแอปนี้");
    latestReviews.forEach(row=>reviewList.appendChild(reviewRow(row)));
    const mine=latestReviews.find(row=>row.user_id===user?.id);
    $("portal-rating").value=String(mine?.rating||5);
    $("portal-comment").value=mine?.comment||"";
  }
  async function loadSession(){
    if(!client)return;
    const {data}=await client.auth.getUser();
    user=data?.user||null;
    refreshAccount();
    await Promise.all([loadHistory(),loadAdmin()]);
    if(activeApp)await loadReviews(activeApp);
  }
  async function signIn(){
    if(!client){
      window.alert("Google Login ยังไม่ได้เชื่อมต่อฐานข้อมูล X-Stage กรุณาตั้งค่า portal-config.js");
      return;
    }
    let redirectTo=location.origin+location.pathname+location.search;
    const native=window.XStagePortalAndroid?.openOAuth;
    if(native)redirectTo="xstageapps://auth";
    const {data,error}=await client.auth.signInWithOAuth({
      provider:"google",options:{redirectTo,skipBrowserRedirect:!!native}
    });
    if(error){window.alert("เข้าสู่ระบบไม่สำเร็จ: "+error.message);return;}
    if(native&&data?.url)window.XStagePortalAndroid.openOAuth(data.url);
  }
  async function completeNativeOAuth(uri){
    if(!client)return;
    try{
      const url=new URL(uri);
      if(url.protocol!=="xstageapps:"||url.hostname!=="auth")throw Error("ที่อยู่ตอบกลับไม่ถูกต้อง");
      const code=url.searchParams.get("code");
      if(!code)throw Error(url.searchParams.get("error_description")||"ไม่มีรหัสยืนยัน");
      const {error}=await client.auth.exchangeCodeForSession(code);
      if(error)throw error;
      await loadSession();
    }catch(error){window.alert("Google Login: "+error.message);}
  }
  window.XStagePortal={completeNativeOAuth};
  login?.addEventListener("click",signIn);
  logout?.addEventListener("click",async()=>{if(client)await client.auth.signOut();user=null;await loadSession();});
  reviewForm?.addEventListener("submit",async event=>{
    event.preventDefault();
    if(!user||!client||!activeApp)return;
    const rating=Number($("portal-rating").value),comment=$("portal-comment").value.trim();
    if(!Number.isInteger(rating)||rating<1||rating>5||comment.length>1000)return;
    const button=$("portal-review-submit");
    button.disabled=true;
    const {error}=await client.from("xstage_reviews").upsert({
      user_id:user.id,app_id:activeApp,rating,comment
    },{onConflict:"user_id,app_id"});
    button.disabled=false;
    if(error)message(reviewStatus,"บันทึกไม่ได้: "+error.message);
    else {message(reviewStatus,"บันทึกรีวิวแล้ว");await loadReviews(activeApp);}
  });
  document.addEventListener("click",event=>{
    const anchor=event.target.closest?.("a[href]");
    if(!anchor||!user)return;
    // Download clicks are not proof that an installer was opened or installed.
    const inDetail=!!anchor.closest("#detail-actions")&&anchor.classList.contains("primary");
    const inCard=anchor.matches(".app-card-download");
    if(!inDetail&&!inCard)return;
    const appId=inDetail?currentApp():anchor.closest("[data-app]")?.dataset.app;
    if(!appId)return;
    const href=anchor.getAttribute("href")||"";
    if(!/\.(apk|exe|zip)(\?|$)/i.test(href))return;
    let version="";
    const match=href.match(/-v(\d+\.\d+\.\d+(?:-preview\.\d+)?)/);
    if(match)version=match[1];
    void saveEvent(appId,"download_clicked",version).then(loadHistory);
  },true);
  // The storefront routes internally without page reload. Recheck on the next event loop.
  const updateRoute=()=>{
    const id=currentApp();
    if(id===activeApp)return;
    activeApp=id;
    if(id)void loadReviews(id);
  };
  window.addEventListener("popstate",updateRoute);
  document.addEventListener("click",event=>{
    if(event.target.closest?.('a[href^="?app="],#detail-back'))setTimeout(updateRoute,0);
  });
  if(!configured||!window.supabase?.createClient){
    message(reviewStatus,"ฐานข้อมูล X-Stage ยังไม่ได้เปิดใช้งาน · ดูแอปและดาวน์โหลดได้โดยไม่ต้องเข้าสู่ระบบ");
    login.disabled=true;login.title="รอการตั้งค่า Google Login";
    return;
  }
  client=window.supabase.createClient(config.supabaseUrl,config.supabasePublishableKey,{
    auth:{flowType:"pkce",detectSessionInUrl:true,persistSession:true,autoRefreshToken:true}
  });
  client.auth.onAuthStateChange((_event,session)=>{
    user=session?.user||null;
    refreshAccount();
    setTimeout(()=>{void loadHistory();void loadAdmin();if(activeApp)void loadReviews(activeApp);},0);
  });
  refreshAccount();
  updateRoute();
  void loadSession();
})();