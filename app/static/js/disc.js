/* Disc tab and header: one card per drive with preview frames, name, folder and copy progress. */
"use strict";
const STATUS = {
  idle: ["idle", "Empty"], detecting: ["busy", "Reading disc"], waiting: ["ok", "Ready to copy"],
  copying: ["busy", "Copying"], done: ["ok", "Done"], error: ["crit", "Needs attention"], unsupported: ["warn", "Can't read disc"],
};
const FORMAT_LABEL = { mkv: "MKV, original quality", mp4: "MP4, converted", folder: "full disc backup" };
const BROWSE = "__browse__";
const ui = {};   // per drive: { el, id, frame, stageSrc, stripKey, nameDirty, destKey }
let histKey = null;

const DISC_SVG = `<svg viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2"><circle cx="60" cy="60" r="54"/><circle cx="60" cy="60" r="16"/><circle cx="60" cy="60" r="5"/><path d="M60 14a46 46 0 0 1 46 46" stroke-linecap="round" opacity=".6"/><path d="M60 28a32 32 0 0 1 32 32" stroke-linecap="round" opacity=".35"/></svg>`;

function driveBlock(d) {
  const el = document.createElement("div");
  el.className = "drive grid g2b"; el.dataset.drive = d.drive;
  el.innerHTML = `
    <div class="panel">
      <h3><span class="dname">${esc(d.drive)}</span><span class="dmodel muted">${esc(d.model)}</span><span class="right stage-note"></span></h3>
      <div class="stage"><img class="main" alt="" hidden><div class="ph">${DISC_SVG}<b class="ph-txt"></b></div>
        <div class="overlay"></div><div class="live-tag" hidden><span class="chip">LIVE</span></div></div>
      <div class="strip"></div>
    </div>
    <div class="panel">
      <h3>Disc <span class="right disc-chip"></span></h3>
      <div class="dtitle">No disc</div><div class="chips"></div><div class="dmsg"></div>
      <div class="dform" hidden>
        <div class="field"><label>Name</label>
          <input class="input d-name" maxlength="160" autocomplete="off" spellcheck="false" placeholder="Movie Name (Year)">
          <span class="hint">Use <b>Movie Name (Year)</b> so Plex, Jellyfin or Emby match it automatically.</span></div>
        <div class="field"><label>Save to</label><select class="select d-dest"></select><span class="hint d-dest-hint"></span></div>
      </div>
      <div class="dprog" hidden>
        <div class="phase"><b class="p-phase"></b><span class="p-fmt"></span></div>
        <div class="bar big"><i></i></div>
        <div class="stats"><div><span>Progress</span><b class="s-pct">0%</b></div><div><span>Written</span><b class="s-copied">-</b></div>
          <div><span>Speed</span><b class="s-speed">-</b></div><div><span>Time left</span><b class="s-eta">-</b></div></div>
      </div>
      <div class="actions mt"><button class="btn primary lg d-copy" hidden>Copy disc</button><button class="btn danger d-cancel" hidden>Cancel copy</button><button class="btn d-eject">Eject</button></div>
      <div class="countdown" hidden></div>
    </div>`;
  const q = s => $(s, el);
  const name = d.drive;
  const nameInput = q(".d-name"), dest = q(".d-dest");
  nameInput.addEventListener("input", () => { ui[name].nameDirty = true; sendPending(name); });
  nameInput.addEventListener("keydown", e => { if (e.key === "Enter") q(".d-copy").click(); });
  dest.addEventListener("change", async () => {
    const s = driveState(name);
    if (dest.value === BROWSE) {
      const path = await pickFolder("Save this disc to", s?.destination);
      if (path) {
        await api("api/locations", { method: "POST", json: { path } }).catch(err => toast(err.message));
        await loadLocations(); ui[name].destKey = null; renderForm(driveState(name)); dest.value = path;
      } else dest.value = s?.destination;
    }
    destHint(name); sendPending(name);
  });
  q(".d-copy").onclick = async () => {
    const btn = q(".d-copy"); btn.disabled = true;
    try {
      await api(`api/drive/${name}/copy`, { method: "POST", json: { name: nameInput.value.trim(), destination: dest.value === BROWSE ? null : dest.value } });
      ui[name].nameDirty = false; toast("Copy started");
    } catch (e) { toast(e.message); }
    btn.disabled = false; loadStatus();
  };
  q(".d-cancel").onclick = async () => {
    if (!await confirmDanger("Cancel this copy?", "Anything copied so far is deleted. The disc stays in the drive so you can try again.", "Cancel copy")) return;
    try { await api(`api/drive/${name}/cancel`, { method: "POST" }); toast("Copy cancelled"); } catch (e) { toast(e.message); }
    loadStatus();
  };
  q(".d-eject").onclick = async () => {
    try { await api(`api/drive/${name}/eject`, { method: "POST" }); toast("Ejected"); } catch (e) { toast(e.message); }
    loadStatus();
  };
  q(".strip").addEventListener("click", e => {
    const b = e.target.closest("button[data-f]"); if (!b) return;
    ui[name].frame = +b.dataset.f; ui[name].stripKey = null; ui[name].pinFrame = true;
    renderStage(driveState(name));
  });
  return el;
}

