import { fetchJson, fmt, seasonBase } from "./common.js";

const statusEl = document.getElementById("status");
const buildBtn = document.getElementById("build-btn");
const tbody = document.querySelector("#table tbody");
const BASE = seasonBase();

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

function renderTable(data) {
  tbody.innerHTML = data.teams
    .map(
      (t, i) => `
    <tr>
      <td>${i + 1}</td>
      <td><a href="/season/team?team_id=${t.team_id}">${t.team_name}</a></td>
      <td>${fmt(t.played, 0)}</td>
      <td>${fmt(t.wins, 0)}</td>
      <td>${fmt(t.draws, 0)}</td>
      <td>${fmt(t.losses, 0)}</td>
      <td>${fmt(t.goals_for, 0)}</td>
      <td>${fmt(t.goals_against, 0)}</td>
      <td><strong>${fmt(t.points, 0)}</strong></td>
      <td>${fmt(t.xg_for, 2)}</td>
      <td>${fmt(t.xg_against, 2)}</td>
      <td>${fmt(t.possession_pct)}</td>
      <td>${fmt(t.ppda, 2)}</td>
      <td>${fmt(t.progressive_passes, 0)}</td>
    </tr>`
    )
    .join("");
}

async function loadTable() {
  try {
    const data = await fetchJson(`${BASE}/table`);
    renderTable(data);
    setStatus(
      `${data.competition || "Season"} · ${data.matches_used} matches · ${data.teams.length} teams`
    );
    return true;
  } catch (err) {
    tbody.innerHTML = "";
    setStatus(err.message, { error: true });
    return false;
  }
}

async function pollBuild() {
  const data = await fetchJson(`${BASE}/build`);
  const b = data.build || {};
  const s = data.season || {};
  if (b.running) {
    setStatus(
      `Building… ${b.done || 0}/${b.total || s.games_total || "?"} (game ${b.current_game_id || "—"})`,
      { loading: true }
    );
    buildBtn.disabled = true;
    setTimeout(pollBuild, 2000);
    return;
  }
  buildBtn.disabled = false;
  if (b.error) {
    setStatus(`Build error: ${b.error}`, { error: true });
  }
  await loadTable();
}

async function startBuild() {
  buildBtn.disabled = true;
  setStatus("Starting season build…", { loading: true });
  try {
    await fetchJson(`${BASE}/build`, { method: "POST" });
    pollBuild();
  } catch (err) {
    buildBtn.disabled = false;
    setStatus(err.message, { error: true });
  }
}

buildBtn.addEventListener("click", startBuild);

(async () => {
  const overview = await fetchJson(BASE);
  if (overview.build?.running) {
    pollBuild();
    return;
  }
  if ((overview.stored_count || 0) === 0) {
    setStatus("No stored matches yet — click Build / refresh season (64 open games).");
    return;
  }
  await loadTable();
})().catch((err) => setStatus(err.message, { error: true }));
