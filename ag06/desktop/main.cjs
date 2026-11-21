"use strict";
const {app,BrowserWindow,session,shell}=require("electron");
const path=require("node:path");
const {pathToFileURL}=require("node:url");
let win=null;
function createWindow(){
  const page=app.isPackaged
    ?path.join(process.resourcesPath,"ag06-web","index.html")
    :path.resolve(__dirname,"..","index.html");
  const trusted=pathToFileURL(page).href;
  session.defaultSession.setPermissionRequestHandler((webContents,permission,callback,details)=>{
    const url=webContents.getURL();
    const audioOnly=permission==="media" && details.mediaTypes?.includes("audio")
      && !details.mediaTypes?.includes("video");
    callback(Boolean(audioOnly&&url.startsWith(trusted)));
  });
  win=new BrowserWindow({
    width:1280,height:850,minWidth:360,minHeight:580,
    autoHideMenuBar:true,backgroundColor:"#0c111d",
    webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}
  });
  win.webContents.setWindowOpenHandler(({url})=>{
    if(/^https:\/\/(usa\.yamaha\.com|github\.com)\//i.test(url))void shell.openExternal(url);
    return {action:"deny"};
  });
  win.webContents.on("will-navigate",(event,url)=>{
    if(url===trusted)return;
    event.preventDefault();
    if(/^https:\/\/(usa\.yamaha\.com|github\.com)\//i.test(url))void shell.openExternal(url);
  });
  win.loadFile(page);
  win.on("closed",()=>{win=null;});
}
app.whenReady().then(()=>{
  createWindow();
  app.on("activate",()=>{if(BrowserWindow.getAllWindows().length===0)createWindow();});
});
app.on("window-all-closed",()=>{if(process.platform!=="darwin")app.quit();});
