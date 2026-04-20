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
    allCards = data.cards;
    applyFilters();
  } catch (e) {
    board.innerHTML = `<div class="loading"><span class="loading-text">Failed to load. Tap to retry.</span></div>`;
    board.querySelector(".loading").onclick = () => load(sport, phase);
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

async function loadPlayer(name, sport) {
  searchResults.style.display = "none";
  searchInput.value = name;
  showPanel("board");
  document.getElementById("board-title").textContent = name;
  document.getElementById("card-count").textContent = "";
  board.innerHTML = `<div class="loading"><div class="spinner"></div><span class="loading-text">Loading ${name}...</span></div>`;
  try {
    const r = await fetch(`/api/player/${encodeURIComponent(name)}?sport=${sport}`);
    const data = await r.json();
    if (data.error) { board.innerHTML = `<div class="loading"><span class="loading-text">${data.error}</span></div>`; return; }
    board.innerHTML = `
      <div class="card has-edge" style="grid-column:1/-1">
        <div class="card-head">
          <div class="card-player">
            <div class="player-avatar">${initials(data.player)}</div>
            <div class="player-info">
              <h3>${data.player}</h3>
              <div class="player-meta">${sport.toUpperCase()} · All Markets</div>
            </div>
          </div>
        </div>
        <div class="card-stats" style="grid-template-columns:1fr 1fr">
          ${data.props.map(p => `
            <div class="stat-item">
              <span class="label">${p.stat.replace(/_/g,' ')}</span>
              <span class="value">${p.mean} ± ${p.sd}</span>
            </div>
          `).join("")}
        </div>
      </div>`;
  } catch (e) {
    board.innerHTML = `<div class="loading"><span class="loading-text">Failed to load player</span></div>`;
  }
}

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
load("nba", "pregame");
