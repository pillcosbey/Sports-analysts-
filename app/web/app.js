/* ===== PropEdge Halftime Parlay Analyzer ===== */

let currentSport = "nba";
let currentGameId = null;
let currentLegs = [];           // populated from /api/halftime/{sport}/{id}
let pickedLegIndexes = new Set();

const TEAM_TINT = {
  ATL: "#e03a3e", BOS: "#007a33", BKN: "#111111", CHA: "#1d1160",
  CHI: "#ce1141", CLE: "#860038", DAL: "#00538c", DEN: "#0e2240",
  DET: "#c8102e", GSW: "#1d428a", HOU: "#ce1141", IND: "#002d62",
  LAC: "#c8102e", LAL: "#552583", MEM: "#5d76a9", MIA: "#98002e",
  MIL: "#00471b", MIN: "#0c2340", NOP: "#0c2340", NYK: "#006bb6",
  OKC: "#007ac1", ORL: "#0077c0", PHI: "#006bb6", PHX: "#1d1160",
  POR: "#e03a3e", SAC: "#5a2d81", SAS: "#c4ced4", TOR: "#ce1141",
  UTA: "#002b5c", WAS: "#002b5c",
};

/* ===== Toast ===== */
function toast(msg, type = "default") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 300); }, 2500);
}

function initials(name) {
  return (name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

function prettyStat(s) {
  const map = {
    points: "Points", rebounds: "Rebounds", assists: "Assists",
    threes_made: "Threes", steals: "Steals", blocks: "Blocks",
    pra: "P+R+A", pr: "Pts+Reb", pa: "Pts+Ast", ra: "Reb+Ast",
  };
  return map[s] || (s || "").replace(/_/g, " ");
}

/* ===== Panel switching ===== */
function showPanel(name) {
  document.getElementById("halftime-panel").classList.toggle("hidden", name !== "halftime");
  document.getElementById("picks-panel").classList.toggle("hidden", name !== "picks");
  document.getElementById("bets-panel").classList.toggle("hidden", name !== "bets");
  document.querySelectorAll("#main-nav button").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  if (name === "halftime") loadGames();
  if (name === "picks") loadPicks();
  if (name === "bets") loadBets();
}

document.querySelectorAll("#main-nav button").forEach(b =>
  b.addEventListener("click", () => showPanel(b.dataset.tab)));

document.getElementById("refresh-btn").addEventListener("click", () => {
  if (!document.getElementById("halftime-panel").classList.contains("hidden")) {
    if (currentGameId) loadGameDetail(currentGameId); else loadGames();
  } else if (!document.getElementById("picks-panel").classList.contains("hidden")) {
    loadPicks();
  } else {
    loadBets();
  }
});

/* ===== Halftime: game list ===== */
document.querySelectorAll(".ht-sport-toggle button").forEach(b =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".ht-sport-toggle button").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    currentSport = b.dataset.sport;
    currentGameId = null;
    document.getElementById("ht-detail").classList.add("hidden");
    loadGames();
  }));

async function loadGames() {
  const host = document.getElementById("ht-games");
  host.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Looking for ${currentSport.toUpperCase()} games...</span></div>`;
  try {
    const r = await fetch(`/api/halftime/games?sport=${currentSport}`);
    const d = await r.json();
    renderGames(d.games || []);
  } catch (e) {
    host.innerHTML = `<div class="empty-state">Failed to load games. Tap refresh.</div>`;
  }
}

function renderGames(games) {
  const host = document.getElementById("ht-games");
  if (!games.length) {
    host.innerHTML = `
      <div class="empty-state">
        <div style="font-size:1.5rem;margin-bottom:6px;">&#127944;</div>
        No ${currentSport.toUpperCase()} games at halftime right now.<br/>
        Refresh near halftime of a live game.
      </div>`;
    return;
  }
  host.innerHTML = games.map(g => {
    const halfBadge = g.is_halftime
      ? `<span class="pill live">HALFTIME</span>`
      : `<span class="pill">${g.sport === "mlb" ? g.status : `Q${g.quarter} ${g.clock}`}</span>`;
    const score = g.home_score !== undefined ? `${g.away_score}-${g.home_score}` : "";
    return `
      <button class="ht-game-card" onclick="loadGameDetail('${g.game_id}')">
        <div class="ht-game-teams">
          <span class="ht-team" style="border-left-color:${TEAM_TINT[g.away] || '#666'}">${g.away || "?"}</span>
          <span class="ht-score">${score}</span>
          <span class="ht-team" style="border-left-color:${TEAM_TINT[g.home] || '#666'}">${g.home || "?"}</span>
        </div>
        <div class="ht-game-foot">${halfBadge}</div>
      </button>`;
  }).join("");
}

/* ===== Halftime: game detail ===== */
async function loadGameDetail(gameId) {
  currentGameId = gameId;
  pickedLegIndexes = new Set();
  const detail = document.getElementById("ht-detail");
  detail.classList.remove("hidden");
  detail.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Analyzing game...</span></div>`;
  try {
    const r = await fetch(`/api/halftime/${currentSport}/${gameId}`);
    const d = await r.json();
    if (d.error) {
      detail.innerHTML = `<div class="empty-state">${d.error}</div>`;
      return;
    }
    if (currentSport === "nba") renderNbaDetail(d);
    else renderMlbDetail(d);
  } catch (e) {
    detail.innerHTML = `<div class="empty-state">Failed to load game</div>`;
  }
}

