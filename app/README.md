# Sports Betting Research — NBA + MLB

A research system for player-prop edges on basketball and baseball, with
pre-game projections, **live in-game updates** (halftime / inning), Monte
Carlo simulation, and a **post-game learning loop** that grades every pick
and improves the model over time.

This is a *research tool*, not a bet placer. No affiliation with any
sportsbook. 21+. Bet responsibly.

## What it does

1. **Pulls odds + stats** from configured providers (stubs included).
2. **Projects** each player's prop (mean + variance) using season trend,
   last-N games, opponent defense, pace, and usage.
3. **Simulates** the outcome 100–10,000 times (Monte Carlo) to get
   `P(over)` and `P(under)`.
4. **Devigs** the sportsbook line into a fair probability, compares it
   against your simulated probability, and computes **edge + Kelly stake**.
5. **Live mode**: at halftime (NBA) or after each inning (MLB), reruns the
   projection with remaining game time and the player's current stats, and
   re-simulates the *final-game* total.
6. **Post-game**: grades every recommendation, logs residuals to SQLite,
   and feeds them back into the projection weights.
7. **AI analyst layer**: Claude writes the human-readable card using the
   prompts in `app/ai/prompts.py`. The model does not invent numbers — it
   explains the simulator's output.

## Layout

```
app/
├── core/          math utilities (devig, Kelly, distributions, simulator)
├── sports/nba/    NBA projection + live halftime update + markets
├── sports/mlb/    MLB projection + live inning update + markets
├── data/          provider abstraction + local SQLite store
├── learning/      post-game grader + weight feedback
├── ai/            prompt templates + Claude agent wrapper
├── api/           FastAPI backend
├── web/           minimal HTML/JS frontend
└── tests/         math unit tests
```

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
cp app/.env.example app/.env        # add your API keys
python -m app.api.main              # serves the web UI on :8000
```

Then open http://localhost:8000 — you'll see today's NBA and MLB boards.
Everything runs on mock data until you add real API keys.

## Running tests

```bash
pytest app/tests
```

## What you need to add

- **The Odds API** key (free tier works for testing): https://the-odds-api.com
- **MLB StatsAPI** is free — no key needed. Already wired in the stub.
- **NBA stats** — balldontlie is free; SportsDataIO or Sportradar for pro.
- Rotate the SportsDataIO key that was checked into the legacy scripts.
