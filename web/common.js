/** Shared helpers for StatMan pages. */

export const DEFAULT_COMPETITION_ID = 43;
export const DEFAULT_SEASON_ID = 3;
export const DEFAULT_GAME_ID = 8657;

export function fmt(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(digits);
  }
  return String(value);
}

export async function fetchJson(url, options) {
  const res = await fetch(url, options);
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

export function qs(name, fallback = null) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name) ?? fallback;
}

export function seasonBase(competitionId = DEFAULT_COMPETITION_ID, seasonId = DEFAULT_SEASON_ID) {
  return `/api/seasons/${competitionId}/${seasonId}`;
}

/** Format 1H / 2H / total period splits. */
export function fmtSplit(split) {
  if (!split || typeof split !== "object") return "—";
  if (
    split.first_half == null &&
    split.second_half == null &&
    split.total == null
  ) {
    return "—";
  }
  return `${fmt(split.first_half, 0)} / ${fmt(split.second_half, 0)} / ${fmt(split.total, 0)}`;
}

export function fmtPct(value) {
  return value == null ? "—" : `${fmt(value)}%`;
}

export function fmtPair(completed, attempted) {
  return `${fmt(completed, 0)} / ${fmt(attempted, 0)}`;
}

/** Grouped catalog rows for match / import team boards. */
export function fmtPassesAccurate(completed, attempted, accuracy) {
  if (attempted == null) return "—";
  const acc = accuracy == null ? "" : ` (${fmt(accuracy)}%)`;
  return `${fmt(completed, 0)} / ${fmt(attempted, 0)}${acc}`;
}

export function catalogSections(team) {
  const s = team.sections || {};
  const m = s.match || team;
  const a = s.attack || team;
  const p = s.passes || team;
  const d = s.defence || team;
  const g = s.goalkeeper || team;
  return [
    {
      title: "Match",
      rows: [
        ["Goals", fmt(m.goals ?? team.goals, 0)],
        ["Possession %", fmtPct(m.possession_pct ?? team.possession_pct)],
        ["Fouls committed", fmt(m.fouls_committed ?? team.fouls_committed, 0)],
        ["Fouls won", fmt(m.fouls_won ?? team.fouls_won, 0)],
        ["Yellow cards", fmt(m.yellow_cards ?? team.yellow_cards, 0)],
        ["Red cards", fmt(m.red_cards ?? team.red_cards, 0)],
        ["Offsides (1H / 2H / tot)", fmtSplit(m.offsides ?? team.offsides)],
        ["Corners (1H / 2H / tot)", fmtSplit(m.corners ?? team.corners)],
        ["Free kicks", fmt(m.free_kicks ?? team.free_kicks, 0)],
        ["Goal kicks", fmt(m.goal_kicks ?? team.goal_kicks, 0)],
        ["Throw-ins", fmt(m.throw_ins ?? team.throw_ins, 0)],
      ],
    },
    {
      title: "Attack",
      rows: [
        ["xG", fmt(a.xg ?? team.xg, 3)],
        ["Shots", fmt(a.shots ?? team.shots, 0)],
        ["Shots on target", fmt(a.shots_on_target ?? team.shots_on_target, 0)],
        ["Shot accuracy %", fmtPct(a.shot_accuracy ?? team.shot_accuracy)],
        ["Blocked shots", fmt(a.blocked_shots ?? team.blocked_shots, 0)],
        ["Missed shots", fmt(a.missed_shots ?? team.missed_shots, 0)],
        ["Shots inside box", fmt(a.shots_inside_box ?? team.shots_inside_box, 0)],
        ["Shots outside box", fmt(a.shots_outside_box ?? team.shots_outside_box, 0)],
        ["Headed shots", fmt(a.headed_shots ?? team.headed_shots, 0)],
        ["Key passes", fmt(a.key_passes ?? team.key_passes, 0)],
        [
          "Into final third (c / a)",
          fmtPair(
            a.into_final_third_completed ?? team.into_final_third_completed,
            a.into_final_third_attempted ?? team.into_final_third_attempted
          ),
        ],
        [
          "Into box (c / a)",
          fmtPair(a.into_box_completed ?? team.into_box_completed, a.into_box_attempted ?? team.into_box_attempted),
        ],
      ],
    },
    {
      title: "Passes",
      rows: [
        ["Passes", fmt(p.passes_attempted ?? team.passes_attempted, 0)],
        ["Passes completed", fmt(p.passes_completed ?? team.passes_completed, 0)],
        ["Pass accuracy %", fmtPct(p.pass_accuracy ?? team.pass_accuracy)],
        [
          "Progressive (c / a)",
          fmtPair(
            p.progressive_passes_completed ?? team.progressive_passes_completed ?? team.progressive_passes,
            p.progressive_passes_attempted ?? team.progressive_passes_attempted
          ),
        ],
        [
          "Crosses (c / tot)",
          fmtPair(p.crosses_completed ?? team.crosses_completed, p.crosses_total ?? team.crosses_total),
        ],
        [
          "Long balls (c / tot)",
          fmtPair(p.long_balls_completed ?? team.long_balls_completed, p.long_balls_total ?? team.long_balls_total),
        ],
        [
          "Through balls (c / tot)",
          fmtPair(
            p.through_balls_completed ?? team.through_balls_completed,
            p.through_balls_total ?? team.through_balls_total
          ),
        ],
      ],
    },
    {
      title: "Defence",
      rows: [
        ["Tackles", fmt(d.tackles ?? team.tackles, 0)],
        ["Interceptions", fmt(d.interceptions ?? team.interceptions, 0)],
        ["Recoveries", fmt(d.recoveries ?? team.recoveries, 0)],
        ["High recoveries", fmt(d.high_recoveries ?? team.high_recoveries, 0)],
        ["Balls lost", fmt(d.balls_lost ?? team.balls_lost, 0)],
        ["Blocks", fmt(d.blocks ?? team.blocks, 0)],
        ["Clearances", fmt(d.clearances ?? team.clearances, 0)],
        [
          "Ground duels (w / tot)",
          fmtPair(d.ground_duels_won ?? team.ground_duels_won, d.ground_duels_total ?? team.ground_duels_total),
        ],
        [
          "Aerial duels (w / tot)",
          fmtPair(d.aerials_won ?? team.aerials_won, d.aerials_total ?? team.aerials_total),
        ],
        ["PPDA", fmt(d.ppda ?? team.ppda, 2)],
      ],
    },
    {
      title: "Goalkeeper",
      rows: [
        ["Shots faced", fmt(g.shots_faced ?? team.shots_faced, 0)],
        ["Shots on target faced", fmt(g.shots_on_target_faced ?? team.shots_on_target_faced, 0)],
        ["Goals conceded", fmt(g.goals_conceded ?? team.goals_conceded, 0)],
        ["Saves", fmt(g.saves ?? team.saves ?? team.gk_saves, 0)],
        ["Save %", fmtPct(g.save_pct ?? team.save_pct)],
        [
          "Passes / accurate",
          fmtPassesAccurate(
            g.gk_passes_completed ?? team.gk_passes_completed,
            g.gk_passes_attempted ?? team.gk_passes_attempted,
            g.gk_pass_accuracy ?? team.gk_pass_accuracy
          ),
        ],
      ],
    },
  ];
}

