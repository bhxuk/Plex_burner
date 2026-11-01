/* Updates tab: version check and one-click self-update. The changelog lives on the website. */
"use strict";
let updPoll = null;
async function loadUpdates(force = false) {
  const b = $("#uCheck"); b.disabled = true; b.textContent = "Checking";
  try { renderUpdates(await api(`api/update?check=true&force=${force}`)); }
  catch (e) { $("#uState").innerHTML = `<div class="notice bad">${esc(e.message)}</div>`; }
  b.disabled = false; b.textContent = "Check now";
}
function renderUpdates(u) {
  $("#uCur").textContent = "v" + u.current;
  $("#uLatest").textContent = u.latest ? "v" + u.latest : "?";
  $("#uLatest").style.color = u.update_available ? "var(--acc)" : "";
  $("#uMethod").textContent = u.install_method;
  $("#updPill").hidden = !u.update_available; $("#bUpd").hidden = !u.update_available;
  let st = "";
  if (u.state === "updating") st = `<div class="notice info">Updating. This usually takes under a minute.</div>`;
  else if (u.state === "restarting") st = `<div class="notice info">Update installed. Restarting, the page will reload by itself.</div>`;
  else if (u.state === "restart_required") st = `<div class="notice info">Update installed. Restart Plex Burner to load it.</div>`;
  else if (u.state === "error") st = `<div class="notice bad">${esc(u.error)}</div>`;
  else if (u.check_error) st = `<div class="notice bad">${esc(u.check_error)}</div>`;
  else if (u.update_available) st = `<div class="notice info">Version ${esc(u.latest)} is available.</div>`;
  else if (u.latest) st = `<div class="notice good">You're on the latest version, v${esc(u.current)}.</div>`;
  if (u.update_available && !u.can_update) st += `<div class="notice bad">${esc(u.reason)}</div>`;
  $("#uState").innerHTML = st;
  const busy = ["updating", "restarting"].includes(u.state);
  $("#uRun").hidden = !(u.update_available && u.can_update) && !busy;
  $("#uRun").disabled = busy; $("#uRun").textContent = busy ? "Updating" : `Update to v${u.latest}`;
  $("#uLog").hidden = !u.log.length; $("#uLog").textContent = u.log.join("\n"); $("#uLog").scrollTop = 1e9;
  $("#uMeta").innerHTML = `${esc(u.repo)}@${esc(u.branch)} · checked ${u.last_check ? ago(u.last_check) : "never"} · auto-update ${u.auto_update ? "on" : "off"}`;
}
async function startUpdate() {
  if (!await confirmDanger("Install the update now?", "Plex Burner will download the new version and restart. Copies in progress must finish first.", "Update")) return;
  const from = state.status?.version;
  try { renderUpdates(await api("api/update", { method: "POST" })); } catch (e) { toast(e.message); return; }
  clearInterval(updPoll);
  let down = false, restarting = false;
  updPoll = setInterval(async () => {
    try {
      if (down || restarting) {
        const h = await api("api/health");
        if (h.version !== from || down) { clearInterval(updPoll); toast(`Updated to v${h.version}`); setTimeout(() => location.reload(), 800); }
        return;
      }
      const u = await api("api/update?check=false"); renderUpdates(u);
      if (u.state === "restarting") restarting = true;
      if (["error", "idle", "restart_required"].includes(u.state)) clearInterval(updPoll);
    } catch { down = true; $("#uState").innerHTML = `<div class="notice info">Restarting Plex Burner. Waiting for it to come back.</div>`; }
  }, 1200);
}
$("#uCheck").onclick = () => loadUpdates(true);
$("#uRun").onclick = startUpdate;
Tabs.updates = { enter: () => loadUpdates(false) };