const driveState = name => state.status?.drives.find(d => d.drive === name);

async function loadStatus() {
  try {
    const s = await api("api/status");
    state.status = s; state.lastOk = Date.now();
    renderHeader(s); renderDrives(s);
    $("#live").classList.remove("stale"); $("#liveTxt").textContent = "live";
  } catch {
    $("#live").classList.add("stale"); $("#liveTxt").textContent = "offline";
  }
}

function renderHeader(s) {
  const drives = s.drives, copying = drives.filter(d => d.status === "copying");
  let cls = "idle", label = "Idle";
  if (copying.length) { cls = "busy"; label = copying.length > 1 ? `Copying ${copying.length} discs` : `Copying ${copying[0].progress}%`; }
  else if (drives.some(d => d.status === "error")) { cls = "crit"; label = "Needs attention"; }
  else if (drives.some(d => d.status === "waiting")) { cls = "ok"; label = "Ready to copy"; }
  else if (drives.some(d => d.status === "done")) { cls = "ok"; label = "Done"; }
  else if (!drives.length) { cls = "warn"; label = "No drive found"; }
  $("#statusPill").className = "pill " + cls; $("#statusTxt").textContent = label;
  document.body.classList.toggle("copying", copying.length > 0);
  $("#hDrive").textContent = drives.length === 1 ? drives[0].device : `${drives.length} drive${drives.length === 1 ? "" : "s"}`;
  $("#hDriveTxt").textContent = drives.map(d => d.status === "idle" ? `${d.drive} empty` : `${d.drive}: ${d.status === "copying" ? d.name + " " + d.progress + "%" : d.suggested || STATUS[d.status]?.[1]}`).join(" · ") || "Plug in a DVD drive";
  $("#updPill").hidden = !s.update_available; $("#bUpd").hidden = !s.update_available;
  $("#fVer").textContent = "v" + s.version;
  document.title = copying.length ? `${copying[0].progress}% · Plex Burner` : "Plex Burner";
}

function renderDrives(s) {
  const box = $("#drives");
  if (!s.drives.length) {
    box.innerHTML = `<div class="panel empty"><b>No disc drive found.</b><br>Plug in a DVD drive. It shows up here within a few seconds.</div>`;
    for (const k of Object.keys(ui)) delete ui[k];
  } else {
    if (!box.querySelector(".drive")) box.innerHTML = "";
    for (const d of s.drives) {
      if (!ui[d.drive]) { ui[d.drive] = { el: driveBlock(d), id: null, frame: 0 }; box.appendChild(ui[d.drive].el); }
    }
    for (const name of Object.keys(ui)) {
      if (!s.drives.some(d => d.drive === name)) { ui[name].el.remove(); delete ui[name]; }
    }
    for (const d of s.drives) renderDrive(d);
  }
  $("#feedMini").innerHTML = feedHtml(s.log.slice(-8), "Nothing has happened yet.");
  if (state.tab === "settings") $("#feedFull").innerHTML = feedHtml(s.log);
  const hk = s.drives.map(d => d.status + d.disc_id).join();
  if (hk !== histKey) { histKey = hk; loadHistory(); if (s.drives.some(d => d.status === "done")) loadLocations().catch(() => {}); }
}

function discChips(d) {
  const i = d.disc_info || {}, chips = [];
  if (d.disc_type === "dvd") chips.push(`<span class="chip acc">DVD</span>`);
  if (d.disc_type === "data") chips.push(`<span class="chip blue">${esc(i.source || "Data disc")}</span>`);
  if (fmtRuntime(i.duration)) chips.push(`<span class="chip">${esc(fmtRuntime(i.duration))}</span>`);
  if (i.chapters) chips.push(`<span class="chip">${i.chapters} chapters</span>`);
  if (i.titles > 1) chips.push(`<span class="chip">${i.titles} titles</span>`);
  if (i.format) chips.push(`<span class="chip">${esc(i.format)}${i.aspect ? " " + esc(i.aspect) : ""}</span>`);
  if (i.resolution) chips.push(`<span class="chip">${esc(i.resolution)}</span>`);
  (i.audio || []).slice(0, 3).forEach(a => chips.push(`<span class="chip violet">${esc(a)}</span>`));
  if ((i.subtitles || []).length) chips.push(`<span class="chip">${i.subtitles.length} subtitle${i.subtitles.length > 1 ? "s" : ""}</span>`);
  if (d.disc_type === "data" && i.videos != null) chips.push(`<span class="chip ${i.videos ? "green" : ""}">${i.videos} video file${i.videos === 1 ? "" : "s"}${i.video_bytes ? " · " + fmtBytes(i.video_bytes) : ""}</span>`);
  if (d.disc_type === "data" && i.files) chips.push(`<span class="chip">${i.files} files</span>`);
  if (i.size) chips.push(`<span class="chip">${fmtBytes(i.size)} disc</span>`);
  return chips.join("");
}