function renderNbaDetail(d) {
  currentLegs = (d.legs || []).map((l, i) => ({ ...l, _idx: i }));
  // Sort by edge proxy: prob distance from 0.5 in the chosen side
  currentLegs.sort((a, b) => Math.max(b.p_over, 1 - b.p_over) - Math.max(a.p_over, 1 - a.p_over));

  const linescore = d.away_quarters?.length
    ? `<table class="ht-linescore"><tr><th></th>${d.away_quarters.map((_, i) => `<th>Q${i+1}</th>`).join("")}<th>T</th></tr>
       <tr><td>${d.away_team}</td>${d.away_quarters.map(q => `<td>${q}</td>`).join("")}<td><b>${d.away_score}</b></td></tr>
       <tr><td>${d.home_team}</td>${d.home_quarters.map(q => `<td>${q}</td>`).join("")}<td><b>${d.home_score}</b></td></tr>
       </table>` : "";

  document.getElementById("ht-detail").innerHTML = `
    <div class="ht-detail-head">
      <button class="btn btn-sm btn-outline" onclick="closeDetail()">&larr; Back</button>
      <div class="ht-detail-title">${d.away_team_name || d.away_team} @ ${d.home_team_name || d.home_team}</div>
      <span class="pill ${d.is_halftime ? 'live' : ''}">${d.is_halftime ? 'HALFTIME' : `Q${d.quarter} ${d.clock}`}</span>
    </div>
    ${linescore}
    <div class="ht-pace">Pace factor <b>${d.pace_factor}×</b> · ${d.legs.length} legs projected</div>

    <div class="ht-controls">
      <select id="ht-side-filter">
        <option value="best">Best side</option>
        <option value="over">OVER only</option>
        <option value="under">UNDER only</option>
      </select>
      <select id="ht-stat-filter">
        <option value="">All stats</option>
        <option value="points">Points</option>
        <option value="rebounds">Rebounds</option>
        <option value="assists">Assists</option>
        <option value="threes_made">Threes</option>
        <option value="pra">P+R+A</option>
        <option value="pr">Pts+Reb</option>
        <option value="pa">Pts+Ast</option>
      </select>
      <button id="ht-suggest" class="btn btn-primary btn-sm">Suggest Parlays</button>
    </div>

    <div id="ht-legs" class="ht-legs"></div>
    <div id="ht-suggestions" class="ht-suggestions"></div>
  `;
  document.getElementById("ht-side-filter").addEventListener("change", renderLegs);
  document.getElementById("ht-stat-filter").addEventListener("change", renderLegs);
  document.getElementById("ht-suggest").addEventListener("click", runSuggest);
  renderLegs();
}

