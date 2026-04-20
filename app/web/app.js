/* ---- State ---- */
const board = document.getElementById("board");
const buttons = document.querySelectorAll("#main-nav button");
const parlayLegs = [];
let allCards = [];
let currentSport = "nba";
let currentPhase = "pregame";

/* ---- Toast (replaces alert) ---- */
function toast(msg, duration = 2500) {
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), duration);
}

/* ---- Board ---- */
async function load(sport, phase) {
  currentSport = sport;
  currentPhase = phase;
  showPanel("board");
  board.innerHTML = `<div class="loading"><div class="spinner"></div>Loading ${sport.toUpperCase()} ${phase}...</div>`;
  try {
    const r = await fetch(`/api/board?sport=${sport}&phase=${phase}`);
    const data = await r.json();
    allCards = data.cards;
    applyFilters();
  } catch (e) {
    board.innerHTML = `<div class="card">Failed to load. <span class="refresh-hint" onclick="load('${sport}','${phase}')">Tap to retry</span></div>`;
  }
}

function applyFilters() {
  const minEdge = parseFloat(document.getElementById("filter-edge").value) || 0;
  const show = document.getElementById("filter-show").value;
  let cards = allCards;
  if (show === "plays") cards = cards.filter(c => c.edge);
  if (minEdge > 0) cards = cards.filter(c => c.edge && c.edge.edge_pct >= minEdge);
  renderCards(cards);
}

function edgeClass(pct) {
  if (pct >= 8) return "edge-high";
  if (pct >= 4) return "edge-mid";
  return "edge-low";
}

function fmtEdge(edge) {
  if (!edge) return '<div class="verdict pass">NO EDGE - PASS</div>';
  return `<div class="verdict play"><span class="${edgeClass(edge.edge_pct)}">${edge.side} | ${edge.edge_pct}% edge</span> | stake ${edge.recommended_stake_pct}%</div>`;
}

function renderCards(cards) {
  if (!cards.length) {
    board.innerHTML = '<div class="card">No picks match filters.</div>';
    return;
  }
  board.innerHTML = cards.map((c, i) => `
    <div class="card" data-idx="${i}">
      <h2>${c.player} - ${c.stat} ${c.line}</h2>
      <div class="meta">${c.team || ''} | ${c.sport.toUpperCase()} | ${c.phase} | ${c.book}</div>
      <div class="grid">
        <span class="label">Projected</span><span>${c.projection.mean} +/- ${c.projection.sd}</span>
        <span class="label">P(over)</span><span>${(c.simulation.p_over*100).toFixed(1)}%</span>
        <span class="label">Fair P(over)</span><span>${(c.fair.p_over*100).toFixed(1)}%</span>
        <span class="label">Book hold</span><span>${c.odds.hold_pct}%</span>
        <span class="label">p10 / p50 / p90</span><span>${c.simulation.p10} / ${c.simulation.p50} / ${c.simulation.p90}</span>
        <span class="label">Trials</span><span>${c.simulation.trials}</span>
      </div>
      ${fmtEdge(c.edge)}
      <div class="card-actions">
        ${c.edge ? `<button class="btn-sm" onclick="addToParlay(${i})">+ Parlay</button>` : ''}
      </div>
    </div>
  `).join("");
}

/* ---- Filters ---- */
document.getElementById("filter-edge").addEventListener("input", applyFilters);
document.getElementById("filter-show").addEventListener("change", applyFilters);

/* ---- Search ---- */
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
  if (!e.target.closest("#search-bar")) searchResults.style.display = "none";
});

async function loadPlayer(name, sport) {
  searchResults.style.display = "none";
  searchInput.value = name;
  showPanel("board");
  board.innerHTML = `<div class="loading"><div class="spinner"></div>Loading ${name}...</div>`;
  try {
    const r = await fetch(`/api/player/${encodeURIComponent(name)}?sport=${sport}`);
    const data = await r.json();
    if (data.error) { board.innerHTML = `<div class="card">${data.error}</div>`; return; }
    board.innerHTML = `
      <div class="card" style="grid-column: 1 / -1">
        <h2>${data.player} (${sport.toUpperCase()})</h2>
        <div class="grid">
          ${data.props.map(p => `
            <span class="label">${p.stat}</span>
            <span>${p.mean} +/- ${p.sd} (${p.dist})</span>
          `).join("")}
        </div>
      </div>`;
  } catch (e) {
    board.innerHTML = `<div class="card">Failed to load player.</div>`;
  }
}

