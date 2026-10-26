// Semi-automatic tagging page. Server: /api/semi/{match}. Pure logic is exported for tests (tag.test via node).
const $ = (id) => document.getElementById(id);

export const EVENT_KEYS = {
  p: "PASS", x: "CROSS", s: "SHOT", t: "TACKLE", i: "INTERCEPT", c: "CLEAR", f: "FOUL", w: "THROW", k: "CORNER",
  e: "FK", g: "GOALKICK", v: "SAVE", o: "RECOVERY", d: "DUEL", u: "AERIAL", b: "LOST",
};
export const LINE_CODES = new Set(["PASS", "CROSS", "FK", "GOALKICK", "THROW", "CORNER", "GK_PASS"]);
const LABEL = { PASS: "pass", CROSS: "cross", SHOT: "shot", TACKLE: "tackle", INTERCEPT: "interception",
  CLEAR: "clearance", FOUL: "foul", THROW: "throw-in", CORNER: "corner", FK: "free kick", GOALKICK: "goal kick",
  SAVE: "save", RECOVERY: "recovery", DUEL: "duel", AERIAL: "aerial", LOST: "ball lost", GK_PASS: "GK pass", CARD: "card" };
const KEY_HELP = [
  ["Space", "play / pause"], ["← →", "−/+ 1 s (Shift 5 s)"], [", .", "−/+ 1 frame"], ["R", "replay moment"],
  ["] or ↓", "next item"], ["[ or ↑", "previous item"], ["Enter", "confirm + next to-do"], ["M", "add moment at current time"],
  ["Delete / Shift+D", "delete (false moment)"], ["Z / Ctrl+Z", "undo"], ["H / A", "team home / away"],
  ["0-9", "shirt (two digits quickly)"], ["Backspace", "clear shirt"], ["Y / N", "success / fail · shot: on / off target"],
  ["L", "shot blocked"], ["Shift+G", "shot = goal"], ["Esc", "clear pitch points"],
  ...Object.entries(EVENT_KEYS).map(([k, c]) => [k.toUpperCase(), LABEL[c]]),
];

// --- coordinates: screen pitch (0..100, x→ right, y↓ far touchline = 0) <-> acting team's view ---
export function attacksRight(team, tMatch, homeRightFirstHalf) {
  const second = tMatch >= 45 * 60;
  const homeRight = homeRightFirstHalf !== second;
  return team === "home" ? homeRight : !homeRight;
}
export function screenToTeam(sx, sy, right) {
  return right ? [round1(sx), round1(sy)] : [round1(100 - sx), round1(100 - sy)];
}
export const teamToScreen = (x, y, right) => (right ? [x, y] : [100 - x, 100 - y]);
const round1 = (v) => Math.round(Math.max(0, Math.min(100, v)) * 10) / 10;

export function videoToMatch(t, segments) {
  const segs = [...(segments || [{ video_start: 0, match_start: 0 }])].sort((a, b) => a.video_start - b.video_start);
  let seg = segs[0];
  for (const s of segs) if (s.video_start <= t) seg = s;
  return seg.match_start + (t - seg.video_start);
}
export function parseSegments(text) {
  const out = String(text || "").split(",").map((p) => p.trim()).filter(Boolean).map((p) => {
    const [v, m] = p.split(":").map(Number);
    if (!Number.isFinite(v) || !Number.isFinite(m)) throw new Error(`bad segment "${p}"`);
    return { video_start: v, match_start: m };
  });
  return out.length ? out : [{ video_start: 0, match_start: 0 }];
}
export const clock = (s) => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };

// --- state ---
const S = { match: null, settings: null, items: [], cur: 0, undo: [], pts: [], shirtBuf: "", shirtAt: 0,
  saveTimer: null, loopEnd: null, loopStart: null };

function snapshot() { S.undo.push(JSON.stringify({ items: S.items, cur: S.cur })); if (S.undo.length > 200) S.undo.shift(); }
function undo() {
  const prev = S.undo.pop(); if (!prev) return;
  const d = JSON.parse(prev); S.items = d.items; S.cur = d.cur; changed(false);
}
const item = () => S.items[S.cur];
const tMatch = (it) => videoToMatch(it.t_video, S.settings.segments);

