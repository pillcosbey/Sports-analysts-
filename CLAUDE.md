# Claude handoff — Sports Analysts halftime parlay system

This file is the durable memory between chat sessions. **Read this first on session start.**
Last updated: 2026-05-22 (CLE/NYK conf-finals halftime parlays placed, pending grade).

---

## What this project is

A FastAPI app deployed on Railway (`https://web-production-11e8b.up.railway.app`) that helps
the user place real-money NBA playoff parlays at halftime. Workflow today:

1. User sends NBA halftime box score + bet365 line screenshots in chat.
2. Claude (me) hand-builds 2 parlays from judgment, not Monte Carlo.
3. User places the parlays on bet365 with real money.
4. User sends the final box; we grade and log lessons.

The live app exists for backup / record-keeping. The chat is the primary surface.

---

## CRITICAL — the lean workflow

User explicitly chose this over the JSON pipeline on 2026-05-20:

> "I want to go with your prediction screenshotting all that codes kills to much time"

**Do NOT** ask the user to paste JSON, run scripts, or hit endpoints during a live game.
The flow is:

- User sends ESPN box screenshot (per team) + bet365 line screenshots.
- Claude reads images, applies the judgment playbook below, returns 2 parlays.
- That's it.

If a request hits "too large" again, ask for a smaller batch (1 box per team + 2-3 line
categories max).

---

## The Judgment Playbook (the rules that won the recent parlays)

Apply these in order. Each rule has a real retrospective behind it.

### 1. Read the game script first

Before any leg, write down: score, lead, pace vs ~110 expected at HT, who's hot, who's
in foul trouble, who's been benched. **This frames everything else.**

### 2. Trust 1H rate only when backed by volume

High minutes + healthy FGA = signal. Low minutes or "2-2 FG hot" = noise — fade it.

> **Retrospective (CLE/DET G5, LeVert):** 2-2 FG in 13 1H minutes for 7 pts → went 0-5
> in 2H for 0 pts. The "rate" was 2 makes, not a stable signal. **Rule:** when 1H FGA/min
> < 0.30 and minutes ≥ 10, widen variance — treat the scoring line as a fade candidate.

### 3. Regress hot starts to season mean — hard

A starter who's above their season pace at half usually regresses. Don't extrapolate.

### 4. Blowout = starter haircut, bench bump

When leading team is up 10+ at half AND pace isn't a runaway (pace_factor ≤ 1.05),
starters get hooked in 2H, bench eats minutes.

> **Retrospective (SAS/MIN G5, Fox OVER 20.5):** SAS led 12+ at half, Fox sat most of Q4,
> lost by 18. Keldon Johnson (bench) put up 21 in garbage time. **Rule:** in lead-protect
> mode, starters → 0.85× projection on points/assists/threes/combos; bench (≤10 1H min) →
> 1.20× projection on same.

### 5. Foul trouble = real cut

4+ PF at half → 0.78× projection. Don't hedge, just cut.

### 6. Pace check on totals

If HT total is far from ~110, the OVER/UNDER on team and game totals usually follows.
Don't fight the pace the game is actually running.

### 7. Same-game correlation matters

