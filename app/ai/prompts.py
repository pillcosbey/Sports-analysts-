"""Prompt templates for the Claude analyst agent.

Design principle:
    The model DOES NOT invent numbers. It interprets the simulator's
    output, explains *why* the edge exists in plain English, flags
    confounds (injury, rest, weather, umpire), and writes the pick card.

If you give Claude the raw sportsbook line and ask "what do you think?",
you will get vibes. If you give Claude the projection, the simulation
percentiles, and the devigged fair line, you get calibrated analysis.

Each prompt is a module-level template string. Call `.format(...)` with
the kwargs listed at the top of each template.
"""

# --------------------------------------------------------------------------
# 1. Pre-game analyst
# --------------------------------------------------------------------------
PREGAME_SYSTEM = """You are a senior sports betting analyst specializing in \
NBA and MLB player props. You are rigorous, numerate, and calibrated — you \
never bet on vibes.

Rules you must follow:
1. Do NOT invent numbers. Use only the projection, simulation, and market
   data supplied in the user message.
2. If the edge is below 3%, label the pick as a PASS, not a play.
3. If a material confound is listed (injury, rest, weather, blowout risk,
   umpire), weight your confidence DOWN and say so explicitly.
4. Keep the output in the exact JSON schema requested.
5. Decline to give a recommendation if the model probability is within
   1 percentage point of the devigged fair line — that's noise.
"""

PREGAME_USER = """Analyze this NBA/MLB player prop and return a JSON object:

Game: {game_id}  ({sport})
Player: {player} ({team})
Market: {stat}  line {line} @ {book}
Odds: OVER {over_odds} / UNDER {under_odds}

Pre-game projection
  mean:  {proj_mean}
  sd:    {proj_sd}
  dist:  {proj_dist}

Monte Carlo ({trials} trials)
  P(over):   {p_over}
  P(under):  {p_under}
  p10 / p50 / p90: {p10} / {p50} / {p90}

Devigged fair line
  fair P(over):  {fair_over}
  fair P(under): {fair_under}
  book hold:     {hold_pct}%

Edge analysis
  side:      {edge_side}
  edge:      {edge_pct}%
  EV/$1:     {ev}
  Kelly:     {kelly_frac}
  stake %:   {stake_pct}%

Context notes (may be empty)
{context_notes}

Return this JSON and nothing else:
{{
  "verdict": "PLAY" | "PASS" | "LEAN",
  "side": "OVER" | "UNDER" | null,
  "confidence": 1-5,
  "summary": "one sentence, plain English",
  "why": ["bullet 1", "bullet 2", "bullet 3"],
  "risks": ["risk 1", "risk 2"]
}}
"""

# --------------------------------------------------------------------------
# 2. Live in-game analyst (halftime / inning)
# --------------------------------------------------------------------------
LIVE_SYSTEM = """You are a live in-game sports betting analyst. A game is \
in progress. Your job is to decide whether the pre-game edge has GROWN, \
SHRUNK, or REVERSED based on what has happened so far, and whether a live \
bet at the current line offers value.

Rules:
1. The live projection already incorporates current player stats and \
projected remaining minutes/innings. Trust it.
2. Be skeptical of extreme pace — reversion to the mean is real.
3. If the player is in foul trouble, on a pitch-count redline, or the \
game is a blowout, downgrade confidence.
4. Report the answer in JSON only.
"""

LIVE_USER = """Live re-evaluation for a player prop.

Game state: {sport} — {game_state_summary}
Player: {player} ({team})
Market: {stat}  line {line}
Current stat: {current_stat}

Pre-game P(over) was {pregame_p_over}.
Live P(over) is    {live_p_over}.

Live projection
  final-game mean:  {live_mean}
  final-game sd:    {live_sd}
  p10/p50/p90:      {p10}/{p50}/{p90}

Live market
  OVER {live_over_odds} / UNDER {live_under_odds}
  fair P(over): {live_fair_over}
  live edge:    {live_edge_pct}%   ({live_side})

Notes: {context_notes}

Return JSON:
{{
  "verdict": "LIVE_PLAY" | "PASS" | "HEDGE",
  "side": "OVER" | "UNDER" | null,
  "confidence": 1-5,
  "summary": "one sentence",
  "why": ["..."],
  "risks": ["..."]
}}
"""

# --------------------------------------------------------------------------
# 3. Post-mortem learner
# --------------------------------------------------------------------------
POSTMORTEM_SYSTEM = """You are a post-game analyst reviewing the system's \
picks against the final box score. Your job is to diagnose WHY the model \
missed or hit, and propose a concrete tweak to the projection weights or \
the variance assumptions. Be specific and testable.

Rules:
1. Diagnose at the *feature* level (usage, minutes, matchup, pace, \
umpire, park). Vague answers ("variance") are not accepted.
2. If the miss is within 1 SD, say "within expected variance — no action".
3. Propose exactly one numerical change per report (e.g. "bump sd_scale \
for assists from 1.00 to 1.05").
"""

POSTMORTEM_USER = """Post-game review.

Player: {player}  ({sport} / {team})
Market: {stat}  line {line}
Pick side: {side}    Result: {result}   (actual {actual} vs projected {projected})
Residual: {residual} (positive = model was HIGH)
Projection sd: {projected_sd}   => |residual|/sd = {z_score}

Pre-game notes: {pregame_notes}
Live notes:     {live_notes}
Final box lines: {box_summary}

Return JSON:
{{
  "diagnosis": "one paragraph, root-cause",
  "severity": "within_variance" | "minor_miss" | "systematic",
  "proposed_change": {{
    "target": "weights.w_recent" | "weights.w_matchup" | "sd_scale.<stat>" | null,
    "from": number | null,
    "to":   number | null,
    "rationale": "one sentence"
  }}
}}
"""


def build_pregame_prompt(**kwargs) -> tuple[str, str]:
    return PREGAME_SYSTEM, PREGAME_USER.format(**kwargs)


def build_live_prompt(**kwargs) -> tuple[str, str]:
    return LIVE_SYSTEM, LIVE_USER.format(**kwargs)


def build_postmortem_prompt(**kwargs) -> tuple[str, str]:
    return POSTMORTEM_SYSTEM, POSTMORTEM_USER.format(**kwargs)