function mutate(fn) {
  const it = item(); if (!it) return;
  snapshot(); fn(it);
  if (it.status === "deleted") return changed();
  changed();
}
function changed(save = true) { render(); if (save) scheduleSave(); }

function scheduleSave() {
  clearTimeout(S.saveTimer); setSave("unsaved…");
  S.saveTimer = setTimeout(save, 700);
}
async function save() {
  const body = { settings: S.settings, items: S.items.map(({ _err, ...r }) => r) };
  try {
    const r = await fetch(`/api/semi/${encodeURIComponent(S.match)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    setSave(`saved ${new Date().toLocaleTimeString()} · ${j.confirmed} confirmed events`);
  } catch (e) { setSave(`NOT saved: ${e.message}`, true); }
}
function setSave(t, err) { const el = $("save-state"); el.textContent = t; el.className = err ? "err" : ""; }
function status(t) { $("status").textContent = t; }

// --- navigation ---
function go(i, play = true) {
  if (!S.items.length) return;
  S.cur = Math.max(0, Math.min(S.items.length - 1, i)); S.pts = [];
  const it = item(); render();
  if (play) seekMoment(it.t_video);
}
function seekMoment(t) {
  const v = $("video"); const lead = Number($("s-lead").value) || 2;
  S.loopStart = Math.max(0, t - lead); S.loopEnd = t + 1;
  if (v.src) { v.currentTime = S.loopStart; v.play().catch(() => {}); }
}
function step(dir) {
  const order = S.items.map((x, i) => i).filter((i) => S.items[i].status !== "deleted");
  const pos = order.findIndex((i) => i >= S.cur + (dir > 0 ? 1 : 0));
  const idx = dir > 0 ? order.find((i) => i > S.cur) : [...order].reverse().find((i) => i < S.cur);
  if (idx !== undefined) go(idx); void pos;
}
function nextTodo() {
  const idx = S.items.findIndex((x, i) => i > S.cur && x.status === "todo");
  go(idx >= 0 ? idx : Math.min(S.cur + 1, S.items.length - 1));
}
function addAtCurrent() {
  const t = Math.round($("video").currentTime * 100) / 100;
  snapshot();
  const it = { id: `u${Date.now()}`, t_video: t, status: "todo", from_moment: false, team_suggestion: null };
  S.items.push(it); S.items.sort((a, b) => a.t_video - b.t_video);
  S.cur = S.items.indexOf(it); S.pts = []; $("video").pause(); changed();
}
function confirm() {
  const it = item(); if (!it) return;
  if (!it.code || !it.team) return status("Set a type and a team first (suggestions are not confirmed automatically).");
  if (LINE_CODES.has(it.code) && it.x2 == null) status("Note: no end point — this pass will not count for progressive passes.");
  else status("");
  snapshot(); it.status = "done"; changed(); nextTodo();
}

// --- keyboard ---
function onKey(ev) {
  if (!S.match || ["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName)) return;
  const v = $("video"); const k = ev.key; const low = k.toLowerCase();
  const handled = () => ev.preventDefault();
  if ((ev.ctrlKey || ev.metaKey) && low === "z") { handled(); return undo(); }
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (k === " ") { handled(); S.loopEnd = null; return v.paused ? v.play() : v.pause(); }
  if (k === "ArrowLeft" || k === "ArrowRight") { handled(); S.loopEnd = null; v.currentTime += (k === "ArrowLeft" ? -1 : 1) * (ev.shiftKey ? 5 : 1); return; }
  if (k === "," || k === ".") { handled(); v.pause(); S.loopEnd = null; v.currentTime += (k === "," ? -1 : 1) / 25; return; }
  if (k === "]" || k === "ArrowDown") { handled(); return step(1); }
  if (k === "[" || k === "ArrowUp") { handled(); return step(-1); }
  if (k === "Enter") { handled(); return confirm(); }
  if (low === "r") { handled(); return item() && seekMoment(item().t_video); }
  if (low === "m") { handled(); return addAtCurrent(); }
  if (k === "Delete" || (ev.shiftKey && low === "d")) { handled(); mutate((it) => { it.status = "deleted"; }); return step(1); }
  if (low === "z") { handled(); return undo(); }
  if (k === "Escape") { handled(); S.pts = []; return mutate((it) => { it.x1 = it.y1 = it.x2 = it.y2 = null; }); }
  if (!item()) return;
  if (low === "h" || low === "a") { handled(); return mutate((it) => { it.team = low === "h" ? "home" : "away"; reopen(it); }); }
  if (/^[0-9]$/.test(k)) {
    handled(); const now = Date.now();
    S.shirtBuf = now - S.shirtAt < 1000 && S.shirtBuf.length < 2 ? S.shirtBuf + k : k; S.shirtAt = now;
    return mutate((it) => { it.shirt = Number(S.shirtBuf) || null; reopen(it); });
  }
  if (k === "Backspace") { handled(); return mutate((it) => { it.shirt = null; reopen(it); }); }
  if (ev.shiftKey && low === "g") { handled(); return mutate((it) => { it.code = "SHOT"; it.outcome = "goal"; reopen(it); }); }
  if (low === "y" || low === "n") {
    handled(); return mutate((it) => { it.outcome = it.code === "SHOT" ? (low === "y" ? "on" : "off") : (low === "y" ? "success" : "fail"); reopen(it); });
  }
  if (low === "l") { handled(); return mutate((it) => { it.code = "SHOT"; it.outcome = "blocked"; reopen(it); }); }
  if (EVENT_KEYS[low] && !ev.shiftKey) {
    handled(); return mutate((it) => {
      const was = it.code; it.code = EVENT_KEYS[low];
      if ((was === "SHOT") !== (it.code === "SHOT")) it.outcome = null;
      if (it.code === "THROW" || it.code === "CORNER" || it.code === "FK" || it.code === "GOALKICK") it.outcome = it.outcome || null;
      reopen(it);
    });
  }
}
// editing a confirmed item keeps it confirmed only while complete
function reopen(it) { if (it.status === "done" && (!it.code || !it.team)) it.status = "todo"; }

// --- pitch ---
function onPitch(ev) {
  const it = item(); if (!it) return;
  const svg = $("pitch"); const r = svg.getBoundingClientRect();
  const sx = ((ev.clientX - r.left) / r.width) * 100; const sy = ((ev.clientY - r.top) / r.height) * 100;
  const team = it.team || it.team_suggestion;
  if (!team) return status("Pick the team first (H/A): coordinates are stored from the acting team's view.");
  const right = attacksRight(team, tMatch(it), S.settings.home_attacks_right_first_half);
  const [x, y] = screenToTeam(sx, sy, right);
  mutate((it2) => {
    if (it2.x1 == null || it2.x2 != null) { it2.x1 = x; it2.y1 = y; it2.x2 = it2.y2 = null; }
    else { it2.x2 = x; it2.y2 = y; }
    if (!it2.team) it2.team = team;
  });
}
function drawPitch() {
  const it = item(); const svg = $("pitch");
  const line = 'stroke="#fff" stroke-width=".4" fill="none"';
  let h = `<rect x=".5" y=".5" width="104" height="67" ${line}/><line x1="52.5" y1=".5" x2="52.5" y2="67.5" ${line}/>
    <circle cx="52.5" cy="34" r="9.15" ${line}/><rect x=".5" y="13.85" width="16.5" height="40.3" ${line}/>
    <rect x="88" y="13.85" width="16.5" height="40.3" ${line}/>`;
  if (it) {
    const team = it.team || it.team_suggestion;
    if (team) {
      const right = attacksRight(team, tMatch(it), S.settings.home_attacks_right_first_half);
      h += `<text x="52.5" y="66" font-size="3" fill="#fff" text-anchor="middle">${team} attacks ${right ? "→" : "←"}</text>`;
      const P = (x, y) => { const [a, b] = teamToScreen(x, y, right); return [a * 1.05, b * 0.68]; };
      if (it.x1 != null) {
        const [a, b] = P(it.x1, it.y1); h += `<circle cx="${a}" cy="${b}" r="1.3" fill="#ff0"/>`;
        if (it.x2 != null) { const [c, d] = P(it.x2, it.y2); h += `<line x1="${a}" y1="${b}" x2="${c}" y2="${d}" stroke="#ff0" stroke-width=".6"/><circle cx="${c}" cy="${d}" r="1" fill="#f80"/>`; }
      }
    }
  }
  svg.innerHTML = h;
}

// --- render ---
function render() {
  const it = item();
  const names = { home: S.settings.home_name, away: S.settings.away_name };
  const card = $("card");
  if (!it) {
    card.innerHTML = "<p>No items. Play the video and press <kbd>M</kbd> to add an event at the current time, or import detector moments.</p>";
  } else {
    const chip = (on, txt, cls = "") => `<span class="chip ${cls} ${on ? "on" : ""}">${txt}</span>`;
    const sugg = !it.team && it.team_suggestion ? `<span class="sugg">detector suggests ${names[it.team_suggestion]} (not confirmed)</span>` : "";
    const outs = it.code === "SHOT" ? [["on", "Y on"], ["off", "N off"], ["blocked", "L blocked"], ["goal", "⇧G goal"]] : [["success", "Y success"], ["fail", "N fail"]];
    card.innerHTML = `
      <div class="row"><b>#${S.cur + 1}/${S.items.length}</b> video ${it.t_video.toFixed(2)} s · match ${clock(tMatch(it))}
        · <b>${it.status}</b>${it.from_moment ? " · detector" : " · manual"}</div>
      <div class="row">${chip(it.team === "home", `H ${names.home}`, "home")}${chip(it.team === "away", `A ${names.away}`, "away")} ${sugg}</div>
      <div class="row">${Object.entries(EVENT_KEYS).map(([k, c]) => chip(it.code === c, `${k.toUpperCase()} ${LABEL[c]}`)).join("")}</div>
      <div class="row">${outs.map(([o, t]) => chip(it.outcome === o, t)).join("")}
        &nbsp; shirt <b>${it.shirt ?? "—"}</b></div>
      <div class="row">start ${it.x1 != null ? `${it.x1},${it.y1}` : "—"} → end ${it.x2 != null ? `${it.x2},${it.y2}` : "—"}
        ${LINE_CODES.has(it.code) && it.x2 == null ? '<span class="sugg">click start + end on the pitch</span>' : ""}</div>
      <div class="row"><input id="detail" placeholder="detail (optional, e.g. header, tackle)" value="${(it.detail || "").replace(/"/g, "&quot;")}" style="flex:1"/></div>`;
    $("detail").addEventListener("change", (e) => mutate((x) => { x.detail = e.target.value; }));
  }
  const dur = $("video").duration || Math.max(60, ...S.items.map((x) => x.t_video + 10));
  $("track").innerHTML = S.items.map((x, i) => `<i class="${x.status} ${i === S.cur ? "cur" : ""}" style="left:${(100 * x.t_video) / dur}%"></i>`).join("")
    + `<b id="playhead" style="left:${(100 * ($("video").currentTime || 0)) / dur}%"></b>`;
  $("list").innerHTML = S.items.map((x, i) => `<li data-i="${i}" class="${x.status} ${i === S.cur ? "cur" : ""}">${clock(tMatch(x))}
    ${x.team ? names[x.team] : x.team_suggestion ? `<span class="sugg">${names[x.team_suggestion]}?</span>` : "?"}
    ${x.code ? LABEL[x.code] : "…"} ${x.outcome || ""} ${x.shirt ? `#${x.shirt}` : ""}</li>`).join("");
  const c = { todo: 0, done: 0, deleted: 0 }; S.items.forEach((x) => { c[x.status] += 1; });
  $("counts").textContent = `${c.done} confirmed · ${c.todo} to do · ${c.deleted} deleted`;
  drawPitch();
  const cur = $("list").querySelector("li.cur"); if (cur) cur.scrollIntoView({ block: "nearest" });
}