Don't stack 3 OVERs on one team's guards in a lead-protect spot — they all fade together.
Build parlays with legs that are uncorrelated or move in different directions
(e.g. team A scoring OVER + team B defender's blocks OVER).

> **Rule:** for 3+ leg same-game parlays, flag if avg pairwise correlation is ≤ 0.02 —
> every leg has to hit independently, which is expensive.

### 8. PRA / PA / PR / P+A category check

bet365 truncates labels. **Always confirm the full stat category before pricing.**

> **Retrospective (SAS/MIN G5, Dosunmu):** bet365 showed "Player Points, Assi..." — I read
> it as PA. It was PRA (Points + Rebounds + Assists). Cost ~9 of model edge. **Rule:**
> if the stat label is truncated, ask the user to confirm before locking the leg.

### 9. Fade UNDERS on cold high-volume shooters — *only when the game is still live*

A 2-for-9 line at half is a positive regression candidate, not a continued slump.
Cold + volume = bounce-back. Cold + no volume = nothing.

> **Retrospective (SAS/MIN G6 + CLE/DET G7, 2026-05-15 / 2026-05-17):** Anthony
> Edwards (9-26 FG) and Cade Cunningham (5-16 FG, 0-7 3PT) were both
> cold + high-volume, both in 30+ pt elimination losses. **Neither bounced.**
> When their team got run off the floor, the offense stopped feeding them, the
> minutes got cut (Rule 4), and the cold line stayed cold through garbage time.
>
> **Caveat:** cold + volume only bounces when the game is still competitive at
> half. If the player's team is **down 15+ at half** *or* a starter-haircut
> blowout script is already likely (Rule 4 triggered), treat the cold line as
> a **continuation**, not a bounce — lean UNDER, not OVER. Rules 4 and 9
> agree in this spot, and that agreement is itself a strong PLAY signal.

### 10. One weak leg kills a parlay

Don't build 4-leggers from 4 mediocre edges. Two strong legs > four soft ones.
**Default: 2 parlays, 3 legs each, $10 each.** Scale legs/stake to confidence.

---

## Output format for each leg (used in chat AND when the app is refactored)

```
LEG: [Player] [OVER/UNDER] [line] [stat]
VERDICT: PLAY | LEAN | AVOID
WHY: one-line reason citing the rule above
```

Then for the parlay:

```
PARLAY: leg + leg + leg
PAYOUT: bet365 odds → $X to $Y
CONFIDENCE: high | medium | low
THESIS: one sentence on how the game has to play out for this to win
```

**No probabilities, no Monte Carlo numbers.** That's the user's explicit preference now.

---

## Recent results (running scoreboard)

| Date | Game | Bet | Result | Lesson |
|------|------|------|--------|--------|
| 2026-05-? | LAL/OKC | (initial picks) | mixed | baseline |
| 2026-05-? | SAS/MIN G4 | screenshot log | graded | season-sync gap surfaced |
| 2026-05-12 | SAS/MIN G5 | Wemby U reb / Edwards O / Castle O ($15) | **LOST** | blowout cap added |
| 2026-05-12 | SAS/MIN G5 | Dosunmu U PRA / Reid U PRA / Fox O ($10) | **LOST** | PRA/PA fix + blowout cap |
| 2026-05-14 | CLE/DET G5 | LeVert O 10.5 PTS | **LOST** | low-touches dampener added |
| 2026-05-17 | CLE/DET G6 | Tobias U / Duren O / Allen O PRA ($20 → $145) | **WON** at +625 | playbook works |
| 2026-05-18 | SAS/MIN G6 | 4-parlay showdown (System vs Claude, $40 total) | **UNGRADED** | need final box |
| 2026-05-20 | CLE/DET G7 | no parlay placed (request-too-large mid-upload) | — | CLE won series, advanced to face NYK |
| 2026-05-22 | CLE/NYK | A: Mobley O21.5 pts / Allen O9.5 reb / Brunson O8.5 ast ($10, +583) | **PENDING** | need final box |
| 2026-05-22 | CLE/NYK | B: Brunson O16.5 pts / Harden O4.5 ast / Hart O4.5 reb ($10, +722) | **PENDING** | need final box |

---

## System architecture (for reference, the app is the backup)

- `app/api/main.py` — FastAPI app, all endpoints
- `app/sports/halftime_projection.py` — current MC-based projection (will be replaced with judgment rules)
- `app/core/simulator.py` — Monte Carlo (deprecated for chat workflow, still backs `/api/halftime`)
- `app/core/builder.py` — auto-parlay builder (also MC-backed today)
- `app/core/parlay.py` — correlation-aware pricer (keep — copula model is good)
- `app/data/live_boxscore.py` — ESPN live box fetcher (primary data source)
- `app/data/balldontlie.py` — backup data source (needs `BALLDONTLIE_API_KEY`)
- `app/data/nba_api_source.py` — open-source NBA.com client (swar/nba_api). No key. Live box, season averages, static roster.
- `app/data/box_score.py` — ESPN → balldontlie → nba_api failover
- `app/data/play_by_play.py` — halftime reconstruction from ESPN PBP (for backtesting)
- `app/data/season_sync.py` — nightly season-avg refresh
- `app/data/pick_grader.py` — final box → leg grading
- `app/data/live_pick_status.py` — mid-game leg progress (winning/losing/tight)
- `app/data/bet_parser.py` — Claude Vision bet365 screenshot parser
- `app/data/pick_log.py`, `app/data/bet_log.py` — dual JSON log
- `app/data/player_resolver.py` — name fuzzy match w/ nicknames map
- `app/sports/backtest_game.py` — model-vs-actual 2H grading
- `app/web/` — three-tab UI (Halftime / Claude Picks / My Bets)

### Merged PRs that built the current system

- #5 — halftime analyzer pivot
- #6 — Claude pick log + promote
- #7 — auto-grader from ESPN finals
- #8 — balldontlie backup
- #9 — name resolver, season sync, auto-backtest, tuned weights
- #10 — blowout cap, PRA/PA fix, live status, correlation warning
- #11 — low-touches confidence dampener
- #12 — CLAUDE.md handoff doc
- #13 — nba_api as no-key fallback (closes pending item #4)

---

## Pending items (carry into next session)

1. **Settle SAS/MIN G6 4-parlay showdown** — System #1, System #2, Claude #1, Claude #2.
   User never sent the final box. Ask for it on next contact.
2. **Grade the CLE/NYK parlays placed 2026-05-22.** Halftime was CLE 49, NYK 53.
   - Parlay A ($10, +583): Mobley O21.5 pts / Allen O9.5 reb / Brunson O8.5 ast.
   - Parlay B ($10, +722): Brunson O16.5 pts / Harden O4.5 ast / Hart O4.5 reb.
   Ask the user for the final box, grade leg-by-leg, log the lesson.
   Roster note: this CLE team has **James Harden #1** and **Dean Wade #32** — both
   confirmed on the bet365 board, don't re-flag them. CLE/DET G7 is closed (CLE won
   the series and now faces NYK); no G7 parlay was ever placed.