/* ---- Parlay ---- */
function addToParlay(idx) {
  const c = allCards[idx];
  if (!c.edge) return;
  if (parlayLegs.some(l => l.player === c.player && l.stat === c.stat)) {
    toast("Already in parlay");
    return;
  }
  parlayLegs.push({
    player: c.player, stat: c.stat, side: c.edge.side,
    model_prob: c.edge.model_prob, game_id: c.player,
    sport: c.sport, odds: c.edge.side === "OVER" ? c.odds.over : c.odds.under,
  });
  renderParlayLegs();
  toast(`${c.player} ${c.stat} ${c.edge.side} added (${parlayLegs.length} legs)`);
}

function renderParlayLegs() {
  const el = document.getElementById("parlay-legs");
  if (!parlayLegs.length) {
    el.innerHTML = '<div style="color:var(--muted);font-size:0.85rem;padding:12px 0">No legs added yet. Go to a board and click "+ Parlay" on a card.</div>';
    return;
  }
  el.innerHTML = parlayLegs.map((l, i) => `
    <div class="parlay-leg">
      <span>${l.player} ${l.stat} ${l.side} (${(l.model_prob*100).toFixed(1)}%)</span>
      <button class="btn-sm" onclick="removeLeg(${i})">X</button>
    </div>
  `).join("");
}

function removeLeg(i) {
  parlayLegs.splice(i, 1);
  renderParlayLegs();
  toast("Leg removed");
}

document.getElementById("price-parlay").addEventListener("click", async () => {
  if (parlayLegs.length < 2) { toast("Add at least 2 legs"); return; }
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
    if (data.error) { document.getElementById("parlay-result").textContent = data.error; return; }
    const evColor = data.is_positive_ev ? "var(--good)" : "var(--bad)";
    document.getElementById("parlay-result").innerHTML = `
      <div class="bt-grid">
        <span class="label">Naive prob</span><span>${(data.naive_prob*100).toFixed(2)}%</span>
        <span class="label">Correlated prob</span><span>${(data.correlated_prob*100).toFixed(2)}%</span>
        <span class="label">Combined odds</span><span>${data.combined_odds.toFixed(2)}x</span>
        <span class="label">Correlation penalty</span><span>${(data.correlation_penalty*100).toFixed(1)}%</span>
        <span class="label">EV per $1</span><span style="color:${evColor}">${data.ev_per_dollar > 0 ? '+' : ''}$${data.ev_per_dollar.toFixed(3)}</span>
        <span class="label">Verdict</span><span style="color:${evColor};font-weight:700">${data.is_positive_ev ? '+EV PLAY' : 'NEGATIVE EV'}</span>
      </div>`;
  } catch (e) {
    document.getElementById("parlay-result").textContent = "Pricing failed.";
  } finally {
    btn.textContent = "Price Parlay";
    btn.disabled = false;
  }
});