// --- load / settings ---
async function load(match) {
  const r = await fetch(`/api/semi/${encodeURIComponent(match)}`);
  const j = await r.json();
  if (!r.ok) return status(j.detail || "load failed");
  S.match = match; S.settings = j.settings; S.items = j.items; S.cur = Math.max(0, S.items.findIndex((x) => x.status === "todo"));
  S.undo = [];
  $("s-home").value = S.settings.home_name; $("s-away").value = S.settings.away_name;
  $("s-seg").value = S.settings.segments.map((s) => `${s.video_start}:${s.match_start}`).join(", ");
  $("s-dir").checked = !!S.settings.home_attacks_right_first_half;
  const base = `/api/autotag/matches/${encodeURIComponent(match)}`;
  $("csv-events").href = `/api/semi/${encodeURIComponent(match)}/events.csv`;
  $("csv-team").href = `${base}/stats/team.csv?confirmed_only=true`;
  $("csv-players").href = `${base}/stats/players.csv?confirmed_only=true`;
  $("stats-link").href = `${base}/stats?confirmed_only=true`;
  $("settings").hidden = false; $("work").hidden = false;
  history.replaceState(null, "", `?match=${encodeURIComponent(match)}`);
  status(`Loaded ${match}: ${S.items.length} items. Open the video file to start.`);
  render();
}
function readSettings() {
  try {
    S.settings = { ...S.settings, home_name: $("s-home").value || "Home", away_name: $("s-away").value || "Away",
      segments: parseSegments($("s-seg").value), home_attacks_right_first_half: $("s-dir").checked };
    changed();
  } catch (e) { status(e.message); }
}