function renderLegs() {
  const sideFilter = document.getElementById("ht-side-filter").value;
  const statFilter = document.getElementById("ht-stat-filter").value;
  const host = document.getElementById("ht-legs");

  const rows = currentLegs
    .filter(l => !statFilter || l.stat === statFilter)
    .map(l => {
      const overBetter = l.p_over >= 0.5;
      let side, prob;
      if (sideFilter === "over")      { side = "OVER";  prob = l.p_over;       }
      else if (sideFilter === "under"){ side = "UNDER"; prob = 1 - l.p_over;   }
      else                             { side = overBetter ? "OVER" : "UNDER"; prob = Math.max(l.p_over, 1 - l.p_over); }
      const edge = (prob - 0.5) * 100;
      const edgeClass = edge >= 8 ? "high" : edge >= 4 ? "mid" : "low";
      const picked = pickedLegIndexes.has(l._idx) && pickedLegIndexes.get?.(l._idx)?.side === side;
      const checked = pickedLegIndexes.has(l._idx);
      const tint = TEAM_TINT[l.team] || "#5a6270";
      const foul = l.foul_trouble ? `<span class="ht-leg-warn" title="In foul trouble">FT</span>` : "";
      return `
        <div class="ht-leg ${checked ? 'picked' : ''}" data-idx="${l._idx}">
          <div class="ht-leg-left">
            <span class="ht-leg-avatar" style="background:${tint}">${initials(l.player)}</span>
            <div class="ht-leg-info">
              <div class="ht-leg-player">${l.player} ${foul}</div>
              <div class="ht-leg-meta">${l.team} · ${prettyStat(l.stat)} · ${l.so_far} so far · ${l.minutes_so_far}m</div>
            </div>
          </div>
          <div class="ht-leg-pick">
            <span class="ht-leg-side ${side === 'OVER' ? 'over' : 'under'}">${side}</span>
            <span class="ht-leg-line">${l.line}</span>
            <span class="ht-leg-prob ${edgeClass}">${(prob*100).toFixed(0)}%</span>
            <button class="ht-leg-add" data-side="${side}" data-idx="${l._idx}">${checked ? '−' : '+'}</button>
          </div>
        </div>`;
    }).join("");

  host.innerHTML = rows || `<div class="empty-state">No legs match filters</div>`;
  host.querySelectorAll(".ht-leg-add").forEach(b => b.addEventListener("click", e => {
    const idx = parseInt(e.currentTarget.dataset.idx, 10);
    const side = e.currentTarget.dataset.side;
    toggleLeg(idx, side);
  }));
}

function toggleLeg(idx, side) {
  // pickedLegIndexes is actually a Map of idx -> {side}
  if (!(pickedLegIndexes instanceof Map)) pickedLegIndexes = new Map();
  if (pickedLegIndexes.has(idx)) pickedLegIndexes.delete(idx);
  else pickedLegIndexes.set(idx, { side });
  renderLegs();
  updateSelectionBadge();
}

function updateSelectionBadge() {
  const n = pickedLegIndexes instanceof Map ? pickedLegIndexes.size : 0;
  const btn = document.getElementById("ht-suggest");
  if (btn) btn.textContent = n > 0 ? `Suggest from ${n} picks` : "Suggest Parlays";
}

function closeDetail() {
  currentGameId = null;
  document.getElementById("ht-detail").classList.add("hidden");
}

