"use strict";
const checkbox = document.getElementById("enabled");
const status = document.getElementById("status");
chrome.storage.local.get({ enabled: false }).then(p => { checkbox.checked = p.enabled === true; });
checkbox.addEventListener("change", () => chrome.storage.local.set({ enabled: checkbox.checked }));
async function check() {
  status.textContent = "กำลังตรวจสอบ...";
  try {
    const result = await chrome.runtime.sendNativeMessage("com.xstage.download_manager", { type: "ping" });
    status.textContent = result?.ok ? "เชื่อมต่อ X-Stage Download Manager สำเร็จ" : "ยังไม่พบแอปที่เชื่อมต่อ";
    status.style.color = result?.ok ? "#0b8559" : "#b34040";
  } catch (error) {
    status.textContent = "ยังไม่เชื่อมต่อ: เปิดแอป X-Stage แล้วกด “เชื่อม Chrome / Edge” เพื่อจับคู่";
    status.style.color = "#b34040";
  }
}
document.getElementById("check").addEventListener("click", check);
check();
