/* ===== PropEdge — Professional Sports Research App ===== */

const board = document.getElementById("board");
const buttons = document.querySelectorAll("#main-nav button");
const parlayLegs = [];
let allCards = [];
let currentSport = "nba";
let currentPhase = "pregame";

/* ===== Toast system ===== */
function toast(msg, type = "default") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; setTimeout(() => el.remove(), 300); }, 2500);
}

/* ===== Board loading ===== */
async function load(sport, phase) {
  currentSport = sport;
  currentPhase = phase;
  showPanel("board");
  const label = `${sport.toUpperCase()} ${phase === "live" ? "Live" : "Pregame"} Props`;
  document.getElementById("board-title").textContent = label;
  board.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Loading ${label}...</span></div>`;
  try {
    const r = await fetch(`/api/board?sport=${sport}&phase=${phase}`);
    const data = await r.json();
    if (data.gated) {
      allCards = [];
      document.getElementById("card-count").textContent = "";
      board.innerHTML = `
        <div class="gated-state">
          <div class="gated-icon">&#9202;</div>
          <div class="gated-title">${label} is gated</div>
          <div class="gated-msg">${data.message || "Not available right now."}</div>
        </div>`;
      return;
    }
    if (data.error) {
      allCards = [];
      board.innerHTML = `<div class="loading"><span class="loading-text">${data.error}</span></div>`;
      return;
    }
    allCards = data.cards || [];
    applyFilters();
  } catch (e) {
    board.innerHTML = `<div class="loading"><span class="loading-text">Failed to load. Tap to retry.</span></div>`;
    board.querySelector(".loading").onclick = () => load(sport, phase);
  }
}

/* ===== NBA Live availability polling =====
 * NBA Live research is only offered during halftime of a playoff game.
 * The tab stays hidden until the server reports a qualifying game.
 */
async function checkNbaLiveAvailability() {
  try {
    const r = await fetch("/api/nba/live_availability");
    const d = await r.json();
    const btn = document.getElementById("nav-nba-live");
    if (!btn) return;
    btn.classList.toggle("hidden", !d.available);
    if (d.available && d.games && d.games.length) {
      const g = d.games[0];
      btn.title = `${g.away} @ ${g.home} — ${g.series} · Halftime`;
    } else {
      btn.title = "NBA Live opens at halftime of playoff games";
    }
  } catch (_) {
    // leave hidden on network failure
  }
}

/* ===== Filtering & sorting ===== */
function applyFilters() {
  const minEdge = parseFloat(document.getElementById("filter-edge").value) || 0;
  const show = document.getElementById("filter-show").value;
  const sort = document.getElementById("filter-sort").value;
  let cards = [...allCards];
  if (show === "plays") cards = cards.filter(c => c.edge);
  if (minEdge > 0) cards = cards.filter(c => c.edge && c.edge.edge_pct >= minEdge);
  if (sort === "prob") cards.sort((a, b) => (b.simulation.p_over) - (a.simulation.p_over));
  else if (sort === "name") cards.sort((a, b) => a.player.localeCompare(b.player));
  else cards.sort((a, b) => ((b.edge?.edge_pct) || -999) - ((a.edge?.edge_pct) || -999));
  document.getElementById("card-count").textContent = `${cards.length} props`;
  renderCards(cards);
}

function initials(name) {
  return name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

function edgeLevel(pct) {
  if (pct >= 8) return "high";
  if (pct >= 4) return "mid";
  return "low";
}

/* ===== Card rendering ===== */
function renderCards(cards) {
  if (!cards.length) {
    board.innerHTML = `<div class="loading"><span class="loading-text">No props match your filters</span></div>`;
    return;
  }
  board.innerHTML = cards.map((c, i) => {
    const hasEdge = !!c.edge;
    const pOver = (c.simulation.p_over * 100);
    const pUnder = (c.simulation.p_under * 100);
    const fairOver = (c.fair.p_over * 100);
    const badge = hasEdge
      ? (c.edge.edge_pct >= 5 ? "play" : "lean")
      : "pass";
    const badgeText = hasEdge
      ? (c.edge.edge_pct >= 5 ? "PLAY" : "LEAN")
      : "PASS";

    return `
    <div class="card ${hasEdge ? 'has-edge' : 'no-edge'}" data-idx="${i}">
      <div class="card-head">
        <div class="card-player">
          <div class="player-avatar">${initials(c.player)}</div>
          <div class="player-info">
            <h3>${c.player}</h3>
            <div class="player-meta">${c.team || ''} · ${c.sport.toUpperCase()} · ${c.book}</div>
          </div>
        </div>
        <span class="card-badge badge-${badge}">${badgeText}</span>
      </div>

      <div class="stat-line">
        <span class="stat-name">${c.stat.replace(/_/g,' ')}</span>
        <span class="stat-line-val">${c.line}</span>
        <div class="stat-odds">
          <span>O ${c.odds.over > 0 ? '+' : ''}${c.odds.over}</span>
          <span>U ${c.odds.under > 0 ? '+' : ''}${c.odds.under}</span>
        </div>
      </div>

      <div class="prob-row">
        <span class="prob-label">Model</span>
        <div class="prob-bar-track"><div class="prob-bar-fill over" style="width:${pOver}%"></div></div>
        <span class="prob-val">${pOver.toFixed(1)}%</span>
      </div>
      <div class="prob-row">
        <span class="prob-label">Fair Line</span>
        <div class="prob-bar-track"><div class="prob-bar-fill fair" style="width:${fairOver}%"></div></div>
        <span class="prob-val">${fairOver.toFixed(1)}%</span>
      </div>

      <div class="card-stats">
        <div class="stat-item"><span class="label">Projected</span><span class="value">${c.projection.mean} ± ${c.projection.sd}</span></div>
        <div class="stat-item"><span class="label">Book Hold</span><span class="value">${c.odds.hold_pct}%</span></div>
        <div class="stat-item"><span class="label">p10/p50/p90</span><span class="value">${c.simulation.p10}/${c.simulation.p50}/${c.simulation.p90}</span></div>
        <div class="stat-item"><span class="label">Trials</span><span class="value">${c.simulation.trials.toLocaleString()}</span></div>
      </div>

      ${hasEdge ? `
      <div class="edge-strip positive">
        <div class="edge-info">
          <span class="edge-pct ${edgeLevel(c.edge.edge_pct)}">${c.edge.edge_pct}%</span>
          <span class="edge-label">${c.edge.side} edge</span>
        </div>
        <span class="edge-stake">Stake ${c.edge.recommended_stake_pct}%</span>
      </div>
      ` : `
      <div class="edge-strip negative">
        <span class="edge-label">No actionable edge</span>
      </div>
      `}

      <div class="card-actions">
        ${hasEdge ? `<button class="btn btn-sm btn-parlay" onclick="addToParlay(${i})">+ Parlay</button>` : ''}
      </div>
    </div>`;
  }).join("");
}

/* ===== Filters ===== */
document.getElementById("filter-edge").addEventListener("input", applyFilters);
document.getElementById("filter-show").addEventListener("change", applyFilters);
document.getElementById("filter-sort").addEventListener("change", applyFilters);

/* ===== Search ===== */
const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
let searchTimeout;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimeout);
  const q = searchInput.value.trim();
  if (q.length < 2) { searchResults.style.display = "none"; return; }
  searchTimeout = setTimeout(async () => {
    const sport = document.getElementById("search-sport").value;
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&sport=${sport}`);
    const data = await r.json();
    if (!data.results.length) { searchResults.style.display = "none"; return; }
    searchResults.innerHTML = data.results.map(name =>
      `<div class="sr-item" onclick="loadPlayer('${name.replace(/'/g,"\\'")}','${sport}')">${name}</div>`
    ).join("");
    searchResults.style.display = "block";
  }, 300);
});

