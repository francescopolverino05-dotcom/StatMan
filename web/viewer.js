import { fetchJson } from "./common.js";
import { mountAppNav } from "./app-shell.js";

mountAppNav({ active: "home" });

const $ = (id) => document.getElementById(id);
const form = $("load-form");
const filesInput = $("files-input");
const filesLabel = $("files-label");
const drop = $("drop");
const statusEl = $("status");

let current = null; // package payload
let playerSort = { col: null, dir: 1 };

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function toNum(value) {
  if (value === null || value === undefined) return null;
  const v = String(value).trim().replace("%", "").replace(",", ".");
  if (v === "" || !/^-?\d+(\.\d+)?$/.test(v)) return null;
  return Number(v);
}

/* ---------------- CSV (client side, for "export this view") --------------- */

function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsv(header, rows) {
  return [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

function download(name, text, type = "text/csv;charset=utf-8") {
  const blob = new Blob(["\ufeff", text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------------- key stats ---------------------------------------------- */

const HIGHLIGHTS = [
  { group: "Possession", items: [["Possession %", /possession/i]] },
  {
    group: "Passes",
    items: [
      ["Attempted", /^passes( attempted| total)?$/i],
      ["Completed", /^passes completed/i],
      ["Accuracy %", /^pass(es)? accuracy/i],
    ],
  },
  {
    group: "Progressive passes",
    items: [
      ["Attempted", /progressive.*attempt/i],
      ["Completed", /progressive.*complet/i],
      ["Success %", /progressive.*(%|pct|percent)/i],
    ],
  },
  {
    group: "Shots",
    items: [
      ["Shots", /^shots( total)?$/i],
      ["On target", /on target/i],
      ["Accuracy %", /^shot accuracy/i],
    ],
  },
  { group: "Expected goals", items: [["xG", /\bxg\b|expected goals/i]] },
  {
    group: "Set pieces & discipline",
    items: [
      ["Corners", /^corners/i],
      ["Fouls", /^fouls/i],
      ["Yellow cards", /yellow/i],
      ["Red cards", /^red/i],
      ["Offsides", /^offsides/i],
    ],
  },
  {
    group: "PPDA",
    items: [
      ["Full match", /ppda.*(full|match|total)|^ppda$/i],
      ["1st half", /ppda.*(1st|1h|first)/i],
      ["2nd half", /ppda.*(2nd|2h|second)/i],
    ],
  },
];

function findRow(rows, re) {
  return rows.find((r) => re.test(r.metric));
}

function renderHighlights(team) {
  const [a, b] = team.teams;
  const out = [];
  for (const g of HIGHLIGHTS) {
    const lines = [];
    for (const [label, re] of g.items) {
      const row = findRow(team.rows, re);
      if (!row) continue;
      const x = toNum(row.home);
      const y = toNum(row.away);
      let bar = "";
      if (x !== null && y !== null && x + y > 0 && x >= 0 && y >= 0) {
        const pct = (x / (x + y)) * 100;
        bar = `<span class="vbar" aria-hidden="true"><i style="width:${pct.toFixed(1)}%"></i></span>`;
      }
      lines.push(`<li><span class="v v--home">${esc(row.home)}</span>${bar}<span class="l" title="${esc(row.metric)}">${esc(label)}</span><span class="v v--away">${esc(row.away)}</span></li>`);
    }
    if (lines.length) {
      out.push(`<div class="viewer-card"><h4>${esc(g.group)}</h4><div class="viewer-card__teams"><span>${esc(a)}</span><span>${esc(b)}</span></div><ul>${lines.join("")}</ul></div>`);
    }
  }
  $("highlights").innerHTML = out.join("") || `<p class="hint">No standard stats recognised — see the full table below.</p>`;
}

function renderTeamTable(pkg) {
  const team = pkg.team;
  const extras = team.extra_columns || [];
  const [a, b] = team.teams;
  const bySection = new Map();
  for (const r of team.rows) {
    if (!bySection.has(r.section)) bySection.set(r.section, []);
    bySection.get(r.section).push(r);
  }
  let html = `<thead><tr><th>Metric</th><th>${esc(a)}</th><th>${esc(b)}</th>${extras.map((e) => `<th>${esc(e)}</th>`).join("")}</tr></thead><tbody>`;
  for (const key of pkg.section_order) {
    const rows = bySection.get(key);
    if (!rows) continue;
    html += `<tr class="viewer-section"><th colspan="${3 + extras.length}">${esc(pkg.section_titles[key] || key)}</th></tr>`;
    for (const r of rows) {
      html += `<tr><td>${esc(r.metric)}</td><td>${esc(r.home)}</td><td>${esc(r.away)}</td>${extras.map((e) => `<td class="viewer-note">${esc(r[e] || "")}</td>`).join("")}</tr>`;
    }
  }
  $("team-table").innerHTML = html + "</tbody>";
}

/* ---------------- players ------------------------------------------------- */

const ACTIVITY_COLS = /^(events|passes|shots|interceptions|recoveries|duels_won|aerials_won|clearances|blocks|saves|fouls|corners|offsides|yellow|red|tackles|goals|xg)$/i;

function playerView() {
  const pl = current.players;
  const cols = pl.columns;
  const teamIdx = cols.findIndex((c) => /^team$/i.test(c));
  const team = $("player-team").value;
  const q = $("player-search").value.trim().toLowerCase();
  const hideZero = $("player-hide-zero").checked;
  const activity = cols.map((c, i) => (ACTIVITY_COLS.test(c) ? i : -1)).filter((i) => i >= 0);
  let rows = pl.rows.filter((r) => {
    if (team && teamIdx >= 0 && r[teamIdx] !== team) return false;
    if (q && !r.some((c, i) => !toNum(c) && String(c).toLowerCase().includes(q))) return false;
    if (hideZero && activity.length && activity.every((i) => !toNum(r[i]))) return false;
    return true;
  });
  if (playerSort.col !== null) {
    const i = playerSort.col;
    const d = playerSort.dir;
    rows = [...rows].sort((x, y) => {
      const nx = toNum(x[i]);
      const ny = toNum(y[i]);
      if (nx !== null && ny !== null) return (nx - ny) * d;
      return String(x[i]).localeCompare(String(y[i]), undefined, { numeric: true }) * d;
    });
  }
  return { cols, rows };
}

function renderPlayers() {
  const { cols, rows } = playerView();
  const head = cols
    .map((c, i) => {
      const arrow = playerSort.col === i ? (playerSort.dir > 0 ? " ▲" : " ▼") : "";
      return `<th data-col="${i}" class="is-sortable">${esc(c)}${arrow}</th>`;
    })
    .join("");
  const body = rows
    .map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`)
    .join("");
  $("player-table").innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  $("player-table").querySelectorAll("th[data-col]").forEach((th) =>
    th.addEventListener("click", () => {
      const i = Number(th.dataset.col);
      playerSort = { col: i, dir: playerSort.col === i ? -playerSort.dir : -1 };
      renderPlayers();
    })
  );
}

function setupPlayers() {
  const pl = current.players;
  const teamIdx = pl.columns.findIndex((c) => /^team$/i.test(c));
  const teams = teamIdx >= 0 ? [...new Set(pl.rows.map((r) => r[teamIdx]))] : [];
  $("player-team").innerHTML = `<option value="">All teams</option>` + teams.map((t) => `<option>${esc(t)}</option>`).join("");
  $("player-team").parentElement.hidden = !teams.length;
  $("player-search").value = "";
  $("player-hide-zero").checked = false;
  playerSort = { col: null, dir: 1 };
  renderPlayers();
}

/* ---------------- shots / export bar / package ---------------------------- */

function renderShots(shots) {
  $("shots-table").innerHTML =
    `<thead><tr>${shots.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
    shots.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("") +
    "</tbody>";
}

function renderExportBar(pkg) {
  const base = `/api/packages/${encodeURIComponent(pkg.package_id)}`;
  const links = [];
  if (pkg.team) links.push([`${base}/team.csv`, "Team stats CSV"]);
  if (pkg.players) links.push([`${base}/players.csv`, "Players CSV"]);
  if (pkg.shots) links.push([`${base}/shots.csv`, "Shots CSV"]);
  if (pkg.has_report) links.push([`${base}/report.html?download=1`, "HTML report"]);
  links.push([`${base}/package.json`, "Everything (JSON)"]);
  $("export-bar").innerHTML =
    `<span class="viewer-export__label">Export</span>` +
    links.map(([href, label]) => `<a class="btn btn--ghost" href="${href}" download>${esc(label)}</a>`).join("") +
    `<button class="btn btn--ghost" type="button" id="print-btn">Print / save as PDF</button>`;
  $("print-btn").addEventListener("click", () => window.print());
}

function showPackage(pkg) {
  current = pkg;
  $("result").hidden = false;
  $("result-title").textContent = pkg.title;
  $("result-summary").textContent = pkg.summary || "";
  renderExportBar(pkg);

  const notes = pkg.notes || [];
  $("notes-wrap").hidden = !notes.length;
  $("notes").innerHTML = notes.map((n) => `<li>${esc(n)}</li>`).join("");

  $("team-block").hidden = !pkg.team;
  if (pkg.team) {
    renderHighlights(pkg.team);
    renderTeamTable(pkg);
  }
  $("players-block").hidden = !pkg.players;
  if (pkg.players) setupPlayers();
  $("shots-block").hidden = !pkg.shots;
  if (pkg.shots) renderShots(pkg.shots);

  $("report-block").hidden = !pkg.has_report;
  $("report-frame").removeAttribute("src");
  if (pkg.has_report) {
    $("report-block").open = false;
    $("report-frame").dataset.src = `/api/packages/${encodeURIComponent(pkg.package_id)}/report.html`;
  }
  history.replaceState(null, "", `/?package=${encodeURIComponent(pkg.package_id)}`);
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("report-block").addEventListener("toggle", () => {
  const f = $("report-frame");
  if ($("report-block").open && !f.getAttribute("src") && f.dataset.src) f.setAttribute("src", f.dataset.src);
});

$("player-team").addEventListener("change", renderPlayers);
$("player-search").addEventListener("input", renderPlayers);
$("player-hide-zero").addEventListener("change", renderPlayers);
$("player-export").addEventListener("click", () => {
  const { cols, rows } = playerView();
  download(`${current.slug}_players_view.csv`, toCsv(cols, rows));
});

/* ---------------- loading ------------------------------------------------- */

let picked = [];

function setPicked(files) {
  picked = [...files];
  filesLabel.textContent = picked.length
    ? `${picked.length} file${picked.length > 1 ? "s" : ""}: ${picked.map((f) => f.name).join(", ")}`
    : "Choose files or drop them here… (e.g. Monopoli-Napoli_team.csv, _players.csv, _stats.html)";
}

filesInput.addEventListener("change", () => setPicked(filesInput.files));
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("is-over"); }));
drop.addEventListener("drop", (e) => setPicked(e.dataTransfer.files));

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!picked.length) {
    setStatus("Choose the package files first (team CSV, players CSV, …).", { error: true });
    return;
  }
  const fd = new FormData();
  picked.forEach((f) => fd.append("files", f, f.name));
  const title = $("title-input").value.trim();
  if (title) fd.append("title", title);
  setStatus("Loading…", { loading: true });
  try {
    const pkg = await fetchJson("/api/packages", { method: "POST", body: fd });
    const ign = pkg.files_ignored?.length ? ` Ignored: ${pkg.files_ignored.join(", ")}.` : "";
    setStatus(`Loaded ${pkg.files_used.join(", ")}.${ign}`);
    showPackage(pkg);
    refreshSaved();
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

async function refreshSaved() {
  try {
    const { packages } = await fetchJson("/api/packages");
    $("saved").hidden = !packages.length;
    $("saved-list").innerHTML = packages
      .map((p) => {
        const when = new Date(p.created_at * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
        const bits = [p.has_team ? "team" : null, p.players ? `${p.players} players` : null, p.has_shots ? "shots" : null, p.has_report ? "report" : null].filter(Boolean).join(" · ");
        return `<li class="viewer-saved"><a class="match-list__row" href="/?package=${encodeURIComponent(p.package_id)}" data-id="${esc(p.package_id)}"><span class="match-list__title">${esc(p.title)}</span><span class="match-list__meta">${esc(bits)} · ${esc(when)}</span></a><button class="btn btn--ghost viewer-del" type="button" data-del="${esc(p.package_id)}" title="Remove from this server">Remove</button></li>`;
      })
      .join("");
    $("saved-list").querySelectorAll("a[data-id]").forEach((a) =>
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        openPackage(a.dataset.id);
      })
    );
    $("saved-list").querySelectorAll("button[data-del]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        if (!confirm("Remove this loaded package from the server?")) return;
        await fetch(`/api/packages/${encodeURIComponent(btn.dataset.del)}`, { method: "DELETE" });
        if (current?.package_id === btn.dataset.del) {
          current = null;
          $("result").hidden = true;
          history.replaceState(null, "", "/");
        }
        refreshSaved();
      })
    );
  } catch {
    /* listing is optional */
  }
}

async function openPackage(id) {
  setStatus("Loading…", { loading: true });
  try {
    showPackage(await fetchJson(`/api/packages/${encodeURIComponent(id)}`));
    setStatus("");
  } catch (err) {
    setStatus(err.message, { error: true });
  }
}

refreshSaved();
const wanted = new URLSearchParams(location.search).get("package");
if (wanted) openPackage(wanted);
