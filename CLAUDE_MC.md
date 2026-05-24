# Claude handoff — MC chat (Monte Carlo parlay system)

This file is the durable memory for the **Monte Carlo chat**. There is a
sister chat that uses the judgment playbook (see `CLAUDE.md`). The two
chats run in parallel on the same games — pure-model vs pure-judgment —
so the user can A/B their picks.

**Read this first on session start. Then read `CLAUDE.md` for game context
(recent results, series state, pending items), but ignore its "lean
workflow / no Monte Carlo" rules — those apply to the judgment chat only.**

---

## What this chat is

Pure Monte Carlo parlay picks. No judgment overlay, no 12-rule playbook.
The user wants to compare the model's picks against the judgment chat's
picks on the same halftime data.

Workflow:

1. User sends ESPN box screenshots (per team) + bet365 line screenshots.
2. This chat parses the screenshots into the `NBABoxGame` dataclass.
3. Run the existing MC pipeline: project → simulate → build parlays.
4. Output 2 parlays with per-leg win probabilities and parlay EV vs bet365 odds.
5. No 12-rule trim/boost. The model speaks for itself.

---

## The pipeline (use the existing code, don't reimplement)

The MC system already exists in this repo. Use it.

```python
from app.data.live_boxscore import NBABoxGame, NBABoxPlayer
from app.sports.halftime_projection import project_nba_halftime
from app.core.simulator import simulate_prop
from app.core.parlay import build_parlay, ParlayLeg
from app.core.builder import suggest_builders
```

### Step 1 — Parse screenshots into `NBABoxGame`

`NBABoxGame` lives in `app/data/live_boxscore.py`. Required fields:

- `game_id, home_team, away_team, home_team_name, away_team_name`
- `home_score, away_score`
- `quarter=2, clock="0:00", is_halftime=True, is_final=False`
- `home_quarters=[q1, q2], away_quarters=[q1, q2]`
- `players: list[NBABoxPlayer]` — every player who saw 1H minutes

`NBABoxPlayer` requires: `player, team, starter, minutes, points, rebounds,
assists, threes_made, steals, blocks, turnovers, fouls, fg_made, fg_att,
ft_made, ft_att`.

Read the ESPN box screenshot carefully — every number goes into the dataclass.
Set `starter=True` for the 5 listed at the top of each team box, `False` for
the bench section.

### Step 2 — Project halftime → full game

```python
projection = project_nba_halftime(game)
```

Returns a `HalftimeGame` with per-player projected full-game stats and a pace
factor. This is the model's view of "what does the rest of the game look like."

### Step 3 — Parse bet365 lines

For each bet365 prop screenshot, extract: player name, stat category, line
value, OVER price, UNDER price. Build a list of candidate legs.

**Stat category gotcha:** bet365 truncates labels (PA vs PRA vs P+A vs P+R).
Confirm the full category with the user if ambiguous — same rule as the
judgment chat. This is a data-correctness issue, not a judgment overlay.

### Step 4 — Simulate each leg

```python
prob_over = simulate_prop(projection, player_name, stat, line, "OVER", trials=20000)
```

Returns the model's win probability for that side. Compare against the
implied probability from the bet365 price to get edge.

### Step 5 — Build parlays

Two options:

```python
# Option A: auto-suggest
suggestions = suggest_builders(projection, candidate_legs, max_legs=3)

# Option B: hand-pick the top-EV legs and price the parlay
legs = [ParlayLeg(...), ParlayLeg(...), ParlayLeg(...)]
result = build_parlay(legs)
```

`build_parlay` is correlation-aware (copula model in `parlay.py`). Use it —
don't multiply leg probs naively.

### Step 6 — Output

Format per leg:
```
LEG: [Player] [OVER/UNDER] [line] [stat]
MODEL P(WIN): 0.XX
BET365: [odds] → implied 0.XX
EDGE: +/-X.X%
```

Format per parlay:
```
PARLAY: leg + leg + leg
MODEL P(WIN): 0.XX (correlation-adjusted)
BET365 PAYOUT: [combined odds] → $10 to $YY
EV: +/-$X.XX per $10
```

**No PLAY/LEAN/AVOID verdicts.** Pure probabilities and EV. The user decides
whether to place based on the number.

---

## Output rules

- **Always include the trial count** used (default 20000) so the user can see
  how converged the estimate is.
- **Always include the correlation-adjusted parlay prob**, not just the product
  of leg probs. Same-game legs are correlated; the copula in `parlay.py`
  handles it.
- **Default: 2 parlays per game**, same as judgment chat, so the comparison
  is apples-to-apples. Pick the two highest-EV parlays from the
  `suggest_builders` output.
- **Do NOT apply Rule 4 (blowout cap), Rule 11 (assist fade), Rule 12 (wing
  rebound vs hot shooting), etc.** Those are judgment-chat rules. If the
  model's projection already encodes the effect, it's encoded; if not, that's
  what the comparison is for.

---

## What gets logged back to `CLAUDE.md`

After the final box arrives and parlays grade:

- Append a row to the "Recent results" table in `CLAUDE.md` with `(MC)` suffix
  on the bet description, e.g.:
  `2026-05-24 | SAS/OKC G4 | (MC) Wemby U / SGA O / Hart O ($10, +XXX) | LOST | model overprojected pace`
- The judgment chat appends its own row separately. The two rows on the same
  game = the head-to-head data point.

---

## Sandbox constraints (inherited from main `CLAUDE.md`)

- External egress is blocked for ESPN, NBA.com, balldontlie.io, data.nba.net.
  **This chat cannot fetch live box scores from those sources.** The user
  provides screenshots; this chat parses them.
- `stats.nba.com` is also blocked — `nba_api` calls fail from sandbox.
  Season averages baked into `app/sports/halftime_projection.py` rely on the
  nightly Railway-side `season_sync` having run; that data is in the repo
  already.
- `gh` CLI not available — use `mcp__github__*` MCP tools if logging picks.
- Direct push to main has been 403'd by sandbox proxy. Workaround: push to
  `claude/mc-*` branch, then merge via GitHub MCP.

---

## How to resume on a fresh MC chat

1. Read this file end-to-end.
2. Read `CLAUDE.md` for: recent results, series state, pending items, roster
   notes (e.g. Harden #1 / Wade #32 on CLE, J-Dub day-to-day for OKC).
   **Skip the "Judgment Playbook" section — that's not for this chat.**
3. Check `git log --oneline -20` for anything shipped since either doc was
   written.
4. Ask the user: "Which game's halftime are we modeling — and is the
   judgment chat running on it too so I know to log the comparison?"
5. Workflow: screenshots → parse → MC → 2 parlays with probabilities. No
   judgment overlay.