/* ---- Backtest ---- */
document.getElementById("run-backtest").addEventListener("click", async () => {
  const n = document.getElementById("bt-games").value;
  const edge = document.getElementById("bt-edge").value;
  const el = document.getElementById("backtest-result");
  const btn = document.getElementById("run-backtest");
  btn.textContent = "Running...";
  btn.disabled = true;
  el.innerHTML = `<div class="loading"><div class="spinner"></div>Simulating ${n} games...</div>`;
  try {
    const r = await fetch(`/api/backtest?n_games=${n}&min_edge=${edge}`);
    const d = await r.json();
    const roiColor = d.flat_roi_pct >= 0 ? "var(--good)" : "var(--bad)";
    el.innerHTML = `
      <div class="bt-grid">
        <span class="label">Games simulated</span><span>${d.total_games}</span>
        <span class="label">Picks made</span><span>${d.picks_made}</span>
        <span class="label">Record</span><span>${d.wins}W - ${d.losses}L</span>
        <span class="label">Win rate</span><span>${(d.win_rate*100).toFixed(1)}%</span>
        <span class="label">Flat-bet ROI</span><span style="color:${roiColor}">${d.flat_roi_pct > 0 ? '+' : ''}${d.flat_roi_pct}%</span>
        <span class="label">Kelly ROI</span><span style="color:${roiColor}">${d.kelly_roi_pct > 0 ? '+' : ''}${d.kelly_roi_pct}%</span>
        <span class="label">Avg edge</span><span>${d.mean_edge_pct}%</span>
      </div>
      <h3 style="margin-top:12px;font-size:0.9rem">By Sport</h3>
      <div class="bt-grid">${Object.entries(d.by_sport).map(([k,v]) =>
        `<span class="label">${k.toUpperCase()}</span><span>${v.w}W-${v.l}L (${(v.wr*100).toFixed(0)}%) ROI $${v.pnl.toFixed(0)}</span>`
      ).join("")}</div>
      <h3 style="margin-top:12px;font-size:0.9rem">By Stat</h3>
      <div class="bt-grid">${Object.entries(d.by_stat).map(([k,v]) =>
        `<span class="label">${k}</span><span>${v.w}W-${v.l}L (${(v.wr*100).toFixed(0)}%)</span>`
      ).join("")}</div>`;
  } catch (e) {
    el.innerHTML = `<div class="card">Backtest failed. <span class="refresh-hint" onclick="this.closest('button')?.click()">Retry</span></div>`;
  } finally {
    btn.textContent = "Run Backtest";
    btn.disabled = false;
  }
});

/* ---- Live Scores ---- */
let scoresInterval;
async function loadScores() {
  const el = document.getElementById("scores-content");
  el.innerHTML = `<div class="loading"><div class="spinner"></div>Loading scores...</div>`;
  try {
    const [nba, mlb] = await Promise.all([
      fetch("/api/live/nba").then(r => r.json()).catch(() => ({games:[]})),
      fetch("/api/live/mlb").then(r => r.json()).catch(() => ({games:[]})),
    ]);
    let html = '<div class="refresh-hint" onclick="loadScores()">Tap to refresh</div>';
    html += "<h3 style='font-size:0.9rem;margin:8px 0'>NBA</h3>";
    if (!nba.games.length) html += '<div class="score-card">No NBA games today</div>';
    for (const g of nba.games) {
      const st = g.is_final ? "FINAL" : g.is_halftime ? "HALF" : `Q${g.quarter} ${g.clock}`;
      html += `<div class="score-card"><div class="teams">${g.away} @ ${g.home}</div><div class="score">${g.score}</div><div class="status">${st}</div></div>`;
    }
    html += "<h3 style='font-size:0.9rem;margin:12px 0 8px'>MLB</h3>";
    if (!mlb.games.length) html += '<div class="score-card">No MLB games today</div>';
    for (const g of mlb.games) {
      html += `<div class="score-card"><div class="teams">${g.away || '?'} @ ${g.home || '?'}</div><div class="status">${g.status}</div></div>`;
    }
    el.innerHTML = html;
  } catch (e) {
    el.innerHTML = `<div class="card">Failed to load scores. <span class="refresh-hint" onclick="loadScores()">Tap to retry</span></div>`;
  }
}

/* ---- Panel switching ---- */
function showPanel(name) {
  board.classList.toggle("hidden", name !== "board");
  document.getElementById("parlay-panel").classList.toggle("hidden", name !== "parlay");
  document.getElementById("backtest-panel").classList.toggle("hidden", name !== "backtest");
  document.getElementById("scores-panel").classList.toggle("hidden", name !== "scores");
  document.getElementById("filters").classList.toggle("hidden", name !== "board");
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

/* ---- Status badge ---- */
async function loadStatus() {
  try {
    const r = await fetch("/api/status");
    const s = await r.json();
    const badge = document.createElement("span");
    badge.className = "status-badge";
    const isLive = s.odds_provider === "live";
    badge.textContent = isLive ? `LIVE | ${s.nba_players} NBA | ${s.mlb_players} MLB` : `MOCK | ${s.nba_players} NBA | ${s.mlb_players} MLB`;
    badge.style.color = isLive ? "var(--good)" : "var(--muted)";
    document.querySelector("header h1").appendChild(badge);
  } catch (_) {}
}

loadStatus();
load("nba", "pregame");