function renderStage(d) {
  const u = ui[d.drive], el = u.el, copying = d.status === "copying";
  if (u.id !== d.disc_id) { u.id = d.disc_id; u.frame = 0; u.nameDirty = false; u.pinFrame = false; }
  const live = copying && d.live_preview && !u.pinFrame;
  let src = null, note = "";
  if (live) { src = media(`api/drive/${d.drive}/live.jpg?t=${d.live_preview}`); note = "live from the copy"; }
  else if (d.previews > 0) { u.frame = Math.min(u.frame, d.previews - 1); src = media(`api/drive/${d.drive}/preview/${u.frame}.jpg?d=${d.disc_id}`); note = "read from the disc"; }
  if (src !== u.stageSrc) {
    u.stageSrc = src;
    const img = $("img.main", el);
    if (src) { img.style.opacity = 0; img.onload = () => { img.style.opacity = 1; }; img.src = src; }
    img.hidden = !src; $(".ph", el).hidden = !!src;
  }
  $(".stage-note", el).textContent = note;
  $(".live-tag", el).hidden = !live;
  const phText = {
    idle: "Insert a DVD or data disc", detecting: "Reading the disc", unsupported: "This disc can't be read",
    copying: d.disc_type === "dvd" ? "Starting the copy. The picture appears in a moment." : "Copying the disc. Video appears once it is converting.",
    waiting: d.disc_type === "dvd" ? "Reading preview frames from the disc" : "Ready to copy",
    done: "Copy finished", error: "Something went wrong",
  };
  $(".ph-txt", el).textContent = phText[d.status] || "";
  $(".stage", el).classList.toggle("spin", ["detecting", "copying"].includes(d.status) || (d.status === "waiting" && d.disc_type === "dvd" && !d.previews));
  $(".overlay", el).innerHTML = d.disc_type ? `<span class="chip">${d.disc_type === "dvd" ? "DVD" : "DATA"}</span>${fmtRuntime(d.disc_info?.duration) ? `<span class="chip">${esc(fmtRuntime(d.disc_info.duration))}</span>` : ""}` : "";
  const showStrip = d.disc_type === "dvd" && ["waiting", "copying", "done", "error"].includes(d.status);
  const key = `${d.disc_id}:${d.previews}:${u.frame}:${showStrip}:${live}`;
  if (key !== u.stripKey) {
    u.stripKey = key;
    const strip = $(".strip", el);
    strip.hidden = !showStrip;
    strip.innerHTML = showStrip ? [0, 1, 2, 3].map(i => i < d.previews
      ? `<button data-f="${i}" class="${i === u.frame && !live ? "on" : ""}" title="Frame ${i + 1}"><img src="${esc(media(`api/drive/${d.drive}/preview/${i}.jpg?d=${d.disc_id}`))}" alt="Preview frame ${i + 1}"></button>`
      : `<button disabled>${d.status === "waiting" ? `<span class="wait"></span>` : ""}</button>`).join("") : "";
  }
}

function renderForm(d) {
  if (!d) return;
  const u = ui[d.drive], el = u.el;
  const canStart = ["waiting", "error"].includes(d.status) && !!d.disc_type;
  $(".dform", el).hidden = !canStart;
  $(".d-copy", el).hidden = !canStart;
  $(".d-cancel", el).hidden = d.status !== "copying";
  $(".d-eject", el).disabled = d.status === "copying" || d.status === "idle";
  if (!canStart) return;
  const name = $(".d-name", el), dest = $(".d-dest", el);
  if (!u.nameDirty && document.activeElement !== name) name.value = d.name || d.suggested || "";
  const locKey = d.disc_id + ":" + state.locations.map(l => l.path + l.free).join("|") + ":" + d.destination;
  if (locKey !== u.destKey && document.activeElement !== dest) {
    u.destKey = locKey;
    const opts = state.locations.filter(l => l.available).map(l => `<option value="${esc(l.path)}" ${l.path === d.destination ? "selected" : ""}>${esc(l.name)} · ${esc(l.path)}</option>`);
    if (!state.locations.some(l => l.path === d.destination)) opts.unshift(`<option value="${esc(d.destination)}" selected>${esc(d.destination)}</option>`);
    dest.innerHTML = opts.join("") + `<option value="${BROWSE}">Choose another folder...</option>`;
  }
  destHint(d.drive);
}