function init() {
  $("keys").innerHTML = KEY_HELP.map(([k, d]) => `<div><kbd>${k}</kbd> ${d}</div>`).join("");
  $("match-form").addEventListener("submit", (e) => { e.preventDefault(); load($("match-id").value.trim()); });
  $("settings-form").addEventListener("change", readSettings);
  $("video-file").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    $("video").src = URL.createObjectURL(f); status(`Video: ${f.name} (local, not uploaded)`);
    $("video").addEventListener("loadedmetadata", () => { render(); if (item()) go(S.cur); }, { once: true });
  });
  $("server-video").addEventListener("click", () => {
    if (!S.match) return status("Load a match first");
    $("video").src = `/api/autotag/matches/${encodeURIComponent(S.match)}/video`;
  });
  $("moments-file").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f || !S.match) return status("Load a match first, then pick the moments file");
    try {
      const body = JSON.parse(await f.text());
      const r = await fetch(`/api/semi/${encodeURIComponent(S.match)}/moments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json(); if (!r.ok) throw new Error(j.detail);
      status(`Imported ${j.moments} moments`); await load(S.match);
    } catch (err) { status(`Import failed: ${err.message}`); }
  });
  $("pitch").addEventListener("click", onPitch);
  $("list").addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) go(Number(li.dataset.i)); });
  $("track").addEventListener("click", (e) => {
    const r = e.currentTarget.getBoundingClientRect(); const v = $("video");
    if (v.duration) { S.loopEnd = null; v.currentTime = ((e.clientX - r.left) / r.width) * v.duration; }
  });
  const v = $("video");
  v.addEventListener("timeupdate", () => {
    $("clock").textContent = S.settings ? `video ${v.currentTime.toFixed(1)} s · match ${clock(videoToMatch(v.currentTime, S.settings.segments))}` : "";
    const ph = $("playhead"); if (ph && v.duration) ph.style.left = `${(100 * v.currentTime) / v.duration}%`;
    if (S.loopEnd != null && v.currentTime >= S.loopEnd) {
      const mode = $("s-mode").value;
      if (mode === "loop") v.currentTime = S.loopStart; else if (mode === "pause") { v.pause(); S.loopEnd = null; } else S.loopEnd = null;
    }
  });
  document.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", () => { if (S.saveTimer) save(); });
  const m = new URLSearchParams(location.search).get("match");
  if (m) { $("match-id").value = m; load(m); }
}
if (typeof document !== "undefined") init();