export function renderTeamCatalogHtml(team, sideLabel, options = {}) {
  const sections = catalogSections(team);
  const formation =
    options.showFormation && team.formation
      ? `<p class="formation-line">${team.formation}</p>`
      : "";
  return `
    <div class="team-col team-col--catalog">
      <p class="side">${sideLabel}</p>
      <h3>${team.team_name}</h3>
      ${formation}
      ${sections
        .map(
          (sec) => `
        <div class="stat-section">
          <h4 class="stat-section__title">${sec.title}</h4>
          <ul class="stat-list">
            ${sec.rows
              .map(([label, value]) => {
                const empty = value === "—";
                return `
              <li class="${empty ? "is-empty" : "is-filled"}">
                <span class="label">${label}</span>
                <span class="value${empty ? " value--empty" : ""}">${value}</span>
              </li>`;
              })
              .join("")}
          </ul>
        </div>`
        )
        .join("")}
    </div>
  `;
}

/* ---- CSV export (team board + player sheet) ---- */

function csvCell(v) {
  const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
  return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function csvText(header, rows) {
  return [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\n") + "\n";
}

/** metric,home,away rows from the same catalog the team board shows. */
export function teamsToCsv(home, away) {
  const a = catalogSections(home);
  const b = away ? catalogSections(away) : [];
  const rows = [];
  a.forEach((sec, i) => {
    sec.rows.forEach(([label, value], j) => {
      const other = b[i]?.rows[j]?.[1];
      rows.push([`${sec.title}: ${label}`, value === "—" ? "" : value, other === undefined || other === "—" ? "" : other]);
    });
  });
  return csvText(["metric", home.team_name, away?.team_name ?? ""], rows);
}

/** Every field of every player object, one column per key. */
export function playersToCsv(players) {
  const cols = [];
  for (const p of players) for (const k of Object.keys(p)) if (!cols.includes(k)) cols.push(k);
  return csvText(cols, players.map((p) => cols.map((c) => p[c])));
}

export function downloadCsv(filename, text) {
  const blob = new Blob(["\ufeff", text], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
