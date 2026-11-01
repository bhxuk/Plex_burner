/* Simulated API for the public demo (?demo, or the GitHub Pages build).
   No real servers, people or paths: two made-up drives, public-domain film titles,
   and generated artwork in place of video frames. */
"use strict";
(function () {
  const VERSION = "1.3.1";
  const T0 = Date.now() / 1000;
  const now = () => Date.now() / 1000;
  const GB = 1e9;

  /* ---------- generated "film frames" ---------- */
  function hash(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  function rng(seed) { return () => { seed = Math.imul(seed ^ (seed >>> 15), 2246822507) ^ Math.imul(seed ^ (seed >>> 13), 3266489909); return ((seed ^= seed >>> 16) >>> 0) / 4294967296; }; }
  const PALETTES = [
    ["#0b1d3a", "#f4a259", "#5b8e7d", "#1b263b"], ["#2b2d42", "#ef233c", "#8d99ae", "#14151f"], ["#1a1423", "#eacdc2", "#b75d69", "#372549"],
    ["#003049", "#fcbf49", "#f77f00", "#001d2e"], ["#264653", "#e9c46a", "#2a9d8f", "#132a33"], ["#10002b", "#c77dff", "#7b2cbf", "#05000f"],
    ["#1b4332", "#d8f3dc", "#52b788", "#081c15"], ["#3d0c11", "#f6aa1c", "#941b0c", "#220901"],
  ];
  const cache = {};
  function frame(key, mono) {
    if (cache[key]) return cache[key];
    const r = rng(hash(key)), p = PALETTES[Math.floor(r() * PALETTES.length)];
    const sunX = 120 + r() * 400, sunY = 70 + r() * 90, hills = [];
    for (let layer = 0; layer < 3; layer++) {
      let d = `M0 360 L0 ${210 + layer * 35 + r() * 30}`;
      for (let x = 0; x <= 640; x += 40) d += ` L${x} ${190 + layer * 40 + r() * 50}`;
      hills.push(`<path d="${d} L640 360 Z" fill="${layer === 2 ? p[3] : p[layer === 0 ? 2 : 0]}" opacity="${0.55 + layer * 0.2}"/>`);
    }
    const stars = Array.from({ length: 18 }, () => `<circle cx="${r() * 640}" cy="${r() * 150}" r="${r() * 1.4}" fill="#fff" opacity="${r() * .7}"/>`).join("");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 360"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[0]}"/><stop offset="1" stop-color="${p[1]}"/></linearGradient>
      <filter id="m"><feColorMatrix type="saturate" values="0"/></filter></defs>
      <g ${mono ? 'filter="url(#m)"' : ""}><rect width="640" height="360" fill="url(#g)"/>${stars}<circle cx="${sunX}" cy="${sunY}" r="${26 + r() * 30}" fill="${p[1]}" opacity=".9"/>${hills.join("")}</g>
      <rect width="640" height="40" fill="#000"/><rect y="320" width="640" height="40" fill="#000"/></svg>`;
    return (cache[key] = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg));
  }

  /* ---------- simulated state ---------- */
  const settings = { auto_start_seconds: 120, eject_when_done: true, output_format: "mkv" };
  let locations = [
    { path: "/srv/media/movies", name: "Movies", default: true, free: 1.42e12, total: 3.6e12 },
    { path: "/srv/media/kids", name: "Kids films", default: false, free: 1.42e12, total: 3.6e12 },
    { path: "/mnt/nas/archive", name: "NAS archive", default: false, free: 6.8e12, total: 12e12 },
  ];
  const FILMS = [
    ["Night of the Living Dead (1968)", 5.1], ["Charade (1963)", 6.2], ["His Girl Friday (1940)", 4.4], ["The General (1926)", 3.9],
    ["Nosferatu (1922)", 3.6], ["Metropolis (1927)", 6.8], ["Detour (1945)", 3.1], ["The Little Shop of Horrors (1960)", 3.4],
    ["Plan 9 from Outer Space (1957)", 3.8], ["The Last Man on Earth (1964)", 4.6], ["Carnival of Souls (1962)", 4.2], ["D.O.A. (1949)", 4.0],
  ];
  const library = FILMS.map(([name, gb], i) => ({
    id: "demo" + i, name, path: `${i % 4 === 3 ? "/srv/media/kids" : "/srv/media/movies"}/${name}`,
    location: i % 4 === 3 ? "Kids films" : "Movies", location_path: i % 4 === 3 ? "/srv/media/kids" : "/srv/media/movies",
    kind: i === 5 ? "dvd" : "movie", size: gb * GB, date: Math.floor(T0 - i * 86400 * 1.7 - 3600), frames: 4,
  }));
  const history = library.slice(0, 6).map((l, i) => ({ name: l.name, path: l.path, type: "dvd", format: i === 5 ? "folder" : "mkv", size: l.size, seconds: 780 + i * 61, date: l.date, drive: i % 2 ? "sr1" : "sr0" }));
  const log = [
    [-5400, "sr0", "Drive found: HL-DT-ST DVDRAM GP65NB60"], [-5390, "sr1", "Drive found: ASUS SDRW-08D2S-U (USB)"],
    [-4700, "sr0", "Detected DVD 'Detour'"], [-4650, "sr0", "Copying 'Detour (1945)' to /srv/media/movies as MKV"],
    [-3900, "sr0", "Saved /srv/media/movies/Detour (1945) (3.1 GB in 13 min)"], [-3896, "sr0", "Disc ejected"],
    [-1300, "sr0", "Detected DVD 'Night Of The Living Dead'"], [-1250, "sr0", "Copying 'Night of the Living Dead (1968)' to /srv/media/movies as MKV"],
    [-40, "sr1", "Detected DVD 'Charade'"],
  ].map(([dt, drive, text]) => ({ ts: T0 + dt, drive, text }));

  const drives = {
    sr0: { name: "Night of the Living Dead (1968)", suggested: "Night Of The Living Dead", started: T0 - 1250, total: 5.1 * GB, length: 1500, cancelled: false,
      info: { title: "NIGHT_OF_THE_LIVING_DEAD", titles: 3, main_title: 1, duration: 5760, chapters: 16, format: "NTSC", aspect: "4/3", resolution: "720x480", audio: ["English AC3 2ch"], subtitles: [], size: 6.9 * GB } },
    sr1: { name: "Charade (1963)", suggested: "Charade", pending: T0 - 40, total: 6.2 * GB,
      info: { title: "CHARADE", titles: 6, main_title: 1, duration: 6780, chapters: 28, format: "NTSC", aspect: "16/9", resolution: "720x480", audio: ["English AC3 2ch", "French AC3 2ch"], subtitles: ["English", "French", "Spanish"], size: 7.4 * GB } },
  };

  function driveSnap(id) {
    const d = drives[id], base = { device: "/dev/" + id, drive: id, connected: true, disc_id: id === "sr0" ? 7 : 3, disc_type: "dvd", disc_info: d.info,
      suggested: d.suggested, destination: locations.find(l => l.default).path, format: settings.output_format, previews: 4, pending_dest: null,
      model: id === "sr0" ? "HL-DT-ST DVDRAM GP65NB60" : "ASUS SDRW-08D2S-U" };
    if (d.started && !d.cancelled) {
      const elapsed = now() - d.started, frac = Math.min(elapsed / d.length, 1);
      if (frac >= 1) {
        return { ...base, status: "done", name: d.name, progress: 100, phase: "Finished", copied: d.total, total: d.total, speed: 0, eta: null,
          message: `Saved '${d.name}'. Disc ejected, insert the next one.`, live_preview: 0, auto_start_in: null };
      }
      return { ...base, status: "copying", name: d.name, progress: Math.floor(frac * 100), phase: "Reading the main film from the disc",
        copied: Math.floor(d.total * frac), total: d.total, speed: Math.floor(d.total / d.length * (0.92 + Math.sin(now()) * .06)),
        eta: Math.floor(d.length - elapsed), live_preview: Math.floor(now() / 15) * 15, message: `Copying '${d.name}'`, auto_start_in: null };
    }
    const wait = settings.auto_start_seconds ? Math.max(0, Math.floor(settings.auto_start_seconds - ((now() - d.pending) % settings.auto_start_seconds))) : null;
    return { ...base, status: "waiting", name: d.typed || d.name, progress: 0, phase: "", copied: 0, total: 0, speed: 0, eta: null, live_preview: 0,
      message: d.cancelled ? "Copy cancelled. Press Copy to try again, or eject the disc." : "Check the name and folder, then press Copy.", auto_start_in: wait };
  }

  function folders(path) {
    const tree = { "/srv/media": ["kids", "movies", "tv"], "/srv/media/movies": ["Classics", "Westerns"], "/srv/media/kids": [], "/srv/media/tv": [],
      "/mnt": ["nas"], "/mnt/nas": ["archive", "backups"], "/mnt/nas/archive": ["Films", "Home videos"] };
    const p = path || "/srv/media/movies", roots = ["/srv/media", "/mnt"];
    const parent = roots.includes(p) ? null : p.split("/").slice(0, -1).join("/") || null;
    return { path: p, dirs: tree[p] || [], roots, free: p.startsWith("/mnt") ? 6.8e12 : 1.42e12, total: p.startsWith("/mnt") ? 12e12 : 3.6e12, parent };
  }

  function body(opts) { try { return opts.json ?? JSON.parse(opts.body || "{}"); } catch { return {}; } }

  async function api(path, opts = {}) {
    await new Promise(r => setTimeout(r, 60));
    const method = (opts.method || "GET").toUpperCase(), url = new URL(path, "http://demo/"), p = url.pathname.replace(/^\//, ""), b = body(opts);
    let m;
    if (p === "api/status") return { version: VERSION, update_available: false, drives: ["sr0", "sr1"].map(driveSnap), log };
    if (p === "api/health") return { ok: true, version: VERSION, drives: 2 };
    if ((m = p.match(/^api\/drive\/(sr\d)\/(copy|cancel|eject|pending)$/))) {
      const d = drives[m[1]];
      if (m[2] === "copy") { d.name = b.name || d.name; d.started = now(); d.length = 900; d.cancelled = false; log.push({ ts: now(), drive: m[1], text: `Copying '${d.name}' as MKV` }); return { ok: true }; }
      if (m[2] === "cancel") { d.cancelled = true; d.started = null; d.pending = now(); log.push({ ts: now(), drive: m[1], text: `Copy of '${d.name}' cancelled` }); return { ok: true }; }
      if (m[2] === "pending") { if (b.name) d.typed = b.name; d.pending = now(); return { ok: true }; }
      throw new Error("Ejecting is switched off in the demo.");
    }
    if (p === "api/history") return history;
    if (p === "api/library") return library;
    if (p === "api/locations" && method === "GET") return { locations: locations.map(l => ({ ...l, available: true })), roots: ["/srv/media", "/mnt"] };
    if (p === "api/locations" && method === "POST") { locations.push({ path: b.path, name: b.name || b.path.split("/").pop(), default: false, free: 1.42e12, total: 3.6e12 }); if (b.default) locations.forEach(l => l.default = l.path === b.path); return { ok: true }; }
    if (p === "api/locations" && method === "PUT") { locations.forEach(l => { if (l.path === b.path && b.name) l.name = b.name; if (b.default) l.default = l.path === b.path; }); return { ok: true }; }
    if (p === "api/locations" && method === "DELETE") { locations = locations.filter(l => l.path !== b.path); return { ok: true }; }
    if (p === "api/folders" && method === "GET") return folders(url.searchParams.get("path"));
    if (p === "api/folders") return { ok: true, path: b.path + "/" + b.name };
    if (p === "api/settings" && method === "GET") return { ...settings, media_paths: ["/srv/media", "/mnt"], drives: [{ name: "sr0", model: "HL-DT-ST DVDRAM GP65NB60" }, { name: "sr1", model: "ASUS SDRW-08D2S-U" }] };
    if (p === "api/settings") { Object.assign(settings, b); return settings; }
    if (p === "api/update" && method === "GET") return { current: VERSION, latest: VERSION, update_available: false, check_error: null, last_check: now() - 1800, can_update: true, reason: null,
      install_method: "docker", auto_update: false, repo: "bhxuk/Plex_burner", branch: "main", state: "idle", log: [], error: null };
    if (p === "api/update") throw new Error("You're already on the latest version.");
    throw new Error("Not available in the demo");
  }

  function image(path) {
    const u = new URL(path, "http://demo/"), p = u.pathname;
    let m;
    if ((m = p.match(/^\/api\/drive\/(sr\d)\/preview\/(\d)\.jpg$/))) return frame(`${m[1]}-${drives[m[1]].info.title}-${m[2]}`, m[1] === "sr0");
    if ((m = p.match(/^\/api\/drive\/(sr\d)\/live\.jpg$/))) return frame(`${m[1]}-live-${u.searchParams.get("t")}`, m[1] === "sr0");
    if ((m = p.match(/^\/api\/frame\/(demo\d+)\/(\d)\.jpg$/))) { const item = library.find(i => i.id === m[1]); return frame(`${m[1]}-${m[2]}`, item && /19[2-4]\d|1957|1968/.test(item.name)); }
    return frame(path);
  }

  window.PBDemo = { api, image };
})();