document.addEventListener("click", e => {
  if (!e.target.closest("#search-wrap")) searchResults.style.display = "none";
});

/* ===== Player graph modal (PropsMadness-style) ===== */
const NBA_STAT_TABS = [
  {key: "points",      label: "Points"},
  {key: "assists",     label: "Assists"},
  {key: "rebounds",    label: "Rebounds"},
  {key: "threes_made", label: "Threes"},
  {key: "pa",          label: "Pts+Ast"},
  {key: "pr",          label: "Pts+Reb"},
  {key: "pra",         label: "P+R+A"},
  {key: "steals",      label: "Steals"},
  {key: "blocks",      label: "Blocks"},
];

let playerGraphState = {name: null, sport: null, stat: "points", tab: "graph"};

async function loadPlayer(name, sport) {
  searchResults.style.display = "none";
  searchInput.value = "";
  if (sport !== "nba") {
    toast("Graph view is NBA-only for now", "error");
    return;
  }
  playerGraphState = {name, sport, stat: "points", tab: "graph"};
  renderPlayerGraph();
}

async function renderPlayerGraph() {
  const {name, stat, tab} = playerGraphState;
  const modal = ensurePlayerModal();
  const body = modal.querySelector(".pg-body");
  body.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Loading ${name}...</span></div>`;
  modal.classList.remove("hidden");

  try {
    // Every tab needs the gamelog for the shared header (name/team/line) — fetch once.
    const gR = await fetch(`/api/player/${encodeURIComponent(name)}/gamelog?stat=${encodeURIComponent(stat)}`);
    const g = await gR.json();
    if (g.error) { body.innerHTML = `<div class="empty-state">${g.error}</div>`; return; }

    let contentHtml = "";
    if (tab === "shooting") {
      const sR = await fetch(`/api/player/${encodeURIComponent(name)}/shooting`);
      const s = await sR.json();
      contentHtml = s.error ? `<div class="empty-state">${s.error}</div>` : buildShootingHtml(s);
    } else if (tab === "similar") {
      const sR = await fetch(`/api/player/${encodeURIComponent(name)}/similar`);
      const s = await sR.json();
      contentHtml = s.error ? `<div class="empty-state">${s.error}</div>` : buildSimilarHtml(s);
    } else if (tab === "types") {
      const tR = await fetch(`/api/player/${encodeURIComponent(name)}/types`);
      const t = await tR.json();
      contentHtml = t.error ? `<div class="empty-state">${t.error}</div>` : buildTypesHtml(t);
    } else {
      contentHtml = buildGraphContentHtml(g);
    }

    body.innerHTML = buildPlayerGraphHtml(g, contentHtml);
  } catch (e) {
    body.innerHTML = `<div class="empty-state">Failed to load player</div>`;
  }
}

function ensurePlayerModal() {
  let modal = document.getElementById("player-graph-modal");
  if (modal) return modal;
  modal = document.createElement("div");
  modal.id = "player-graph-modal";
  modal.className = "pg-modal hidden";
  modal.innerHTML = `
    <div class="pg-overlay"></div>
    <div class="pg-dialog">
      <button class="pg-close" aria-label="Close">&times;</button>
      <div class="pg-stat-tabs">
        ${NBA_STAT_TABS.map(t =>
          `<button data-stat="${t.key}" class="pg-stat-tab">${t.label}</button>`
        ).join("")}
      </div>
      <div class="pg-body"></div>
    </div>`;
  document.body.appendChild(modal);
  modal.querySelector(".pg-close").addEventListener("click", closePlayerGraph);
  modal.querySelector(".pg-overlay").addEventListener("click", closePlayerGraph);
  modal.addEventListener("click", (e) => {
    const statBtn = e.target.closest(".pg-stat-tab");
    if (statBtn) {
      playerGraphState.stat = statBtn.dataset.stat;
      renderPlayerGraph();
      return;
    }
    const subBtn = e.target.closest(".pg-subtab");
    if (subBtn && !subBtn.disabled) {
      playerGraphState.tab = subBtn.dataset.tab;
      renderPlayerGraph();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePlayerGraph();
  });
  return modal;
}

function closePlayerGraph() {
  const modal = document.getElementById("player-graph-modal");
  if (modal) modal.classList.add("hidden");
}

const PG_SUBTABS = [
  {key: "graph",    label: "Graph"},
  {key: "shooting", label: "Shooting"},
  {key: "similar",  label: "Similar"},
  {key: "types",    label: "Types"},
];

async function loadTeammates(player, stat) {
  try {
    const r = await fetch(`/api/player/${encodeURIComponent(player)}/teammates?stat=${encodeURIComponent(stat)}&n=6`);
    const d = await r.json();
    const host = document.getElementById("pg-suggested");
    if (!host || !d.teammates || !d.teammates.length) return;
    host.innerHTML = d.teammates.map(m => `
      <button class="pg-sugg-item" onclick="loadPlayer('${m.name.replace(/'/g,"\\'")}','nba')">
        <span class="pg-sugg-avatar">${initials(m.name)}</span>
        <span class="pg-sugg-name">${m.name}</span>
        <span class="pg-sugg-mean">${m.mean}</span>
      </button>
    `).join("");
  } catch (_) { /* non-fatal */ }
}

/* ===== Sub-tab (Graph / Shooting / Similar / Types) content renderers ===== */

function buildShootingHtml(s) {
  const zones = s.zones.map(z => `
    <div class="pg-zone">
      <div class="pg-zone-head">
        <span class="pg-zone-name">${z.name}</span>
        <span class="pg-zone-pct">${z.pct}%</span>
      </div>
      <div class="pg-zone-bar">
        <div class="pg-zone-fill" style="width:${z.share}%"></div>
      </div>
      <div class="pg-zone-share">${z.share}% of shots</div>
    </div>
  `).join("");
  return `
    <div class="pg-shoot-grid">
      <div class="pg-shoot-stat"><span class="lbl">FG</span><span class="val">${s.fg.made}/${s.fg.att}</span><span class="pct">${s.fg.pct}%</span></div>
      <div class="pg-shoot-stat"><span class="lbl">3PT</span><span class="val">${s.three.made}/${s.three.att}</span><span class="pct">${s.three.pct}%</span></div>
      <div class="pg-shoot-stat"><span class="lbl">FT</span><span class="val">${s.ft.made}/${s.ft.att}</span><span class="pct">${s.ft.pct}%</span></div>
      <div class="pg-shoot-stat"><span class="lbl">TS%</span><span class="val">${s.ts_pct}%</span><span class="pct">eFG ${s.efg_pct}%</span></div>
    </div>
    <div class="pg-section-title">Shot Distribution</div>
    <div class="pg-zones">${zones}</div>
    <div class="pg-footer-note">Per-game averages · ${s.minutes} min</div>
  `;
}

function buildSimilarHtml(d) {
  if (!d.similar || !d.similar.length) {
    return `<div class="empty-state">No similar players found</div>`;
  }
  const rows = d.similar.map(s => {
    const tint = TEAM_TINT[s.team] || "#5a6270";
    return `
      <button class="pg-similar-row" onclick="loadPlayer('${s.name.replace(/'/g,"\\'")}','nba')">
        <span class="pg-sim-avatar" style="background:${tint}">${initials(s.name)}</span>
        <span class="pg-sim-info">
          <span class="pg-sim-name">${s.name}</span>
          <span class="pg-sim-team">${s.team} · ${s.team_name}</span>
        </span>
        <span class="pg-sim-line"><span>${s.points}</span><span class="pg-sim-sub">PTS</span></span>
        <span class="pg-sim-line"><span>${s.rebounds}</span><span class="pg-sim-sub">REB</span></span>
        <span class="pg-sim-line"><span>${s.assists}</span><span class="pg-sim-sub">AST</span></span>
        <span class="pg-sim-match">${s.similarity}%</span>
      </button>`;
  }).join("");
  return `
    <div class="pg-section-title">Most similar players by stat profile</div>
    <div class="pg-similar-list">${rows}</div>
  `;
}

function buildTypesHtml(d) {
  if (!d.types || !d.types.length) {
    return `<div class="empty-state">No prop types available</div>`;
  }
  const rows = d.types.map(t => {
    const hitColor = t.hit_rate >= 0.6 ? "var(--green)" : t.hit_rate >= 0.4 ? "var(--yellow)" : "var(--red)";
    const hitPct = (t.hit_rate * 100).toFixed(0);
    return `
      <button class="pg-type-row" onclick="switchToStat('${t.stat}')">
        <span class="pg-type-name">${prettyStat(t.stat)}</span>
        <span class="pg-type-line">${t.line}</span>
        <span class="pg-type-avg">avg ${t.graph_avg}</span>
        <span class="pg-type-hit" style="color:${hitColor}">${hitPct}% (${t.hits}/${t.games})</span>
        <span class="pg-type-hitbar"><span class="pg-type-hitfill" style="width:${hitPct}%;background:${hitColor}"></span></span>
      </button>`;
  }).join("");
  return `
    <div class="pg-section-title">Hit rate by prop type (L12)</div>
    <div class="pg-types-list">${rows}</div>
  `;
}

function switchToStat(stat) {
  // The Types tab exposes rows you can click to jump to that stat's Graph.
  playerGraphState.stat = stat;
  playerGraphState.tab = "graph";
  renderPlayerGraph();
}

function buildGraphContentHtml(d) {
  const values = d.games.map(g => g.value).filter(v => v !== null);
  const maxVal = Math.max(d.line * 1.4, ...values, 1);
  const linePct = (d.line / maxVal) * 100;
  const avgColor = d.graph_avg >= d.line ? "var(--green)" : "var(--red)";
  const hitColor = d.hit_rate >= 0.5 ? "var(--green)" : "var(--red)";

  const bars = d.games.map(g => {
    const pending = g.value === null;
    const hit = !pending && g.value > d.line;
    const barPct = pending ? 100 : Math.max(2, (g.value / maxVal) * 100);
    const barClass = pending ? "pg-bar-pending" : (hit ? "pg-bar-hit" : "pg-bar-miss");
    const valLabel = pending ? "?" : (Number.isInteger(g.value) ? g.value : g.value.toFixed(1));
    const marker = g.is_playoff ? "<span class=\"pg-playoff-dot\" title=\"Playoff game\"></span>" : "";
    const atSymbol = g.home ? "vs" : "@";
    return `
      <div class="pg-bar-col" title="${atSymbol} ${g.opponent_name} · ${g.date}${pending ? ' · not played' : ` · ${valLabel}`}">
        <div class="pg-bar-wrap">
          <div class="pg-bar ${barClass}" style="height:${barPct}%">
            <span class="pg-bar-label">${valLabel}</span>
          </div>
        </div>
        <div class="pg-bar-foot">
          <div class="pg-bar-opp">${logoEmoji(g.opponent)}<span class="pg-bar-opp-abbr">${g.opponent}</span></div>
          <div class="pg-bar-date">${g.date}</div>
          ${marker}
        </div>
      </div>`;
  }).join("");

  return `
    <div class="pg-summary">
      <div class="pg-sum-item">
        <span class="pg-sum-label">SEASON AVG</span>
        <span class="pg-sum-value" style="color:${d.season_avg >= d.line ? 'var(--green)' : 'var(--red)'}">${d.season_avg}</span>
      </div>
      <div class="pg-sum-item">
        <span class="pg-sum-label">GRAPH AVG</span>
        <span class="pg-sum-value" style="color:${avgColor}">${d.graph_avg}</span>
      </div>
      <div class="pg-sum-item">
        <span class="pg-sum-label">HIT RATE</span>
        <span class="pg-sum-value" style="color:${hitColor}">${(d.hit_rate * 100).toFixed(1)}% (${d.hits}/${d.games_played})</span>
      </div>
    </div>
    <div class="pg-chart-wrap">
      <div class="pg-chart">
        <div class="pg-line" style="bottom:${linePct}%">
          <span class="pg-line-pill">${d.line}</span>
        </div>
        <div class="pg-bars">${bars}</div>
      </div>
    </div>
    <div class="pg-chip-row">
      <div class="pg-chip">
        <span class="pg-chip-label">LINE</span>
        <span class="pg-chip-val">${d.line}</span>
      </div>
      <div class="pg-chip">
        <span class="pg-chip-label">L${d.games_played}</span>
        <span class="pg-chip-val">${d.graph_avg}</span>
      </div>
      <div class="pg-chip">
        <span class="pg-chip-label">HIT%</span>
        <span class="pg-chip-val" style="color:${hitColor}">${(d.hit_rate * 100).toFixed(0)}%</span>
      </div>
    </div>
  `;
}

function buildPlayerGraphHtml(d, contentHtml) {
  // Highlight current stat tab, current sub-tab, and kick off teammate fetch.
  const activeTab = playerGraphState.tab || "graph";
  setTimeout(() => {
    document.querySelectorAll(".pg-stat-tab").forEach(b =>
      b.classList.toggle("active", b.dataset.stat === d.stat));
    document.querySelectorAll(".pg-subtab").forEach(b =>
      b.classList.toggle("active", b.dataset.tab === activeTab));
    loadTeammates(d.player, d.stat);
  }, 0);

  const statLabel = prettyStat(d.stat);

  const subtabs = PG_SUBTABS.map(t =>
    `<button data-tab="${t.key}" class="pg-subtab ${t.key === activeTab ? 'active' : ''}">${t.label}</button>`
  ).join("");

  const playoffStrip = d.is_playoff_team
    ? `<div class="pg-playoff-strip">PLAYOFFS · ${d.playoff_series}</div>`
    : "";

  return `
    <div class="pg-header">
      <div class="pg-avatar" style="background:${TEAM_TINT[d.team] || 'var(--bg-card)'}">${initials(d.player)}</div>
      <div class="pg-name-wrap">
        <div class="pg-name">${d.player}</div>
        <div class="pg-team">${d.team} · ${d.team_name}</div>
      </div>
      <div class="pg-line-box">
        <span class="pg-line-val">${d.line}</span>
        <span class="pg-line-label">${statLabel} line</span>
      </div>
    </div>
    ${playoffStrip}
    <div class="pg-subtabs">${subtabs}</div>
    <div class="pg-tab-content">${contentHtml}</div>
    <div class="pg-suggested-wrap">
      <div class="pg-suggested-title">Suggested · ${d.team} teammates</div>
      <div id="pg-suggested" class="pg-suggested"></div>
    </div>
    <div class="pg-footer-note">Season 25/26 · ${d.games_played} recent games</div>
  `;
}

function prettyStat(key) {
  const t = NBA_STAT_TABS.find(x => x.key === key);
  return t ? t.label : key.replace(/_/g, " ");
}

function logoEmoji(team) {
  // Tiny colored block stands in for a team logo — browsers won't have NBA
  // logos bundled, so we use the team-color tint + initials below the bar.
  const color = TEAM_TINT[team] || "#5a6270";
  return `<span class="pg-logo" style="background:${color}"></span>`;
}

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

/* ===== Parlay builder ===== */
function addToParlay(idx) {
  const c = allCards[idx];
  if (!c.edge) return;
  if (parlayLegs.some(l => l.player === c.player && l.stat === c.stat)) {
    toast("Already in parlay", "error");
    return;
  }
  parlayLegs.push({
    player: c.player, stat: c.stat, side: c.edge.side,
    model_prob: c.edge.model_prob, game_id: c.player,
    sport: c.sport, odds: c.edge.side === "OVER" ? c.odds.over : c.odds.under,
  });
  updateParlayCount();
  toast(`${c.player} ${c.stat} ${c.edge.side} added`, "success");
}

function updateParlayCount() {
  document.getElementById("parlay-count").textContent = `${parlayLegs.length} leg${parlayLegs.length !== 1 ? 's' : ''}`;
}

function renderParlayLegs() {
  const el = document.getElementById("parlay-legs");
  if (!parlayLegs.length) {
    el.innerHTML = '<div class="empty-state">Add picks from the board to build a parlay</div>';
    return;
  }
  el.innerHTML = parlayLegs.map((l, i) => `
    <div class="parlay-leg">
      <div class="leg-info">
        <div class="leg-player">${l.player}</div>
        <div class="leg-detail">${l.stat.replace(/_/g,' ')} · ${l.side} · ${l.sport.toUpperCase()}</div>
      </div>
      <span class="leg-prob" style="color:var(--accent)">${(l.model_prob*100).toFixed(1)}%</span>
      <button class="btn btn-sm btn-danger" onclick="removeLeg(${i})">Remove</button>
    </div>
  `).join("");
}

function removeLeg(i) {
  parlayLegs.splice(i, 1);
  renderParlayLegs();
  updateParlayCount();
  toast("Leg removed");
}

document.getElementById("clear-parlay").addEventListener("click", () => {
  parlayLegs.length = 0;
  renderParlayLegs();
  updateParlayCount();
  document.getElementById("parlay-result").innerHTML = "";
  toast("Parlay cleared");
});

document.getElementById("price-parlay").addEventListener("click", async () => {
  if (parlayLegs.length < 2) { toast("Add at least 2 legs", "error"); return; }
  const btn = document.getElementById("price-parlay");
  btn.textContent = "Pricing...";
  btn.disabled = true;
  try {
    const r = await fetch("/api/parlay", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(parlayLegs),
    });
    const data = await r.json();
    if (data.error) { toast(data.error, "error"); return; }
    const positive = data.is_positive_ev;
    document.getElementById("parlay-result").innerHTML = `
      <div class="parlay-verdict ${positive ? 'positive' : 'negative'}">
        ${positive ? '+EV PLAY' : 'NEGATIVE EV'}
      </div>
      <div class="parlay-grid">
        <div class="parlay-stat">
          <span class="label">Naive Probability</span>
          <span class="value">${(data.naive_prob*100).toFixed(2)}%</span>
        </div>
        <div class="parlay-stat">
          <span class="label">Correlated Probability</span>
          <span class="value">${(data.correlated_prob*100).toFixed(2)}%</span>
        </div>
        <div class="parlay-stat">
          <span class="label">Combined Odds</span>
          <span class="value">${data.combined_odds.toFixed(2)}x</span>
        </div>
        <div class="parlay-stat">
          <span class="label">Correlation Adj.</span>
          <span class="value">${(data.correlation_penalty*100).toFixed(1)}%</span>
        </div>
        <div class="parlay-stat">
          <span class="label">EV per $1</span>
          <span class="value" style="color:${positive ? 'var(--green)' : 'var(--red)'}">${data.ev_per_dollar > 0 ? '+' : ''}$${data.ev_per_dollar.toFixed(3)}</span>
        </div>
        <div class="parlay-stat">
          <span class="label">Legs</span>
          <span class="value">${data.legs}</span>
        </div>
      </div>`;
  } catch (e) {
    toast("Pricing failed", "error");
  } finally {
    btn.textContent = "Price Parlay";
    btn.disabled = false;
  }
});

/* ===== Backtest ===== */
document.getElementById("run-backtest").addEventListener("click", async () => {
  const n = document.getElementById("bt-games").value;
  const edge = document.getElementById("bt-edge").value;
  const el = document.getElementById("backtest-result");
  const btn = document.getElementById("run-backtest");
  btn.textContent = "Running...";
  btn.disabled = true;
  el.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Simulating ${n} games...</span></div>`;
  try {
    const r = await fetch(`/api/backtest?n_games=${n}&min_edge=${edge}`);
    const d = await r.json();
    const roiColor = d.flat_roi_pct >= 0 ? "var(--green)" : "var(--red)";
    const kellyColor = d.kelly_roi_pct >= 0 ? "var(--green)" : "var(--red)";
    el.innerHTML = `
      <div class="bt-summary">
        <div class="bt-stat"><div class="val">${d.total_games}</div><div class="lbl">Games</div></div>
        <div class="bt-stat"><div class="val">${d.picks_made}</div><div class="lbl">Picks</div></div>
        <div class="bt-stat"><div class="val">${d.wins}W-${d.losses}L</div><div class="lbl">Record</div></div>
        <div class="bt-stat"><div class="val">${(d.win_rate*100).toFixed(1)}%</div><div class="lbl">Win Rate</div></div>
        <div class="bt-stat"><div class="val" style="color:${roiColor}">${d.flat_roi_pct > 0 ? '+' : ''}${d.flat_roi_pct}%</div><div class="lbl">Flat ROI</div></div>
        <div class="bt-stat"><div class="val" style="color:${kellyColor}">${d.kelly_roi_pct > 0 ? '+' : ''}${d.kelly_roi_pct}%</div><div class="lbl">Kelly ROI</div></div>
      </div>
      <div class="bt-section-title">By Sport</div>
      <div class="bt-rows">${Object.entries(d.by_sport).map(([k,v]) =>
        `<div class="bt-row"><span class="bt-key">${k.toUpperCase()}</span><span class="bt-val">${v.w}W-${v.l}L (${(v.wr*100).toFixed(0)}%) · $${v.pnl.toFixed(0)}</span></div>`
      ).join("")}</div>
      <div class="bt-section-title">By Stat</div>
      <div class="bt-rows">${Object.entries(d.by_stat).map(([k,v]) =>
        `<div class="bt-row"><span class="bt-key">${k.replace(/_/g,' ')}</span><span class="bt-val">${v.w}W-${v.l}L (${(v.wr*100).toFixed(0)}%)</span></div>`
      ).join("")}</div>`;
  } catch (e) {
    el.innerHTML = `<div class="loading"><span class="loading-text">Backtest failed</span></div>`;
  } finally {
    btn.textContent = "Run Backtest";
    btn.disabled = false;
  }
});

