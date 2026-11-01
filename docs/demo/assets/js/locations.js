/* Locations tab and the folder picker used across the app. */
"use strict";

function renderLocations() {
  const locs = state.locations;
  $("#locList").innerHTML = locs.map(l => {
    const used = l.total ? (l.total - l.free) / l.total * 100 : 0;
    const fits = l.free != null ? Math.floor(l.free / DVD_SIZE) : null;
    return `<div class="panel loc ${l.default ? "def" : ""}" data-path="${esc(l.path)}">
      <div class="top-row"><span class="nm" title="${esc(l.name)}">${esc(l.name)}</span>${l.default ? `<span class="chip acc">default</span>` : ""}${l.available ? "" : `<span class="chip red">not available</span>`}</div>
      <div class="path">${esc(l.path)}</div>
      <div class="bar"><i style="width:${used.toFixed(1)}%;background:${used > 90 ? "var(--red)" : used > 75 ? "var(--amber)" : "var(--acc)"}"></i></div>
      <div class="nums"><div><span>Free</span><b>${fmtBytes(l.free)}</b></div><div><span>Disk size</span><b>${fmtBytes(l.total)}</b></div><div><span>Room for</span><b>${fits == null ? "-" : "~" + fits + " DVDs"}</b></div></div>
      <div class="actions">${l.default ? "" : `<button class="btn sm" data-act="default">Make default</button>`}<button class="btn sm" data-act="rename">Rename</button><button class="btn sm" data-act="browse">Browse</button>${l.default ? "" : `<button class="btn sm danger" data-act="remove">Remove</button>`}</div>
    </div>`;
  }).join("") || `<div class="panel empty">No locations yet.</div>`;
  $("#locRoots").innerHTML = `Plex Burner can save inside these folders on the server: ${(state.roots || []).map(r => `<code>${esc(r)}</code>`).join(", ")}. Add more with <code>MEDIA_PATH</code> and <code>EXTRA_PATH</code> in <code>.env</code>.`;
}

async function loadLocationsTab() {
  try { await loadLocations(); renderLocations(); } catch (e) { $("#locList").innerHTML = `<div class="panel empty">${esc(e.message)}</div>`; }
}

$("#locList").addEventListener("click", async e => {
  const b = e.target.closest("button[data-act]"); if (!b) return;
  const path = b.closest(".loc").dataset.path, loc = state.locations.find(l => l.path === path);
  try {
    if (b.dataset.act === "default") { await api("api/locations", { method: "PUT", json: { path, default: true } }); toast(`New discs go to ${loc.name}`); }
    if (b.dataset.act === "rename") {
      const name = await dialog("Rename location", `<div class="field"><label>Name</label><input class="input" id="locName" value="${esc(loc.name)}"></div>`,
        [{ label: "Cancel", value: null }, { label: "Save", cls: "primary", action: body => $("#locName", body).value.trim() || false }]);
      if (!name) return;
      await api("api/locations", { method: "PUT", json: { path, name } });
    }
    if (b.dataset.act === "browse") { await pickFolder(`Inside ${loc.name}`, path, { browseOnly: true }); return; }
    if (b.dataset.act === "remove") {
      if (!await confirmDanger(`Remove ${loc.name}?`, "Only the shortcut is removed. Nothing in the folder is deleted.", "Remove")) return;
      await api("api/locations", { method: "DELETE", json: { path } });
    }
  } catch (err) { toast(err.message); }
  loadLocationsTab();
});

$("#locAdd").onclick = async () => {
  const path = await pickFolder("Add a location", null, { askName: true });
  if (!path) return;
  loadLocationsTab();
};

/* Folder picker in the side drawer. Resolves with the chosen path, or null. */
function pickFolder(title, start, opts = {}) {
  return new Promise(resolve => {
    let current = null, done = false;
    const finish = v => {
      if (done) return;
      done = true; $("#drClose").onclick = $("#scrim").onclick = closeDrawer;
      closeDrawer(); resolve(v);
    };
    $("#drClose").onclick = $("#scrim").onclick = () => finish(null);
    async function go(path) {
      let r;
      try { r = await api("api/folders" + (path ? "?path=" + encodeURIComponent(path) : "")); }
      catch (e) { toast(e.message); if (!current) finish(null); return; }
      current = r.path;
      openDrawer(title, r.free != null ? `<span class="chip">${fmtBytes(r.free)} free</span>` : "", `
        <div class="browser">
          <div class="row"><select class="select" id="pkRoot">${r.roots.map(x => `<option value="${esc(x)}" ${r.path === x || r.path.startsWith(x + "/") ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
            <button class="btn" id="pkUp" ${r.parent ? "" : "disabled"}>Up one level</button></div>
          <div class="crumbs">${esc(r.path)}</div>
          <ul id="pkList">${r.dirs.map(d => `<li data-d="${esc(d)}"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>${esc(d)}</li>`).join("") || `<li class="none">No folders here</li>`}</ul>
          <div class="row"><input class="input" id="pkNew" placeholder="New folder name, e.g. Kids Films" style="flex:1"><button class="btn" id="pkMk">Create folder</button></div>
          ${opts.browseOnly ? "" : `${opts.askName ? `<div class="field mt"><label>Location name</label><input class="input" id="pkName" placeholder="${esc(r.path.split("/").pop())}"></div>` : ""}
          <div class="row mt"><button class="btn primary lg" id="pkUse" style="flex:1">${opts.askName ? "Add this folder" : "Use this folder"}</button>
          ${opts.askName ? `<label class="row" style="gap:8px;font-size:13px"><input type="checkbox" id="pkDef"> Make it the default</label>` : ""}</div>`}
        </div>`);
      $("#pkRoot").onchange = e => go(e.target.value);
      $("#pkUp").onclick = () => r.parent && go(r.parent);
      $("#pkList").onclick = e => { const li = e.target.closest("li[data-d]"); if (li) go(r.path.replace(/\/$/, "") + "/" + li.dataset.d); };
      $("#pkMk").onclick = async () => {
        const name = $("#pkNew").value.trim(); if (!name) return;
        try { const c = await api("api/folders", { method: "POST", json: { path: r.path, name } }); toast("Folder created"); go(c.path); } catch (err) { toast(err.message); }
      };
      const use = $("#pkUse");
      if (use) use.onclick = async () => {
        if (opts.askName) {
          try { await api("api/locations", { method: "POST", json: { path: current, name: $("#pkName").value.trim(), default: $("#pkDef").checked } }); toast("Location added"); }
          catch (err) { toast(err.message); return; }
        }
        finish(current);
      };
    }
    go(start);
  });
}

Tabs.locations = { enter: loadLocationsTab };
