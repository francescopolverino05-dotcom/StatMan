const select = document.getElementById("game-select");
const loadBtn = document.getElementById("load-btn");
const statusEl = document.getElementById("status");
const boardSection = document.getElementById("board");
const playersSection = document.getElementById("players");
const teamBoard = document.getElementById("team-board");
const playerBody = document.querySelector("#player-table tbody");
const scoreline = document.getElementById("scoreline");
const matchMeta = document.getElementById("match-meta");
const defsEl = document.getElementById("definitions");

const DEFAULT_GAME_ID = 8657;

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(digits);
  return String(value);
}

function teamColumn(team, sideLabel) {
  const items = [
    ["Possession %", fmt(team.possession_pct)],
    ["xG", fmt(team.xg, 3)],
    ["Shots", fmt(team.shots, 0)],
    ["Pass accuracy", team.pass_accuracy == null ? "—" : `${fmt(team.pass_accuracy)}%`],
    ["Progressive passes", fmt(team.progressive_passes, 0)],
    ["PPDA", fmt(team.ppda, 2)],
    ["Tackles", fmt(team.tackles, 0)],
    ["Interceptions", fmt(team.interceptions, 0)],
    ["Clearances", fmt(team.clearances, 0)],
    ["Aerials (W / L)", `${fmt(team.aerials_won, 0)} / ${fmt(team.aerials_lost, 0)}`],
  ];

  return `
    <div class="team-col">
      <p class="side">${sideLabel}</p>
      <h3>${team.team_name}</h3>
      <ul class="stat-list">
        ${items
          .map(
            ([label, value]) => `
          <li>
            <span class="label">${label}</span>
            <span class="value">${value}</span>
          </li>`
          )
          .join("")}
      </ul>
    </div>
  `;
}

function renderMatch(data) {
  const { match, teams, players, definitions, source } = data;
  const home = teams.find((t) => t.team_id === match.home_team_id) || teams[0];
  const away = teams.find((t) => t.team_id === match.away_team_id) || teams[1];

  scoreline.textContent = `${match.home_team} ${match.home_score}–${match.away_score} ${match.away_team}`;
  matchMeta.textContent = `${match.competition} ${match.season} · ${match.game_date} · ${source.schema}`;

  teamBoard.innerHTML = `
    ${teamColumn(home, "Home")}
    <div class="score-stack">
      <div class="score">${match.home_score}–${match.away_score}</div>
      <div class="vs">full time</div>
    </div>
    ${teamColumn(away, "Away")}
  `;

  playerBody.innerHTML = players
    .map(
      (p, i) => `
    <tr style="animation-delay:${Math.min(i, 12) * 30}ms">
      <td>${p.player_name || "—"}</td>
      <td>${p.team_name}</td>
      <td>${fmt(p.xg, 3)}</td>
      <td>${fmt(p.shots, 0)}</td>
      <td>${p.pass_accuracy == null ? "—" : `${fmt(p.pass_accuracy)}%`}</td>
      <td>${fmt(p.progressive_passes, 0)}</td>
      <td>${fmt(p.tackles, 0)}</td>
      <td>${fmt(p.interceptions, 0)}</td>
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

loadBtn.addEventListener("click", loadStats);
select.addEventListener("change", () => setStatus("Ready to compute."));

loadGames();
