const board = document.getElementById("board");
const buttons = document.querySelectorAll("nav button");

async function load(sport, phase) {
  board.innerHTML = `<div class="card">Loading ${sport.toUpperCase()} ${phase}…</div>`;
  const r = await fetch(`/api/board?sport=${sport}&phase=${phase}`);
  const data = await r.json();
  renderCards(data.cards);
}

function fmtEdge(edge) {
  if (!edge) return '<div class="verdict pass">NO EDGE — PASS</div>';
  return `<div class="verdict play">${edge.side} · ${edge.edge_pct}% edge · stake ${edge.recommended_stake_pct}%</div>`;
}

function renderCards(cards) {
  if (!cards.length) {
    board.innerHTML = '<div class="card">No picks right now.</div>';
    return;
  }
  board.innerHTML = cards.map(c => `
    <div class="card">
      <h2>${c.player} — ${c.stat} ${c.line}</h2>
      <div class="meta">${c.team} · ${c.sport.toUpperCase()} · ${c.phase}</div>
      <div class="grid">
        <span class="label">Projected</span><span>${c.projection.mean} ± ${c.projection.sd}</span>
        <span class="label">P(over)</span><span>${(c.simulation.p_over*100).toFixed(1)}%</span>
        <span class="label">Fair P(over)</span><span>${(c.fair.p_over*100).toFixed(1)}%</span>
        <span class="label">Book hold</span><span>${c.odds.hold_pct}%</span>
        <span class="label">p10 / p50 / p90</span><span>${c.simulation.p10} / ${c.simulation.p50} / ${c.simulation.p90}</span>
        <span class="label">Trials</span><span>${c.simulation.trials}</span>
      </div>
      ${fmtEdge(c.edge)}
    </div>
  `).join("");
}

buttons.forEach(b => b.addEventListener("click", () => {
  buttons.forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  load(b.dataset.sport, b.dataset.phase);
}));

load("nba", "pregame");