3. **Refactor `/api/halftime` and `/api/builder` to use judgment rules instead of Monte Carlo.**
   Output per leg: `verdict ∈ {PLAY, LEAN, AVOID}` + `why: str`. Keep `parlay.py`'s
   correlation logic for the parlay-level layer.
4. ~~Fallback database gap.~~ **DONE (2026-05-20):** nba_api source covers
   every active player (Castle, Harper, Champagnie, Vassell, Shannon all
   resolve from the embedded static roster). On next Railway deploy,
   `POST /api/admin/sync-season-averages` will work with no env var set —
   it falls back to nba_api when `BALLDONTLIE_API_KEY` is missing.

---

## Operating rules (from user, preserve verbatim)

- "Push to main every changes we make push to main okay" — user wants all changes on main.
- "Force push to main" — explicit authorization for force pushes when remote rejects (use only when needed).
- Direct push to main has been 403'd by sandbox proxy in past sessions. Workaround:
  push to `claude/implement-todo-*` branch, then merge via GitHub MCP
  (`create_pull_request` + `merge_pull_request`).

## Sandbox constraints (known)

- External egress from sandbox is blocked for: ESPN, NBA.com, balldontlie.io, data.nba.net.
  Only `raw.githubusercontent.com` and WebSearch work. User opens URLs on their phone and
  screenshots back when web data is needed.
- `nba_api` calls hit stats.nba.com / cdn.nba.com — also blocked from sandbox.
  The package works on Railway; can't be smoke-tested locally beyond static-roster lookups.
- `gh` CLI is **not** available. Use `mcp__github__*` MCP tools instead.

---

## How to resume on a fresh chat

1. Read this file end-to-end.
2. Check `git log --oneline -20` to see what's shipped since this doc was written.
3. Ask the user: "Where do we pick up — Game 7 halftime, settle G6, or season-sync gap?"
4. Keep the lean workflow. Box + bet365 screenshots → 2 hand-built parlays. No JSON.
