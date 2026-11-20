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
  const guestLabel=$("portal-guest-label"), profile=$("portal-profile");
  const profileToggle=$("portal-profile-toggle"), profileMenu=$("portal-profile-menu");
  const profileName=$("portal-profile-name"), profileEmail=$("portal-profile-email");
  const avatarImage=$("portal-avatar-image"), avatarFallback=$("portal-avatar-fallback");
  const historySection=$("portal-history"), historyList=$("portal-history-list");
  const accountScreen=$("portal-account-screen"), accountBack=$("portal-account-back");
  const accountViews={overview:$("portal-account-overview"),personal:$("portal-account-personal"),
    history:historySection,reviews:$("portal-account-my-reviews")};
  const accountAvatar=$("portal-account-avatar"), accountInitials=$("portal-account-initials");
  const accountFullName=$("portal-account-full-name"), accountEmail=$("portal-account-email");
  const downloadCount=$("portal-download-count"), downloadSummary=$("portal-download-summary");
  const myReviewsList=$("portal-my-reviews-list");
  const reviewForm=$("portal-review-form"), reviewStatus=$("portal-reviews-status");
  const reviewList=$("portal-review-list"), reviewSummary=$("portal-rating-summary");
  const adminPanel=$("portal-admin"), adminEvents=$("portal-admin-events");
  const appIds=()=>Array.from(document.querySelectorAll(".app-card[data-app]")).map(c=>c.dataset.app);
  let client=null,user=null,isAdmin=false,activeApp=null,latestReviews=[],backendReady=false;
  let accountView="overview",accountLastFocus=null;
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
  function appMeta(appId){
    const card=Array.from(document.querySelectorAll(".app-card[data-app]")).find(c=>c.dataset.app===appId);
    return {name:card?.querySelector(".app-text h3")?.textContent?.trim()||appId,
      icon:card?.querySelector(".app-art img")?.getAttribute("src")||""};
  }
  function accountAppIcon(appId){
    const meta=appMeta(appId);
    const wrap=element("span","portal-account-app-icon");
    if(meta.icon){
      const image=element("img");image.src=meta.icon;image.alt="";image.loading="lazy";
      wrap.appendChild(image);
    }else wrap.textContent="↓";
    return wrap;
  }
  function closeAccountScreen(){
    if(!accountScreen||accountScreen.hidden)return;
    accountScreen.hidden=true;
    document.body.classList.remove("portal-account-open");
    if(accountLastFocus?.isConnected)accountLastFocus.focus();
    accountLastFocus=null;
  }
  function setAccountView(view){
    if(!Object.hasOwn(accountViews,view))view="overview";
    accountView=view;
    Object.entries(accountViews).forEach(([key,node])=>{if(node)node.hidden=key!==view;});
    const headings={overview:"บัญชี X-Stage",personal:"ข้อมูลส่วนตัว",
      history:"ประวัติการดาวน์โหลด",reviews:"คะแนนและความคิดเห็น"};
    message($("portal-account-title"),headings[view]);
    accountBack.setAttribute("aria-label",view==="overview"?"ปิดหน้าบัญชี":"กลับไปหน้าบัญชี");
    $("portal-account-scroll")?.scrollTo({top:0,behavior:"instant"});
    if(view==="history")void loadHistory();
    if(view==="reviews")void loadMyReviews();
  }
  function openAccountScreen(view="overview"){
    if(!user)return;
    accountLastFocus=document.activeElement;
    closeProfileMenu();
    accountScreen.hidden=false;
    document.body.classList.add("portal-account-open");
    setAccountView(view);
    accountBack.focus();
  }
  function displayName(account){
    const google=account?.identities?.find(identity=>identity.provider==="google")?.identity_data;
    return safeText(account?.user_metadata?.full_name || account?.user_metadata?.name ||
      google?.full_name || account?.email?.split("@")[0] || "สมาชิก X-Stage").trim().slice(0,80);
  }
  function googleAvatarUrl(account){
    const google=account?.identities?.find(identity=>identity.provider==="google")?.identity_data;
    const candidates=[google?.picture,google?.avatar_url,
      account?.user_metadata?.avatar_url,account?.user_metadata?.picture];
    for(const value of candidates){
      if(typeof value!=="string")continue;
      try{
        const url=new URL(value);
        const host=url.hostname.toLowerCase();
        // Only fetch Google-hosted account images, never arbitrary user-supplied URLs.
        if(url.protocol==="https:" && (host==="googleusercontent.com" ||
          host.endsWith(".googleusercontent.com") || host==="ggpht.com" ||
          host.endsWith(".ggpht.com")))return url.href;
      }catch{}
    }
    return "";
  }
  function initials(name){
    const parts=name.split(/\s+/).filter(Boolean);
    return (parts.length>1?(parts[0].slice(0,1)+parts[parts.length-1].slice(0,1)):
      (parts[0]||"X").slice(0,2)).toLocaleUpperCase("th-TH");
  }
  function closeProfileMenu(){
    profileMenu.hidden=true;
    profileToggle.setAttribute("aria-expanded","false");
  }
  function refreshAccount(){
    login.hidden=!!user;
    guestLabel.hidden=!!user;
    profile.hidden=!user;
    closeProfileMenu();
    if(user){
      const name=displayName(user);
      userLabel.textContent=name;
      profileName.textContent=name;
      profileEmail.textContent=safeText(user.email||"");
      profileToggle.setAttribute("aria-label","โปรไฟล์ Google ของ "+name+" · เปิดเมนูบัญชี");
      message(accountFullName,name);
      message(accountEmail,user.email||"");
      message($("portal-account-detail-name"),name);
      message($("portal-account-detail-email"),user.email||"");
      message(accountInitials,initials(name));
      avatarFallback.textContent=initials(name);
      avatarFallback.hidden=false;
      avatarImage.hidden=true;
      const photo=googleAvatarUrl(user);
      accountAvatar.hidden=true;
      accountInitials.hidden=false;
      if(photo){
        if(accountAvatar.getAttribute("src")!==photo)accountAvatar.src=photo;
        if(accountAvatar.complete&&accountAvatar.naturalWidth>0){
          accountAvatar.hidden=false;accountInitials.hidden=true;
        }
        if(avatarImage.src!==photo)avatarImage.src=photo;
        // Show the fallback until the image has loaded successfully.
        if(avatarImage.complete&&avatarImage.naturalWidth>0){
          avatarImage.hidden=false;
          avatarFallback.hidden=true;
        }
      }else{
        avatarImage.removeAttribute("src");
        accountAvatar.removeAttribute("src");
      }
    }else{
      accountAvatar.removeAttribute("src");
      accountAvatar.hidden=true;
      accountInitials.hidden=false;
      avatarImage.removeAttribute("src");
      avatarImage.hidden=true;
      avatarFallback.hidden=false;
      profileEmail.textContent="";
      userLabel.textContent="สมาชิก X-Stage";
    }
    if(!user)closeAccountScreen();
    reviewForm.hidden=!user||!activeApp||!canUsePortal();
  }
  avatarImage?.addEventListener("load",()=>{
    if(!user || avatarImage.src!==googleAvatarUrl(user))return;
    avatarImage.hidden=false;
    avatarFallback.hidden=true;
  });
  avatarImage?.addEventListener("error",()=>{
    avatarImage.hidden=true;
    avatarFallback.hidden=false;
  });
  accountAvatar?.addEventListener("load",()=>{
    if(!user||accountAvatar.src!==googleAvatarUrl(user))return;
    accountAvatar.hidden=false;
    accountInitials.hidden=true;
  });
  accountAvatar?.addEventListener("error",()=>{
    accountAvatar.hidden=true;
    accountInitials.hidden=false;
  });
  $("portal-open-account")?.addEventListener("click",()=>openAccountScreen());
  accountBack?.addEventListener("click",()=>{
    if(accountView!=="overview"){setAccountView("overview");accountBack.focus();}
    else closeAccountScreen();
  });
  document.querySelectorAll("[data-account-view]").forEach(button=>
    button.addEventListener("click",()=>setAccountView(button.dataset.accountView)));
  accountScreen?.addEventListener("click",event=>{
    if(event.target===accountScreen)closeAccountScreen();
  });
  profileToggle?.addEventListener("click",()=>{
    if(!user)return;
    const opening=profileMenu.hidden;
    profileMenu.hidden=!opening;
    profileToggle.setAttribute("aria-expanded",String(opening));
  });
  document.addEventListener("click",event=>{
    if(!profile.contains(event.target))closeProfileMenu();
  });
  document.addEventListener("keydown",event=>{
    if(accountScreen&&!accountScreen.hidden){
      if(event.key==="Escape"){
        event.preventDefault();
        if(accountView!=="overview")setAccountView("overview");
        else closeAccountScreen();
      }else if(event.key==="Tab"){
        const candidates=Array.from(accountScreen.querySelectorAll(
          'button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled])'))
          .filter(node=>!node.closest("[hidden]")&&node.getClientRects().length);
        const first=candidates[0],last=candidates[candidates.length-1];
        if(!first)return;
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
      }
      return;
    }
    if(event.key==="Escape"&&!profileMenu.hidden){
      closeProfileMenu();
      profileToggle.focus();
    }
  });
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
    const uid=user.id;
    historyList.replaceChildren();
    showInfo(historyList,"กำลังโหลดประวัติ…");
    const {data,error,count}=await client.from("xstage_download_events")
      .select("id,app_id,event_type,app_version,created_at",{count:"exact"})
      .eq("user_id",uid).order("created_at",{ascending:false}).limit(100);
    if(user?.id!==uid)return;
    historyList.replaceChildren();
    if(error){
      message(downloadSummary,"ไม่สามารถอ่านประวัติได้");
      downloadCount.hidden=true;
      showInfo(historyList,"อ่านประวัติไม่ได้: "+error.message);
      return;
    }
    const total=Number.isInteger(count)?count:(data?.length||0);
    message(downloadSummary,total?total+" กิจกรรมที่บันทึกไว้":"ยังไม่มีรายการดาวน์โหลด");
    downloadCount.textContent=total.toLocaleString("th-TH");
    downloadCount.hidden=!total;
    if(!data?.length){showInfo(historyList,"ยังไม่มีประวัติการดาวน์โหลด · เลือกแอปแล้วกดดาวน์โหลดเพื่อเริ่มบันทึก");return;}
    for(const item of data){
      const meta=appMeta(item.app_id);
      const line=element("article","portal-event portal-download-event");
      line.appendChild(accountAppIcon(item.app_id));
      const details=element("div","portal-download-meta");
      details.appendChild(element("strong","",meta.name));
      details.appendChild(element("span","portal-muted",dateLabel(item.created_at)+
        (item.app_version?" · รุ่น "+item.app_version:"")));
      const confirmed=item.event_type==="installation_confirmed";
      details.appendChild(element("span","portal-download-state"+(confirmed?" is-confirmed":""),
        confirmed?"✓ ผู้ใช้ยืนยันว่าติดตั้งแล้ว":"↓ กดดาวน์โหลด"));
      line.appendChild(details);
      if(item.event_type==="download_clicked"){
        const confirm=element("button","portal-small-button","ยืนยันการติดตั้ง");
        confirm.type="button";
        confirm.setAttribute("aria-label","ยืนยันว่าติดตั้ง "+meta.name+" แล้ว");
        confirm.addEventListener("click",async()=>{
          confirm.disabled=true;
          const ok=await saveEvent(item.app_id,"installation_confirmed",item.app_version||null);
          if(ok)await loadHistory();else{
            confirm.disabled=false;
            window.alert("บันทึกการยืนยันการติดตั้งไม่สำเร็จ");
          }
        });
        line.appendChild(confirm);
      }
      historyList.appendChild(line);
    }
    if(total>data.length)showInfo(historyList,"แสดง 100 กิจกรรมล่าสุดจากทั้งหมด "+total+" กิจกรรม");
    const clear=element("button","portal-small-button portal-danger portal-clear-history","ลบประวัติทั้งหมดของฉัน");
    clear.type="button";
    clear.addEventListener("click",async()=>{
      if(!window.confirm("ลบประวัติการกดดาวน์โหลดและการยืนยันติดตั้งทั้งหมดของบัญชีนี้?"))return;
      clear.disabled=true;
      const {error}=await client.from("xstage_download_events").delete().eq("user_id",uid);
      if(error){window.alert(error.message);clear.disabled=false;}
      else await loadHistory();
    });
    historyList.appendChild(clear);
  }
  async function loadMyReviews(){
    if(!user||!client)return;
    const uid=user.id;
    myReviewsList.replaceChildren();
    showInfo(myReviewsList,"กำลังโหลดความคิดเห็น…");
    const {data,error}=await client.from("xstage_reviews")
      .select("app_id,rating,comment,updated_at").eq("user_id",uid)
      .order("updated_at",{ascending:false}).limit(100);
    if(user?.id!==uid)return;
    myReviewsList.replaceChildren();
    if(error){showInfo(myReviewsList,"อ่านความคิดเห็นไม่ได้: "+error.message);return;}
    if(!data?.length){showInfo(myReviewsList,"ยังไม่มีรีวิว · คุณสามารถให้คะแนนได้จากหน้ารายละเอียดแต่ละแอป");return;}
    for(const item of data){
      const meta=appMeta(item.app_id);
      const link=element("a","portal-event portal-my-review");
      link.href="?app="+encodeURIComponent(item.app_id);
      link.appendChild(accountAppIcon(item.app_id));
      const body=element("div","portal-download-meta");
      body.appendChild(element("strong","",meta.name));
      body.appendChild(element("span","portal-stars","★".repeat(item.rating)+"☆".repeat(5-item.rating)));
      if(item.comment)body.appendChild(element("span","portal-review-excerpt",item.comment));
      body.appendChild(element("span","portal-muted",dateLabel(item.updated_at)));
      link.appendChild(body);
      link.appendChild(element("span","portal-account-chevron","›"));
      myReviewsList.appendChild(link);
    }
  }
  async function saveEvent(appId,eventType,version){
    if(!client||!user||!appIds().includes(appId))return;
    const {error}=await client.from("xstage_download_events").insert({
      user_id:user.id,app_id:appId,event_type:eventType,
      app_version:typeof version==="string"?version.slice(0,64):null,
      client_platform:navigator.userAgent.includes("XStageAppsPortal/")?"android-portal":"web"
    });
    if(error)console.warn("X-Stage history unavailable:",error.message);
    return !error;
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
    if(!client||!backendReady){
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
    if(!client||!backendReady)return;
    const {data}=await client.auth.getUser();
    user=data?.user||null;
    refreshAccount();
    await Promise.all([loadHistory(),loadAdmin()]);
    if(activeApp)await loadReviews(activeApp);
  }
  async function signIn(){
    if(!client||!backendReady){
      window.alert("Google Login ยังไม่พร้อม เพราะฐานข้อมูล xstage_ ยังไม่ได้ตั้งค่า");
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
  async function signOut(){
    closeAccountScreen();
    closeProfileMenu();
    if(client)await client.auth.signOut();
    user=null;
    refreshAccount();
    await loadSession();
  }
  logout?.addEventListener("click",signOut);
  $("portal-account-signout")?.addEventListener("click",signOut);
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
    if(!backendReady)return;
    setTimeout(()=>{void loadHistory();void loadAdmin();if(activeApp)void loadReviews(activeApp);},0);
  });
  login.disabled=true;
  refreshAccount();
  updateRoute();
  // Fail closed: do not enable account/review features until REST + RLS schema exists.
  void client.from("xstage_reviews").select("app_id").limit(0).then(async ({error})=>{
    if(error){
      message(reviewStatus,"ระบบ Google Login และรีวิวรอติดตั้งตาราง xstage_ ใน Supabase ISSQL");
      message(reviewSummary,"ยังไม่เปิดระบบรีวิว");
      login.title="ฐานข้อมูล xstage_ ยังไม่พร้อม";
      return;
    }
    backendReady=true;
    login.disabled=false;
    login.title="เข้าสู่ระบบด้วยบัญชี Google";
    refreshAccount();
    await loadSession();
  });
})();