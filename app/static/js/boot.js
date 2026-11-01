/* Starts the app: demo data if needed, the 2 second status loop, then the tab from the URL. */
"use strict";
(async function boot() {
  if (DEMO) {
    $("#demoBanner").hidden = false;
    if (!window.PBDemo) await new Promise((res, rej) => { const s = document.createElement("script"); s.src = "assets/demo.js"; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  }
  await loadLocations().catch(() => {});
  await loadStatus();
  setInterval(() => !document.hidden && loadStatus(), 2000);
  api("api/library").then(items => { $("#bLib").textContent = items.length; }).catch(() => {});
  const t = location.hash.slice(1);
  showTab(Tabs[t] ? t : "disc");
  window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (Tabs[h] && h !== state.tab) showTab(h); });
  // Demo only: ?open=<library item id> opens its details, used for the website screenshots.
  const open = DEMO && new URLSearchParams(location.search).get("open");
  if (open) setTimeout(() => openItem(open), 400);
})();
