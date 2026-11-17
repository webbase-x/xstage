"use strict";
/* TV browser and Android WebView refresh. No hardcoded cache-bust parameters,
 * no private-session deletion, and no unsolicited automatic reloads. */
(function(){
  const button=document.getElementById("tv-refresh-window");
  if(!button)return;
  const ua=navigator.userAgent||"";
  const params=new URLSearchParams(location.search);
  const tvBrowser=/(Android TV|Google TV|AFT[A-Z0-9]+|SHIELD Android TV|BRAVIA)/i.test(ua)||
      params.get("tv")==="1"||params.get("source")==="android-tv"||
      document.body.classList.contains("xstage-native-tv");
  button.hidden=!tvBrowser;
  const refresh=()=>{window.location.reload();};
  window.XStageTvRefreshPage=refresh;
  button.addEventListener("click",refresh);
})();