async function runSuggest() {
  // If user has manually picked legs, use those; otherwise use the top-ranked auto pool.
  let pool;
  if (pickedLegIndexes instanceof Map && pickedLegIndexes.size >= 2) {
    pool = [...pickedLegIndexes.entries()].map(([idx, v]) => {
      const l = currentLegs.find(x => x._idx === idx);
      return legToCandidate(l, v.side);
    });
  } else {
    pool = currentLegs.slice(0, 14).map(l => legToCandidate(l, l.p_over >= 0.5 ? "OVER" : "UNDER"));
  }

  const host = document.getElementById("ht-suggestions");
  host.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Building combos...</span></div>`;
  try {
    const r = await fetch("/api/builder/suggest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sport: currentSport,
        game_id: currentGameId,
        legs: pool,
        min_leg_prob: 0.52,
        min_ev: -0.20,
        top_k: 8,
      }),
    });
    const d = await r.json();
    renderSuggestions(d.suggestions || []);
  } catch (e) {
    host.innerHTML = `<div class="empty-state">Suggestion engine failed</div>`;
  }
}

function legToCandidate(l, side) {
  // Default to -110 odds for picked legs (we don't have real odds yet)
  return {
    player: l.player, team: l.team, stat: l.stat, side,
    line: l.line,
    model_prob: side === "OVER" ? l.p_over : (1 - l.p_over),
    american_odds: -110,
    decimal_odds: 1.91,
  };
}

function renderSuggestions(suggestions) {
  const host = document.getElementById("ht-suggestions");
  if (!suggestions.length) {
    host.innerHTML = `<div class="empty-state">No +EV combos found from this pool</div>`;
    return;
  }
  host.innerHTML = `
    <div class="ht-section-title">Suggested Builders</div>
    ${suggestions.map((s, i) => {
      const evColor = s.ev_per_dollar >= 0.1 ? "var(--green)" : s.ev_per_dollar >= 0 ? "var(--yellow)" : "var(--red)";
      const evSign = s.ev_per_dollar >= 0 ? "+" : "";
      const ams = s.combined_american > 0 ? `+${s.combined_american}` : `${s.combined_american}`;
      return `
        <div class="ht-suggestion">
          <div class="ht-suggestion-head">
            <span class="pill">${s.size} legs</span>
            <span class="ht-odds">${ams}</span>
            <span class="ht-prob">${(s.correlated_prob*100).toFixed(1)}% hit</span>
            <span class="ht-ev" style="color:${evColor}">${evSign}$${s.ev_per_dollar.toFixed(2)}/$1</span>
          </div>
          <div class="ht-suggestion-legs">
            ${s.legs.map(l => `
              <div class="ht-sug-leg">
                <span class="ht-sug-avatar" style="background:${TEAM_TINT[l.team] || '#5a6270'}">${initials(l.player)}</span>
                <span class="ht-sug-name">${l.player}</span>
                <span class="ht-sug-pick ${l.side === 'OVER' ? 'over' : 'under'}">${l.side} ${l.line} ${prettyStat(l.stat)}</span>
                <span class="ht-sug-prob">${(l.model_prob*100).toFixed(0)}%</span>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }).join("")}
  `;
}

function renderMlbDetail(d) {
  const host = document.getElementById("ht-detail");
  const hitters = (d.players || []).filter(p => !p.is_pitcher && p.at_bats >= 1);
  const pitchers = (d.players || []).filter(p => p.is_pitcher && p.innings_pitched > 0);

  host.innerHTML = `
    <div class="ht-detail-head">
      <button class="btn btn-sm btn-outline" onclick="closeDetail()">&larr; Back</button>
      <div class="ht-detail-title">${d.away_team} @ ${d.home_team}</div>
      <span class="pill">${d.is_top ? 'Top' : 'Bot'} ${d.inning}</span>
    </div>
    <div class="ht-mlb-section">
      <h3>Hitters</h3>
      ${hitters.length ? hitters.map(p => `
        <div class="ht-mlb-row">
          <span class="ht-mlb-player">${p.player}</span>
          <span class="ht-mlb-team">${p.team}</span>
          <span class="ht-mlb-stat">${p.hits}-${p.at_bats}</span>
          <span class="ht-mlb-stat">${p.total_bases} TB</span>
          <span class="ht-mlb-stat">${p.runs} R · ${p.rbis} RBI</span>
        </div>`).join("") : '<div class="empty-state">No hitter data yet</div>'}
    </div>
    <div class="ht-mlb-section">
      <h3>Pitchers</h3>
      ${pitchers.length ? pitchers.map(p => `
        <div class="ht-mlb-row">
          <span class="ht-mlb-player">${p.player}</span>
          <span class="ht-mlb-team">${p.team}</span>
          <span class="ht-mlb-stat">${p.innings_pitched} IP</span>
          <span class="ht-mlb-stat">${p.strikeouts} K</span>
          <span class="ht-mlb-stat">${p.pitch_count} pitches</span>
        </div>`).join("") : '<div class="empty-state">No pitcher data yet</div>'}
    </div>
  `;
}

/* ===== Picks (Claude's track record) ===== */
async function loadPicks() {
  const list = document.getElementById("picks-list");
  list.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Loading picks...</span></div>`;
  try {
    const r = await fetch("/api/picks");
    const d = await r.json();
    renderPickSummary(d.stats);
    renderPickList(d.picks);
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Failed to load picks</div>`;
  }
}

async function gradeAllPending() {
  toast("Grading all pending picks...");
  try {
    const r = await fetch("/api/picks/grade-pending", { method: "POST" });
    const d = await r.json();
    if (d.error) { toast(d.error, "error"); return; }
    toast(`Graded ${d.graded} pick${d.graded === 1 ? "" : "s"}`, "success");
    loadPicks();
  } catch (e) { toast("Grade-all failed", "error"); }
}

document.getElementById("grade-all-btn").addEventListener("click", gradeAllPending);

function renderPickSummary(s) {
  const roiColor = s.pnl >= 0 ? "var(--green)" : "var(--red)";
  const calColor = Math.abs(s.calibration_gap) < 0.05 ? "var(--green)" : Math.abs(s.calibration_gap) < 0.15 ? "var(--yellow)" : "var(--red)";
  document.getElementById("picks-summary").innerHTML = `
    <div class="bt-summary">
      <div class="bt-stat"><div class="val">${s.total_picks}</div><div class="lbl">Picks</div></div>
      <div class="bt-stat"><div class="val">${s.wins}-${s.losses}${s.pushes ? `-${s.pushes}` : ''}</div><div class="lbl">Record</div></div>
      <div class="bt-stat"><div class="val">${(s.win_rate*100).toFixed(1)}%</div><div class="lbl">Hit Rate</div></div>
      <div class="bt-stat"><div class="val" style="color:${roiColor}">${s.pnl >= 0 ? '+' : ''}$${s.pnl.toFixed(2)}</div><div class="lbl">P/L ($1 flat)</div></div>
      <div class="bt-stat"><div class="val" style="color:${roiColor}">${s.roi_pct >= 0 ? '+' : ''}${s.roi_pct.toFixed(1)}%</div><div class="lbl">ROI</div></div>
      <div class="bt-stat"><div class="val" style="color:${calColor}">${s.calibration_gap >= 0 ? '+' : ''}${(s.calibration_gap*100).toFixed(1)}%</div><div class="lbl">Calibration</div></div>
    </div>`;
}

function renderPickList(picks) {
  const list = document.getElementById("picks-list");
  if (!picks.length) {
    list.innerHTML = `<div class="empty-state">No picks yet. Ask Claude for a parlay and I'll log it here automatically.</div>`;
    return;
  }
  picks.sort((a, b) => b.suggested_at - a.suggested_at);
  list.innerHTML = picks.map(p => {
    const odds = p.american_odds ? (p.american_odds > 0 ? `+${p.american_odds}` : `${p.american_odds}`) : "—";
    const statusClass = p.status === "won" ? "won" : p.status === "lost" ? "lost" : p.status === "push" ? "push" : "open";
    const modelProb = p.model_prob != null ? `${(p.model_prob*100).toFixed(1)}% model` : "";
    const ev = p.ev_per_dollar != null ? `${p.ev_per_dollar >= 0 ? '+' : ''}$${p.ev_per_dollar.toFixed(2)} EV` : "";
    const confTag = p.confidence ? `<span class="conf-tag conf-${p.confidence}">${p.confidence.toUpperCase()}</span>` : "";
    const settleBtns = p.status === "open" ? `
      <button class="btn btn-sm" onclick="settlePick('${p.id}','won')">Won</button>
      <button class="btn btn-sm btn-danger" onclick="settlePick('${p.id}','lost')">Lost</button>
      <button class="btn btn-sm btn-outline" onclick="settlePick('${p.id}','push')">Push</button>
    ` : `
      <button class="btn btn-sm btn-outline" onclick="settlePick('${p.id}','open')">Reopen</button>
    `;
    const promoteBtn = p.promoted_to_bet_id
      ? `<span class="promoted-tag">Promoted ✓</span>`
      : `<button class="btn btn-sm btn-primary" onclick="promotePick('${p.id}')">Place this</button>`;
    const canAutoGrade = p.status === "open" && (p.game_id || (p.game_date && p.home_team && p.away_team));
    const autoGradeBtn = canAutoGrade
      ? `<button class="btn btn-sm btn-outline" onclick="autoGradePick('${p.id}')">Auto-grade</button>`
      : "";
    return `
      <div class="bet-card status-${statusClass}">
        <div class="bet-head">
          ${confTag}
          <span class="bet-odds">${odds}</span>
          <span class="bet-sport">${(p.sport || '').toUpperCase()}</span>
          <span class="pick-prob">${modelProb}</span>
          <span class="pick-ev">${ev}</span>
          <span class="bet-status">${p.status.toUpperCase()}</span>
        </div>
        ${p.rationale ? `<div class="pick-rationale">${p.rationale}</div>` : ""}
        <div class="bet-legs">
          ${p.legs.map(l => {
            const lp = l.model_prob != null ? ` <span class="pick-leg-prob">${(l.model_prob*100).toFixed(0)}%</span>` : "";
            return `<div class="bet-leg-row"><span class="bet-leg-status ${l.status}">●</span>${l.description || `${l.player} ${l.side} ${l.line} ${l.stat}`}${lp}</div>`;
          }).join("")}
        </div>
        <div class="bet-actions">
          ${settleBtns}
          ${autoGradeBtn}
          ${promoteBtn}
          <button class="btn btn-sm btn-danger" onclick="deletePick('${p.id}')">Delete</button>
        </div>
      </div>`;
  }).join("");
}

