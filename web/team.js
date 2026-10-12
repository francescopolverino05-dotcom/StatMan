import { fetchJson, fmt, qs, seasonBase } from "./common.js";

const teamId = Number(qs("team_id"));
const statusEl = document.getElementById("status");
const nameEl = document.getElementById("team-name");
const metaEl = document.getElementById("team-meta");
const summarySection = document.getElementById("summary-section");
const summaryEl = document.getElementById("summary");
const tbody = document.querySelector("#matches tbody");

function setStatus(text, { error = false, loading = false } = {}) {
  statusEl.textContent = text;
  statusEl.classList.toggle("is-error", error);
  statusEl.classList.toggle("is-loading", loading);
}

if (!teamId) {
  setStatus("Missing team_id query param.", { error: true });
} else {
  setStatus("Loading team sheet…", { loading: true });
  fetchJson(`${seasonBase()}/teams/${teamId}`)
    .then((data) => {
      nameEl.textContent = data.team_name || `Team ${teamId}`;
      document.title = `StatMan — ${data.team_name}`;
      metaEl.textContent = `${data.competition || ""} ${data.season || ""} · ${data.matches.length} matches`;

      if (data.summary) {
        const s = data.summary;
        summarySection.hidden = false;
        summaryEl.innerHTML = [
          ["Played", s.played],
          ["Record", `${s.wins}-${s.draws}-${s.losses}`],
          ["Points", s.points],
          ["Goals", `${s.goals_for}:${s.goals_against}`],
          ["xG / xGA", `${fmt(s.xg_for, 2)} / ${fmt(s.xg_against, 2)}`],
          ["Possession %", fmt(s.possession_pct)],
          ["PPDA", fmt(s.ppda, 2)],
          ["Progressive passes", s.progressive_passes],
        ]
          .map(
            ([label, value]) => `
          <li>
            <span class="label">${label}</span>
            <span class="value">${value}</span>
          </li>`
          )
          .join("");
      }

      tbody.innerHTML = data.matches
        .map((m) => {
          const date = String(m.game_date || "").slice(0, 10);
          return `
          <tr>
            <td><a href="/#match" data-game="${m.game_id}">${date}</a></td>
            <td>${m.venue}</td>
            <td>${m.opponent}</td>
            <td>${m.score_for}–${m.score_against}</td>
            <td>${m.result}</td>
            <td>${fmt(m.xg, 3)}</td>
            <td>${fmt(m.possession_pct)}</td>
            <td>${fmt(m.ppda, 2)}</td>
            <td>${fmt(m.progressive_passes, 0)}</td>
            <td>${m.pass_accuracy == null ? "—" : `${fmt(m.pass_accuracy)}%`}</td>
            <td>${fmt(m.tackles, 0)}</td>
            <td>${fmt(m.interceptions, 0)}</td>
          </tr>`;
        })
        .join("");
      setStatus(`${data.matches.length} matches loaded.`);
    })
    .catch((err) => setStatus(err.message, { error: true }));
}
