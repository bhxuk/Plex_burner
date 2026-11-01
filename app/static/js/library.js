/* Library tab: everything in your save locations, with preview frames. */
"use strict";
const lib = { items: [], kind: "all", loaded: false };
const KIND = { dvd: ["DVD backup", "acc"], movie: ["Video", "green"], iso: ["Disc image", "blue"], collection: ["Collection", "violet"] };
const NOIMG = `<div class="noimg"><svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/></svg></div>`;

async function loadLibrary(refresh = false) {
  if (!lib.loaded) $("#libGrid").innerHTML = `<div class="panel empty">Scanning your library</div>`;
  try {
    lib.items = await api("api/library" + (refresh ? "?refresh=1" : ""));
    lib.loaded = true;
  } catch (e) { $("#libGrid").innerHTML = `<div class="panel empty">${esc(e.message)}</div>`; return; }
  $("#bLib").textContent = lib.items.length;
  const locs = [...new Set(lib.items.map(i => i.location_path))];
  const sel = $("#libLoc"), cur = sel.value;
  sel.innerHTML = `<option value="">All locations</option>` + locs.map(p => `<option value="${esc(p)}">${esc(lib.items.find(i => i.location_path === p).location)} · ${esc(p)}</option>`).join("");
  sel.value = locs.includes(cur) ? cur : "";
  renderLibrary();
}

function renderLibrary() {
  const q = $("#libSearch").value.trim().toLowerCase(), loc = $("#libLoc").value;
  const items = lib.items.filter(i => (lib.kind === "all" || i.kind === lib.kind) && (!loc || i.location_path === loc) && (!q || i.name.toLowerCase().includes(q)));
  $("#libCount").textContent = `${items.length} item${items.length === 1 ? "" : "s"} · ${fmtBytes(items.reduce((a, i) => a + i.size, 0))}`;
  $("#libGrid").innerHTML = items.map(i => {
    const [label, cls] = KIND[i.kind] || [i.kind, ""];
    return `<button class="card" data-id="${esc(i.id)}">
      <div class="th">${i.frames ? `<img loading="lazy" src="${esc(media(`api/frame/${i.id}/1.jpg`))}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'noimg',innerHTML:'No preview'}))">` : NOIMG}<span class="chip ${cls}">${esc(label)}</span></div>
      <div class="bd"><b title="${esc(i.name)}">${esc(i.name)}</b><span>${fmtBytes(i.size)} · ${esc(fmtDate(i.date))} · ${esc(i.location)}</span></div></button>`;
  }).join("") || `<div class="panel empty" style="grid-column:1/-1">${lib.items.length ? "Nothing matches your search." : "Your library is empty. Copied discs appear here."}</div>`;
}

function openItem(id) {
  const i = lib.items.find(x => x.id === id); if (!i) return;
  const [label, cls] = KIND[i.kind] || [i.kind, ""];
  const frames = i.frames ? [0, 1, 2, 3].map(n => `<img loading="lazy" src="${esc(media(`api/frame/${i.id}/${n}.jpg`))}" alt="Frame ${n + 1}" onerror="this.outerHTML='<div class=&quot;noimg&quot;>No frame</div>'">`).join("") : `<div class="noimg" style="grid-column:1/-1">No preview for disc images. Copy discs as MKV or MP4 to get previews.</div>`;
  openDrawer(i.name, `<span class="chip ${cls}">${esc(label)}</span>`, `
    <div class="actions" style="margin-bottom:14px"><button class="btn primary" id="itRename">Rename</button></div>
    <div class="frames">${frames}</div>
    <div class="section-t">Details</div>
    <dl class="kvs"><dt>Size</dt><dd>${fmtBytes(i.size)}</dd><dt>Added</dt><dd>${esc(new Date(i.date * 1000).toLocaleString())}</dd>
      <dt>Location</dt><dd>${esc(i.location)}</dd><dt>Path</dt><dd>${esc(i.path)}</dd></dl>`);
  $("#itRename").onclick = () => renameItem(i);
}

async function renameItem(i) {
  const isFolder = i.kind !== "movie" || !/\.[a-z0-9]{2,4}$/i.test(i.path);
  const r = await dialog("Rename", `
    <div class="field"><label>New name</label><input class="input" id="rnName" value="${esc(i.name)}" spellcheck="false" autocomplete="off">
      <span class="hint">Use <b>Movie Name (Year)</b>, for example <b>Charade (1963)</b>, so your media server finds the right film.
      ${isFolder ? "The folder and the video files inside it are renamed together." : "The file keeps its extension."}</span></div>`,
    [{ label: "Cancel", value: null }, { label: "Rename", cls: "primary", action: async body => {
      const name = $("#rnName", body).value.trim();
      if (!name || name === i.name) return false;
      return api(`api/library/${i.id}/rename`, { method: "POST", json: { name } });
    } }]);
  if (!r) return;
  toast("Renamed");
  await loadLibrary(true);
  if (r.id) openItem(r.id); else closeDrawer();
  loadHistory();
}
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "rnName") $("#dlgFoot .primary")?.click(); });

$("#libGrid").addEventListener("click", e => { const c = e.target.closest(".card"); if (c) openItem(c.dataset.id); });
$("#libSearch").addEventListener("input", renderLibrary);
$("#libLoc").addEventListener("change", renderLibrary);
$("#libRefresh").onclick = () => loadLibrary(true);
seg("#libKind", [["all", "All"], ["dvd", "DVD backups"], ["movie", "Videos"], ["iso", "Images"], ["collection", "Collections"]], "all", v => { lib.kind = v; renderLibrary(); });
Tabs.library = { enter: () => loadLibrary(false) };