async function settlePick(id, status) {
  try {
    const r = await fetch(`/api/picks/${id}/settle`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const d = await r.json();
    if (d.error) toast(d.error, "error");
    else toast(`Pick ${status}`, "success");
    loadPicks();
  } catch (e) { toast("Settle failed", "error"); }
}

async function promotePick(id) {
  const stakeStr = prompt("Stake $ for this bet?", "10");
  if (stakeStr === null) return;
  const stake = parseFloat(stakeStr);
  if (!stake || stake <= 0) { toast("Invalid stake", "error"); return; }
  try {
    const r = await fetch(`/api/picks/${id}/promote`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stake }),
    });
    const d = await r.json();
    if (d.error) { toast(d.error, "error"); return; }
    toast("Placed in My Bets", "success");
    loadPicks();
  } catch (e) { toast("Promote failed", "error"); }
}

async function autoGradePick(id) {
  toast("Grading from final box score...");
  try {
    const r = await fetch(`/api/picks/${id}/auto-grade`, { method: "POST" });
    const d = await r.json();
    if (d.error) { toast(d.error, "error"); return; }
    if (d.committed) {
      const legSummary = d.legs.map(l =>
        `${l.player} ${l.side} ${l.line} ${l.stat}: ${l.actual ?? "?"} → ${l.status.toUpperCase()}`
      ).join("\n");
      toast(`Pick ${d.overall.toUpperCase()} · ${d.box_score}`, d.overall === "won" ? "success" : "error");
      alert(`${d.box_score}\n\n${legSummary}\n\nOverall: ${d.overall.toUpperCase()}`);
    } else {
      toast(d.note || "Game not final yet", "default");
    }
    loadPicks();
  } catch (e) { toast("Auto-grade failed", "error"); }
}

