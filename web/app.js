import { fetchJson, fmt, renderTeamCatalogHtml } from "./common.js";

const select = document.getElementById("game-select");
const loadBtn = document.getElementById("load-btn");
const statusEl = document.getElementById("status");
const boardSection = document.getElementById("board");
const mapsSection = document.getElementById("maps");
const playersSection = document.getElementById("players");
const teamBoard = document.getElementById("team-board");
const playerBody = document.querySelector("#player-table tbody");
const scoreline = document.getElementById("scoreline");
const matchMeta = document.getElementById("match-meta");
const defsEl = document.getElementById("definitions");
const mapTeam = document.getElementById("map-team");
const mapShots = document.getElementById("map-shots");
const mapProg = document.getElementById("map-progressive");
const mapDef = document.getElementById("map-defence");

const DEFAULT_GAME_ID = 8657;
let currentGameId = DEFAULT_GAME_ID;

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

function setMaps(gameId, match) {
  currentGameId = gameId;
  mapTeam.innerHTML = `
    <option value="">Both teams</option>
    <option value="${match.home_team_id}">${match.home_team}</option>
    <option value="${match.away_team_id}">${match.away_team}</option>
  `;
  refreshMaps();
  mapsSection.hidden = false;
}

function refreshMaps() {
  const teamQ = mapTeam.value ? `?team_id=${encodeURIComponent(mapTeam.value)}` : "";
  const bust = `&t=${Date.now()}`;
  const q = teamQ ? `${teamQ}${bust}` : `?t=${Date.now()}`;
  mapShots.src = `/api/matches/${currentGameId}/maps/shots.png${q}`;
  mapProg.src = `/api/matches/${currentGameId}/maps/progressive.png${q}`;
  mapDef.src = `/api/matches/${currentGameId}/maps/defence.png${q}`;
}

function renderMatch(data) {
  const { match, teams, players, definitions, source } = data;
  const home = teams.find((t) => t.team_id === match.home_team_id) || teams[0];
  const away = teams.find((t) => t.team_id === match.away_team_id) || teams[1];

  scoreline.textContent = `${match.home_team} ${match.home_score}–${match.away_score} ${match.away_team}`;
  matchMeta.textContent = `${match.competition} ${match.season} · ${match.game_date} · ${source.schema}`;

  teamBoard.innerHTML = `
    ${renderTeamCatalogHtml(home, "Home")}
    <div class="score-stack">
      <div class="score">${match.home_score}–${match.away_score}</div>
      <div class="vs">full time</div>
    </div>
    ${renderTeamCatalogHtml(away, "Away")}
  `;

  playerBody.innerHTML = players
    .map(
      (p, i) => `
    <tr style="animation-delay:${Math.min(i, 12) * 30}ms">
      <td>${p.player_name || "—"}</td>
      <td>${p.team_name}</td>
      <td>${fmt(p.xg, 3)}</td>
      <td>${fmt(p.shots, 0)}</td>
      <td>${fmt(p.shots_on_target, 0)}</td>
      <td>${fmt(p.key_passes, 0)}</td>
      <td>${p.pass_accuracy == null ? "—" : `${fmt(p.pass_accuracy)}%`}</td>
      <td>${fmt(p.progressive_passes, 0)}</td>
      <td>${fmt(p.interceptions, 0)}</td>
      <td>${fmt(p.recoveries, 0)}</td>
      <td>${fmt(p.aerials_won, 0)}/${fmt(p.aerials_lost, 0)}</td>
    </tr>`
    )
    .join("");

  defsEl.innerHTML = Object.entries(definitions || {})
    .map(
      ([key, text]) => `
    <div>
      <dt>${key}</dt>
      <dd>${text}</dd>
    </div>`
    )
    .join("");

  setMaps(match.game_id, match);

  boardSection.hidden = false;
  playersSection.hidden = false;
  boardSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadGames() {
  setStatus("Fetching open World Cup 2018 matches…", { loading: true });
  try {
    const data = await fetchJson("/api/games/demo?limit=24");
    select.innerHTML = "";
    for (const g of data.games) {
      const opt = document.createElement("option");
      opt.value = g.game_id;
      opt.textContent = `${g.home_team} ${g.home_score}–${g.away_score} ${g.away_team} · ${g.game_date.slice(0, 10)}`;
      if (g.game_id === DEFAULT_GAME_ID) opt.selected = true;
      select.appendChild(opt);
    }
    select.disabled = false;
    loadBtn.disabled = false;
    setStatus(`${data.count} matches ready. Demo default: Belgium–England.`);
  } catch (err) {
    setStatus(`Could not load match list: ${err.message}`, { error: true });
  }
}

async function loadStats() {
  const gameId = Number(select.value || DEFAULT_GAME_ID);
  loadBtn.disabled = true;
  setStatus(`Computing SPADL stats for match ${gameId}…`, { loading: true });
  try {
    const data = await fetchJson(`/api/matches/${gameId}/stats`);
    renderMatch(data);
    setStatus(`Loaded ${data.match.home_team} vs ${data.match.away_team}.`);
  } catch (err) {
    setStatus(`Failed: ${err.message}`, { error: true });
  } finally {
    loadBtn.disabled = false;
  }
}

mapTeam?.addEventListener("change", refreshMaps);
loadBtn.addEventListener("click", loadStats);
loadGames();
