import { fetchJson, qs } from "./common.js";

const $ = (id) => document.getElementById(id);
const COLS = {
  "lineup-home": ["number", "name", "position", "starter"],
  "lineup-away": ["number", "name", "position", "starter"],
  goals: ["minute", "team", "scorer", "assist", "own_goal"],
  subs: ["minute", "team", "off", "on"],
  cards: ["minute", "team", "player", "colour"],
};
let facts = empty();
let match = null;

function empty() {
  return { home_team: "", away_team: "", lineups: { home: [], away: [] }, subs: [], goals: [], cards: [] };
}
const rowsFor = (key) => (key.startsWith("lineup-") ? facts.lineups[key.slice(7)] : facts[key]);
const api = (suffix = "") => `/api/autotag/matches/${encodeURIComponent(match)}/matchsheet${suffix}`;
const esc = (v) => String(v ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function cell(key, i, col, v) {
  if (col === "starter" || col === "own_goal")
    return `<input type="checkbox" data-k="${key}" data-i="${i}" data-c="${col}" ${v ? "checked" : ""}/>`;
  if (col === "team" || col === "colour") {
    const opts = col === "team" ? ["home", "away"] : ["yellow", "red"];
    return `<select data-k="${key}" data-i="${i}" data-c="${col}">${opts.map((o) => `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  }
  return `<input data-k="${key}" data-i="${i}" data-c="${col}" value="${esc(v)}" size="${col === "name" || col === "scorer" || col === "assist" || col === "player" ? 16 : 5}"/>`;
}

function render() {
  $("home_team").value = facts.home_team || "";
  $("away_team").value = facts.away_team || "";
  for (const key of Object.keys(COLS)) {
    const cols = COLS[key];
    const rows = rowsFor(key) || [];
    $(`t-${key}`).innerHTML = `<tr>${cols.map((c) => `<th>${c}</th>`).join("")}<th></th></tr>` +
      rows.map((r, i) => `<tr>${cols.map((c) => `<td>${cell(key, i, c, r[c])}</td>`).join("")}<td><button class="btn btn--ghost" data-del="${key}" data-i="${i}">×</button></td></tr>`).join("");
  }
  $("json").value = JSON.stringify(facts, null, 2);
  $("editor").hidden = false;
}

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.id === "home_team" || t.id === "away_team") facts[t.id] = t.value;
  if (!t.dataset || !t.dataset.k) return;
  const row = rowsFor(t.dataset.k)[Number(t.dataset.i)];
  const col = t.dataset.c;
  if (t.type === "checkbox") row[col] = t.checked;
  else if (["number", "off", "on"].includes(col) && /^\d+$/.test(t.value)) row[col] = Number(t.value);
  else row[col] = t.value === "" ? null : t.value;
  $("json").value = JSON.stringify(facts, null, 2);
});
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.dataset.add) {
    e.preventDefault();
    const blank = Object.fromEntries(COLS[t.dataset.add].map((c) => [c, c === "team" ? "home" : c === "colour" ? "yellow" : c === "starter" ? true : c === "own_goal" ? false : null]));
    rowsFor(t.dataset.add).push(blank);
    render();
  } else if (t.dataset.del) {
    e.preventDefault();
    rowsFor(t.dataset.del).splice(Number(t.dataset.i), 1);
    render();
  }
});

function show(doc) {
  $("sheet-status").textContent = doc.status ? `(${doc.status}${doc.source ? ", " + doc.source : ""})` : "";
  $("issues").innerHTML = (doc.issues || []).map((i) => `<li>${esc(i)}</li>`).join("");
  $("pages").innerHTML = Array.from({ length: doc.pages || 0 }, (_, i) =>
    `<a href="${api(`/pages/${i + 1}.png`)}" target="_blank"><img src="${api(`/pages/${i + 1}.png`)}" alt="page ${i + 1}" style="max-width:220px;margin:4px;border:1px solid #ccc"/></a>`).join("");
  if (doc.facts) facts = doc.facts;
  if (doc.last_apply) $("report").textContent = "Last apply: " + JSON.stringify(doc.last_apply.score || {}) + " goals";
  render();
}

async function load() {
  match = $("match-id").value.trim();
  if (!match) return;
  history.replaceState(null, "", `?match=${encodeURIComponent(match)}`);
  $("to-review").href = `/review?match=${encodeURIComponent(match)}`;
  const doc = await fetchJson(api());
  if (doc.status === "none") { $("status").textContent = "No match sheet yet."; facts = empty(); $("editor").hidden = true; }
  else show(doc);
}

$("match-form").addEventListener("submit", (e) => { e.preventDefault(); load().catch((err) => ($("status").textContent = err.message)); });
$("blank").addEventListener("click", () => { if (!$("match-id").value.trim()) return; match = $("match-id").value.trim(); facts = empty(); render(); });
$("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  match = $("match-id").value.trim();
  if (!match) { $("status").textContent = "Enter a match id first."; return; }
  const fd = new FormData();
  fd.append("file", $("sheet-file").files[0]);
  $("status").textContent = "Reading the sheet…";
  try {
    const res = await fetch(api("/upload"), { method: "POST", body: fd });
    const doc = await res.json();
    if (!res.ok) throw new Error(doc.detail || res.statusText);
    $("status").textContent = "Read. Check every row, then confirm.";
    show(doc);
  } catch (err) { $("status").textContent = "Error: " + err.message; }
});
$("from-json").addEventListener("click", () => {
  try { facts = { ...empty(), ...JSON.parse($("json").value) }; render(); } catch (err) { $("status").textContent = "Bad JSON: " + err.message; }
});
$("save-draft").addEventListener("click", async () => {
  const doc = await fetchJson(api(), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ facts }) });
  show(doc);
  $("status").textContent = "Draft saved (not applied).";
});
$("confirm").addEventListener("click", async () => {
  if (!confirm("Apply these facts? Goals, cards and subs will override the auto-tags.")) return;
  try {
    const out = await fetchJson(api("/confirm"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ facts }) });
    const r = out.report;
    $("report").textContent =
      `Applied. Score ${r.score.home}-${r.score.away}. Goals: ${r.goals.corrected.length} corrected, ${r.goals.added.length} added, ${r.goals.rejected.length} phantom removed. ` +
      `Cards: ${r.cards.corrected.length} corrected, ${r.cards.added.length} added, ${r.cards.rejected.length} removed. ` +
      `Clock offsets ${JSON.stringify(r.clock.offsets)} (${r.shifted} events shifted). ${r.attribution_cleared.length} off-pitch shirt attributions cleared.`;
    $("sheet-status").textContent = "(confirmed)";
  } catch (err) { $("report").textContent = "Error: " + err.message; }
});

const initial = qs("match");
if (initial) { $("match-id").value = initial; load().catch(() => {}); }
