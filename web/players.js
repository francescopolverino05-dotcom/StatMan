import { fetchJson, fmt, seasonBase } from "./common.js";

const statusEl = document.getElementById("status");
const sortSelect = document.getElementById("sort-select");
const reloadBtn = document.getElementById("reload-btn");
const tbody = document.querySelector("#players tbody");
const BASE = seasonBase();

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

async function load() {
  const sort = sortSelect.value;
  setStatus(`Loading leaderboard (${sort})…`, { loading: true });
  reloadBtn.disabled = true;
  try {
    const data = await fetchJson(`${BASE}/players?sort=${encodeURIComponent(sort)}&limit=50`);
    tbody.innerHTML = data.players
      .map(
        (p, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${p.player_name || "—"}</td>
        <td><a href="/season/team?team_id=${p.team_id}">${p.team_name || "—"}</a></td>
        <td>${fmt(p.matches, 0)}</td>
        <td>${fmt(p.xg, 3)}</td>
        <td>${fmt(p.goals, 0)}</td>
        <td>${fmt(p.shots, 0)}</td>
        <td>${p.pass_accuracy == null ? "—" : `${fmt(p.pass_accuracy)}%`}</td>
        <td>${fmt(p.progressive_passes, 0)}</td>
        <td>${fmt(p.tackles, 0)}</td>
        <td>${fmt(p.interceptions, 0)}</td>
        <td>${fmt(p.aerials_won, 0)}/${fmt(p.aerials_lost, 0)}</td>
      </tr>`
      )
      .join("");
    setStatus(
      `${data.competition || "Season"} · ${data.matches_used} matches · top ${data.players.length} by ${data.sort}`
    );
  } catch (err) {
    tbody.innerHTML = "";
    setStatus(err.message, { error: true });
  } finally {
    reloadBtn.disabled = false;
  }
}

reloadBtn.addEventListener("click", load);
sortSelect.addEventListener("change", load);
load();