function destHint(name) {
  const el = ui[name].el, d = driveState(name);
  const loc = state.locations.find(l => l.path === $(".d-dest", el).value);
  const free = loc?.free, hint = $(".d-dest-hint", el);
  const fmt = `Saved as ${FORMAT_LABEL[d?.format] || "MKV"} in its own folder. Change the format in Settings.`;
  if (free == null) { hint.textContent = fmt; return; }
  const fits = Math.floor(free / DVD_SIZE);
  hint.innerHTML = (free < 10e9 ? `<span style="color:var(--red)">Only ${fmtBytes(free)} free. A DVD needs 4 to 8 GB.</span>` : `${fmtBytes(free)} free, room for about ${fits} more DVD${fits === 1 ? "" : "s"}.`) + " " + esc(fmt);
}

function renderProgress(d) {
  const el = ui[d.drive].el, show = ["copying", "done"].includes(d.status);
  $(".dprog", el).hidden = !show;
  if (!show) return;
  const bar = $(".bar", el);
  bar.classList.toggle("indet", d.status === "copying" && !d.progress);
  $("i", bar).style.width = d.progress + "%";
  $("i", bar).style.background = d.status === "done" ? "var(--green)" : "var(--acc)";
  $(".p-phase", el).textContent = d.phase || "";
  $(".p-fmt", el).textContent = d.format ? FORMAT_LABEL[d.format] : "";
  $(".s-pct", el).textContent = d.progress + "%";
  $(".s-copied", el).textContent = d.copied ? fmtBytes(d.copied) : "-";
  $(".s-copied", el).title = d.total ? `about ${fmtBytes(d.total)} in total` : "";
  $(".s-speed", el).textContent = d.speed ? fmtBytes(d.speed) + "/s" : "-";
  $(".s-eta", el).textContent = d.status === "done" ? "done" : d.eta != null ? fmtDur(d.eta) : "-";
}

function renderDrive(d) {
  const el = ui[d.drive].el;
  renderStage(d);
  $(".dtitle", el).textContent = ["copying", "done"].includes(d.status) ? d.name : d.suggested || (d.status === "idle" ? "No disc" : "Unknown disc");
  $(".chips", el).innerHTML = discChips(d);
  $(".disc-chip", el).innerHTML = d.status === "copying" ? `<span class="chip acc">${d.progress}%</span>` : `<span class="chip">${esc(STATUS[d.status]?.[1] || d.status)}</span>`;
  $(".dmsg", el).textContent = d.message;
  renderForm(d); renderProgress(d);
  const cd = $(".countdown", el);
  cd.hidden = d.auto_start_in == null;
  if (d.auto_start_in != null) cd.textContent = `Copies automatically in ${Math.floor(d.auto_start_in / 60)}:${String(d.auto_start_in % 60).padStart(2, "0")}. Typing a name restarts the timer. Change this in Settings.`;
}

async function loadHistory() {
  const items = await api("api/history").catch(() => []);
  $("#histList").innerHTML = items.slice(0, 8).map(h => `<div class="it">
      <span class="ic"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/></svg></span>
      <div class="tt"><b>${esc(h.name)}</b><span>${fmtBytes(h.size)} · ${esc((h.format || "").toUpperCase() || (h.type === "dvd" ? "DVD" : "DATA"))} · took ${esc(fmtDur(h.seconds).replace(/ \d+s$/, ""))} · ${esc(h.path)}</span></div>
      <time title="${esc(new Date(h.date * 1000).toLocaleString())}">${esc(ago(h.date))}</time></div>`).join("") || `<div class="muted">Nothing copied yet. Insert a disc to start.</div>`;
}

/* Typing a name or picking a folder is sent to the server, so auto-start uses it and the countdown restarts. */
const pendingTimers = {};
function sendPending(name) {
  clearTimeout(pendingTimers[name]);
  pendingTimers[name] = setTimeout(() => {
    const el = ui[name]?.el; if (!el) return;
    const dest = $(".d-dest", el).value;
    api(`api/drive/${name}/pending`, { method: "POST", json: { name: $(".d-name", el).value, destination: dest === BROWSE ? null : dest } }).then(loadStatus).catch(() => {});
  }, 500);
}
Tabs.disc = { enter: () => { if (state.status) renderDrives(state.status); } };
