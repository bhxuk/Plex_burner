/* Plex Burner core: helpers, API, dialogs, drawer and tab routing. Loaded first. */
"use strict";
const DEMO = window.PB_DEMO === true || new URLSearchParams(location.search).has("demo");
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { tab: "disc", status: null, lastOk: 0, locations: [] };
const Tabs = {};          // each tab file registers { load, period, enter, leave }

/* ---------- formatting ---------- */
function fmtBytes(n, d = 1) {
  if (n == null || isNaN(n)) return "-";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"]; let i = 0;
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(n >= 100 ? 0 : d)) + " " + u[i];
}
function fmtDur(sec) {
  if (sec == null || sec < 0) return "-";
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  if (d) return `${d}d ${h}h`; if (h) return `${h}h ${m}m`; if (m) return `${m}m ${String(s).padStart(2, "0")}s`; return `${s}s`;
}
function fmtRuntime(sec) { if (!sec) return null; const h = Math.floor(sec / 3600), m = Math.round(sec % 3600 / 60); return h ? `${h}h ${m}m` : `${m} min`; }
function ago(ts) { if (!ts) return "never"; const s = Date.now() / 1000 - ts; return s < 60 ? "just now" : fmtDur(s).replace(/ \d+s$/, "") + " ago"; }
function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
function fmtDate(ts) { return new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }); }
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), 3200); }
const DVD_SIZE = 6e9;  // rough size of a full DVD copy, for "fits about N discs"

/* ---------- api ---------- */
async function api(path, opts = {}) {
  if (DEMO) return window.PBDemo.api(path, opts);
  const init = { ...opts, headers: { Accept: "application/json", ...(opts.headers || {}) } };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; delete init.json; }
  const r = await fetch(path, init);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
/* Image URLs go through here so the demo can supply its own pictures. */
function media(path) { return DEMO ? window.PBDemo.image(path) : path; }

/* ---------- dialogs & drawer ---------- */
function dialog(title, bodyHtml, buttons = [{ label: "Close" }]) {
  return new Promise(resolve => {
    const d = $("#dlg");
    $("#dlgTitle").textContent = title; $("#dlgBody").innerHTML = bodyHtml;
    $("#dlgFoot").innerHTML = buttons.map((b, i) => `<button class="btn ${b.cls || ""}" data-i="${i}">${esc(b.label)}</button>`).join("");
    const close = v => { d.classList.remove("open"); d.onclick = null; resolve(v); };
    d.onclick = async e => {
      if (e.target === d || e.target.closest("[data-close]")) return close(null);
      const btn = e.target.closest("#dlgFoot button"); if (!btn) return;
      const b = buttons[+btn.dataset.i];
      if (b.action) {
        btn.disabled = true;
        try { const r = await b.action($("#dlgBody")); if (r !== false) close(r ?? true); }
        catch (err) { toast(err.message); }
        btn.disabled = false;
      } else close(b.value ?? null);
    };
    d.classList.add("open");
    setTimeout(() => { const f = $("#dlgBody input, #dlgBody select"); if (f) f.focus(); }, 50);
  });
}
async function confirmDanger(title, html, label = "Confirm") {
  return dialog(title, `<p style="margin:0;color:var(--muted)">${html}</p>`, [{ label: "Cancel", value: false }, { label, cls: "primary", value: true }]);
}
function openDrawer(title, stateHtml, bodyHtml) {
  $("#drTitle").textContent = title; $("#drState").innerHTML = stateHtml || ""; $("#drBody").innerHTML = bodyHtml;
  $("#drawer").classList.add("open"); $("#scrim").classList.add("open");
}
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").classList.remove("open"); state.drawer = null; }
$("#drClose").onclick = closeDrawer; $("#scrim").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeDrawer(); $("#dlg").classList.remove("open"); } });

/* ---------- tabs ---------- */
let tabTimer = null;
function showTab(t, opts = {}) {
  if (!Tabs[t]) t = "disc";
  if (state.tab !== t && Tabs[state.tab]?.leave) Tabs[state.tab].leave();
  state.tab = t; history.replaceState(null, "", "#" + t);
  $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$("section.view").forEach(s => s.classList.toggle("active", s.id === "v-" + t));
  clearInterval(tabTimer);
  const tab = Tabs[t];
  if (tab.enter) tab.enter(opts); else if (tab.load) tab.load();
  if (tab.period && tab.load) tabTimer = setInterval(() => !document.hidden && tab.load(), tab.period);
  if (opts.anchor) setTimeout(() => document.getElementById(opts.anchor)?.scrollIntoView({ behavior: "smooth" }), 100);
}
$("#tabs").addEventListener("click", e => { const b = e.target.closest(".tab"); if (b) showTab(b.dataset.tab); });
document.addEventListener("click", e => {
  const a = e.target.closest("[data-goto]");
  if (a) { e.preventDefault(); showTab(a.dataset.goto, { anchor: a.dataset.anchor }); }
});

function feedHtml(log, empty = "Nothing yet") {
  return log.slice().reverse().map(e => `<div class="ev"><time>${esc(fmtTime(e.ts))}</time>${e.drive && e.drive !== "-" ? `<span class="chip">${esc(e.drive)}</span>` : ""}<span>${esc(e.text)}</span></div>`).join("") || `<div class="muted">${empty}</div>`;
}
function seg(el, options, value, onChange) {
  el = typeof el === "string" ? $(el) : el;
  el.innerHTML = options.map(([v, l]) => `<button data-v="${esc(v)}" class="${v === value ? "on" : ""}">${esc(l)}</button>`).join("");
  el.onclick = e => { const b = e.target.closest("button"); if (!b) return; $$("button", el).forEach(x => x.classList.toggle("on", x === b)); onChange(b.dataset.v); };
}

/* Locations are used by several tabs, so they are loaded here. */
async function loadLocations() {
  const r = await api("api/locations");
  state.locations = r.locations; state.roots = r.roots;
  $("#bLoc").textContent = r.locations.length;
  return r;
}
