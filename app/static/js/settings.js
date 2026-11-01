/* Settings tab: copy options, server details and the activity log. */
"use strict";
async function loadSettings() {
  try {
    const s = await api("api/settings");
    const auto = $("#setAuto");
    if (![...auto.options].some(o => +o.value === s.auto_start_seconds)) auto.insertAdjacentHTML("beforeend", `<option value="${s.auto_start_seconds}">After ${s.auto_start_seconds} seconds</option>`);
    auto.value = String(s.auto_start_seconds);
    $("#setEject").checked = s.eject_when_done;
    $("#setFormat").value = s.output_format;
    $("#setServer").innerHTML = `<dt>Disc drives</dt><dd>${s.drives.map(d => `${esc(d.name)} · ${esc(d.model)}`).join("<br>") || "none found"}</dd>
      <dt>Media folders</dt><dd>${s.media_paths.map(esc).join("<br>")}</dd>`;
  } catch (e) { toast(e.message); }
  if (state.status) $("#feedFull").innerHTML = feedHtml(state.status.log);
}
async function saveSetting(json) {
  try { await api("api/settings", { method: "POST", json }); toast("Saved"); } catch (e) { toast(e.message); }
}
$("#setAuto").onchange = e => saveSetting({ auto_start_seconds: +e.target.value });
$("#setEject").onchange = e => saveSetting({ eject_when_done: e.target.checked });
$("#setFormat").onchange = e => saveSetting({ output_format: e.target.value });
Tabs.settings = { enter: loadSettings };
