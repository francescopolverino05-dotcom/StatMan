import { fetchJson, fmt, renderTeamCatalogHtml } from "./common.js";

const form = document.getElementById("import-form");
const eventsInput = document.getElementById("events-input");
const eventsLabel = document.getElementById("events-label");
const lineupsInput = document.getElementById("lineups-input");
const matchInput = document.getElementById("match-input");
const gameIdInput = document.getElementById("game-id");
const homeTeamInput = document.getElementById("home-team-id");
const statusEl = document.getElementById("status");
const results = document.getElementById("results");
const resultTitle = document.getElementById("result-title");
const resultMeta = document.getElementById("result-meta");
const teamGrid = document.getElementById("team-grid");
const playerBody = document.querySelector("#player-table tbody");
const importsBody = document.querySelector("#imports-table tbody");

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

eventsInput.addEventListener("change", () => {
  const file = eventsInput.files?.[0];
  eventsLabel.textContent = file ? file.name : "Choose events JSON…";
});

function renderStats(payload) {
  const stats = payload.stats || payload;
  const match = stats.match || {};
  results.hidden = false;
  resultTitle.textContent = `${match.home_team || "Home"} vs ${match.away_team || "Away"}`;
  resultMeta.textContent = [
    match.competition,
    match.season,
    match.game_date,
    `game ${match.game_id ?? "—"}`,
    stats.source?.import_format || stats.source?.provider,
    payload.import_id ? `import ${payload.import_id}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const teams = stats.teams || [];
  const home = teams.find((t) => t.team_id === match.home_team_id) || teams[0];
  const away = teams.find((t) => t.team_id === match.away_team_id) || teams[1];
  teamGrid.className = "team-board";
  teamGrid.innerHTML = `
    ${home ? renderTeamCatalogHtml(home, "Home") : ""}
    <div class="score-stack">
      <div class="score">${match.home_score ?? "—"}–${match.away_score ?? "—"}</div>
      <div class="vs">imported</div>
    </div>
    ${away ? renderTeamCatalogHtml(away, "Away") : ""}
  `;

  playerBody.innerHTML = (stats.players || [])
    .slice(0, 24)
    .map(
      (p) => `
    <tr>
      <td>${p.player_name || p.player_id}</td>
      <td>${p.team_name || "—"}</td>
      <td>${fmt(p.xg, 2)}</td>
      <td>${fmt(p.shots, 0)}</td>
      <td>${fmt(p.shots_on_target, 0)}</td>
      <td>${fmt(p.key_passes, 0)}</td>
      <td>${fmt(p.passes_attempted, 0)}</td>
      <td>${fmt(p.progressive_passes, 0)}</td>
      <td>${fmt(p.interceptions, 0)}</td>
      <td>${fmt(p.gk_saves, 0)}</td>
    </tr>`
    )
    .join("");

  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function refreshImports() {
  const data = await fetchJson("/api/imports?limit=12");
  importsBody.innerHTML = (data.imports || [])
    .map(
      (row) => `
    <tr data-import="${row.import_id}" class="job-row">
      <td><code>${row.import_id}</code></td>
      <td>${row.format}</td>
      <td>${row.home_team || "—"} vs ${row.away_team || "—"}</td>
      <td>${row.home_score ?? "—"}–${row.away_score ?? "—"}</td>
    </tr>`
    )
    .join("");
  for (const row of importsBody.querySelectorAll(".job-row")) {
    row.addEventListener("click", async () => {
      setStatus(`Loading import ${row.dataset.import}…`, { loading: true });
      try {
        const payload = await fetchJson(`/api/imports/${row.dataset.import}`);
        renderStats(payload);
        setStatus(`Loaded import ${row.dataset.import}.`);
      } catch (err) {
        setStatus(err.message, { error: true });
      }
    });
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const events = eventsInput.files?.[0];
  if (!events) {
    setStatus("Choose an events JSON file first.", { error: true });
    return;
  }
  const body = new FormData();
  body.append("events", events);
  if (lineupsInput.files?.[0]) body.append("lineups", lineupsInput.files[0]);
  if (matchInput.files?.[0]) body.append("match", matchInput.files[0]);
  if (gameIdInput.value) body.append("game_id", gameIdInput.value);
  if (homeTeamInput.value) body.append("home_team_id", homeTeamInput.value);

  setStatus("Importing event data…", { loading: true });
  try {
    const res = await fetch("/api/imports", { method: "POST", body });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail || detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail);
    }
    const payload = await res.json();
    renderStats(payload);
    setStatus(`Imported ${payload.format} match (${payload.import_id}).`);
    await refreshImports();
  } catch (err) {
    setStatus(err.message, { error: true });
  }
});

refreshImports().catch((err) => setStatus(err.message, { error: true }));