async function deletePick(id) {
  if (!confirm("Delete this pick?")) return;
  try {
    await fetch(`/api/picks/${id}`, { method: "DELETE" });
    toast("Deleted");
    loadPicks();
  } catch (e) { toast("Delete failed", "error"); }
}

/* ===== Bets ===== */
async function loadBets() {
  const list = document.getElementById("bets-list");
  list.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Loading bets...</span></div>`;
  try {
    const r = await fetch("/api/bets");
    const d = await r.json();
    renderBetSummary(d.stats);
    renderBetList(d.bets);
  } catch (e) {
    list.innerHTML = `<div class="empty-state">Failed to load bets</div>`;
  }
}

function renderBetSummary(s) {
  const roiColor = s.pnl >= 0 ? "var(--green)" : "var(--red)";
  document.getElementById("bets-summary").innerHTML = `
    <div class="bt-summary">
      <div class="bt-stat"><div class="val">${s.total_bets}</div><div class="lbl">Bets</div></div>
      <div class="bt-stat"><div class="val">${s.wins}W-${s.losses}L${s.pushes ? `-${s.pushes}P` : ''}</div><div class="lbl">Record</div></div>
      <div class="bt-stat"><div class="val">$${s.wagered.toFixed(0)}</div><div class="lbl">Wagered</div></div>
      <div class="bt-stat"><div class="val" style="color:${roiColor}">${s.pnl >= 0 ? '+' : ''}$${s.pnl.toFixed(2)}</div><div class="lbl">P/L</div></div>
      <div class="bt-stat"><div class="val" style="color:${roiColor}">${s.roi_pct >= 0 ? '+' : ''}${s.roi_pct.toFixed(1)}%</div><div class="lbl">ROI</div></div>
      <div class="bt-stat"><div class="val">${s.open_bets}</div><div class="lbl">Open</div></div>
    </div>`;
}

function renderBetList(bets) {
  const list = document.getElementById("bets-list");
  if (!bets.length) {
    list.innerHTML = `<div class="empty-state">No bets logged yet. Upload a screenshot or add manually.</div>`;
    return;
  }
  bets.sort((a, b) => b.placed_at - a.placed_at);
  list.innerHTML = bets.map(b => {
    const odds = b.american_odds ? (b.american_odds > 0 ? `+${b.american_odds}` : `${b.american_odds}`) : `${b.decimal_odds.toFixed(2)}x`;
    const statusClass = b.status === "won" ? "won" : b.status === "lost" ? "lost" : b.status === "push" ? "push" : "open";
    const settleBtns = b.status === "open" ? `
      <button class="btn btn-sm" onclick="settleBet('${b.id}','won')">Won</button>
      <button class="btn btn-sm btn-danger" onclick="settleBet('${b.id}','lost')">Lost</button>
      <button class="btn btn-sm btn-outline" onclick="settleBet('${b.id}','push')">Push</button>
    ` : `
      <button class="btn btn-sm btn-outline" onclick="settleBet('${b.id}','open')">Reopen</button>
    `;
    return `
      <div class="bet-card status-${statusClass}">
        <div class="bet-head">
          <span class="bet-stake">$${b.stake.toFixed(2)}</span>
          <span class="bet-odds">${odds}</span>
          <span class="bet-sport">${(b.sport || '').toUpperCase()}</span>
          <span class="bet-status">${b.status.toUpperCase()}</span>
          ${b.status !== "open" ? `<span class="bet-returned">→ $${b.returned.toFixed(2)}</span>` : ""}
        </div>
        <div class="bet-legs">
          ${b.legs.map(l => `<div class="bet-leg-row"><span class="bet-leg-status ${l.status}">●</span>${l.description || `${l.player} · ${l.side} ${l.line} ${l.stat}`}</div>`).join("")}
        </div>
        <div class="bet-actions">
          ${settleBtns}
          <button class="btn btn-sm btn-danger" onclick="deleteBet('${b.id}')">Delete</button>
        </div>
      </div>`;
  }).join("");
}

async function settleBet(id, status) {
  try {
    const r = await fetch(`/api/bets/${id}/settle`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const d = await r.json();
    if (d.error) toast(d.error, "error");
    else toast(`Bet ${status}`, "success");
    loadBets();
  } catch (e) { toast("Settle failed", "error"); }
}

async function deleteBet(id) {
  if (!confirm("Delete this bet?")) return;
  try {
    await fetch(`/api/bets/${id}`, { method: "DELETE" });
    toast("Deleted");
    loadBets();
  } catch (e) { toast("Delete failed", "error"); }
}

/* ===== Bets: upload ===== */
document.getElementById("bet-screenshot").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("image", file);
  toast("Parsing screenshot with AI...");
  try {
    const r = await fetch("/api/bets/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (d.error) { toast(d.error, "error"); return; }
    toast("Bet logged from screenshot", "success");
    loadBets();
  } catch (err) {
    toast("Upload failed", "error");
  } finally {
    e.target.value = "";
  }
});

/* ===== Bets: manual entry ===== */
document.getElementById("manual-bet-btn").addEventListener("click", () => {
  document.getElementById("manual-form").classList.toggle("hidden");
});
document.getElementById("m-cancel").addEventListener("click", () => {
  document.getElementById("manual-form").classList.add("hidden");
});
document.getElementById("m-save").addEventListener("click", async () => {
  const sport = document.getElementById("m-sport").value;
  const stake = parseFloat(document.getElementById("m-stake").value || "0");
  const odds = parseInt(document.getElementById("m-odds").value || "0", 10);
  const legsText = document.getElementById("m-legs").value.trim();
  if (!stake || !legsText) { toast("Stake and at least one leg required", "error"); return; }
  const legs = legsText.split("\n").map(line => ({
    description: line.trim(),
    status: "open",
  })).filter(l => l.description);
  try {
    const r = await fetch("/api/bets", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sport, book: "bet365", stake, american_odds: odds, legs }),
    });
    const d = await r.json();
    if (d.error) { toast(d.error, "error"); return; }
    toast("Bet logged", "success");
    document.getElementById("manual-form").classList.add("hidden");
    document.getElementById("m-legs").value = "";
    loadBets();
  } catch (e) { toast("Save failed", "error"); }
});

/* ===== Status pill ===== */
async function loadStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    const pill = document.getElementById("status-pill");
    pill.className = s.vision_enabled ? "live" : "mock";
    pill.textContent = s.vision_enabled ? "AI vision ON" : "AI vision OFF";
  } catch (_) {}
}

/* ===== Init ===== */
loadStatus();
loadGames();
setInterval(() => {
  if (!document.getElementById("halftime-panel").classList.contains("hidden") && !currentGameId) {
    loadGames();
  }
}, 60000);