/* ===== Live scores ===== */
let scoresInterval;
async function loadScores() {
  const el = document.getElementById("scores-content");
  el.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Loading scores...</span></div>`;
  try {
    const [nba, mlb] = await Promise.all([
      fetch("/api/live/nba").then(r => r.json()).catch(() => ({games:[]})),
      fetch("/api/live/mlb").then(r => r.json()).catch(() => ({games:[]})),
    ]);
    let html = '<div class="scores-section"><h3>&#127936; NBA</h3>';
    if (!nba.games.length) html += '<div class="empty-state">No NBA games today</div>';
    for (const g of nba.games) {
      const st = g.is_final ? "FINAL" : g.is_halftime ? "HALF" : `Q${g.quarter} ${g.clock}`;
      const cls = g.is_final ? "final" : (!g.is_final && !g.is_halftime ? "live" : "");
      html += `<div class="score-card"><span class="score-teams">${g.away} @ ${g.home}</span><span class="score-val">${g.score}</span><span class="score-status ${cls}">${st}</span></div>`;
    }
    html += '</div><div class="scores-section"><h3>&#9918; MLB</h3>';
    if (!mlb.games.length) html += '<div class="empty-state">No MLB games today</div>';
    for (const g of mlb.games) {
      html += `<div class="score-card"><span class="score-teams">${g.away || '?'} @ ${g.home || '?'}</span><span class="score-status">${g.status}</span></div>`;
    }
    html += '</div>';
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = `<div class="loading"><span class="loading-text">Failed to load scores</span></div>`;
  }
}

/* ===== Panel switching ===== */
function showPanel(name) {
  board.classList.toggle("hidden", name !== "board");
  document.getElementById("toolbar").classList.toggle("hidden", name !== "board");
  document.getElementById("parlay-panel").classList.toggle("hidden", name !== "parlay");
  document.getElementById("backtest-panel").classList.toggle("hidden", name !== "backtest");
  document.getElementById("scores-panel").classList.toggle("hidden", name !== "scores");
  clearInterval(scoresInterval);
  if (name === "scores") scoresInterval = setInterval(loadScores, 60000);
}

buttons.forEach(b => b.addEventListener("click", () => {
  buttons.forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  if (b.dataset.tab === "parlay") { showPanel("parlay"); renderParlayLegs(); }
  else if (b.dataset.tab === "backtest") { showPanel("backtest"); }
  else if (b.dataset.tab === "scores") { showPanel("scores"); loadScores(); }
  else { load(b.dataset.sport, b.dataset.phase); }
}));

/* ===== Status badge ===== */
async function loadStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    const pill = document.getElementById("status-pill");
    const isLive = s.odds_provider === "live";
    pill.className = isLive ? "live" : "mock";
    pill.id = "status-pill";
    pill.textContent = isLive ? `LIVE · ${s.nba_players + s.mlb_players} players` : `DEMO · ${s.nba_players + s.mlb_players} players`;
  } catch (_) {}
}

/* ===== Init ===== */
loadStatus();
checkNbaLiveAvailability();
setInterval(checkNbaLiveAvailability, 60000);
load("nba", "pregame");
