"use strict";
const HOST = "com.xstage.download_manager";
const isWebUrl = value => /^https?:\/\/[^ ]+$/i.test(value || "");
async function handOff(url) {
  if (!isWebUrl(url)) return false;
  try {
    const response = await chrome.runtime.sendNativeMessage(HOST, { type: "enqueue", url });
    return response?.ok === true;
  } catch (error) {
    console.warn("X-Stage app is not connected; browser download stays untouched", String(error));
    return false;
  }
}
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "xstage-send", title: "ดาวน์โหลดด้วย X-Stage", contexts: ["link", "page", "video"] });
});
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.pageUrl || tab?.url;
  if (url) await handOff(url);
});
chrome.downloads.onCreated.addListener(async item => {
  const preference = await chrome.storage.local.get({ enabled: false });
  if (!preference.enabled || item.byExtensionId === chrome.runtime.id) return;
  const url = item.finalUrl || item.url;
  if (!isWebUrl(url) || /\/xstage-download-manager-v[\d.]+-build\d+-win-x64-setup\.exe(?:[?#]|$)/i.test(url)) return;
  const before = await chrome.downloads.search({ id: item.id });
  if (!before.some(x => x.state === "in_progress")) return;
  // Cancel the original only after the desktop application ACKNOWLEDGES the job.
  if (!(await handOff(url))) return;
  const latest = await chrome.downloads.search({ id: item.id });
  if (latest.some(x => x.state === "in_progress")) {
    try { await chrome.downloads.cancel(item.id); }
    catch (error) { console.warn("Chrome download was already completed", String(error)); }
  }
});
