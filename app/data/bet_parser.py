"""Parse a sportsbook bet-slip screenshot via Claude Vision.

The user uploads a screenshot of their bet365 (or any book) bet slip.
We send the image to Claude with a tight schema prompt; Claude returns
structured JSON we can persist directly into the bet log.

Falls back gracefully to a 'manual entry required' response if the API
key isn't set or the parse fails.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)

# Use the latest available Claude model on the project's pinned SDK (0.39).
# Sonnet 4 is the recommended default for vision + structured extraction.
_DEFAULT_MODEL = os.environ.get("BET_PARSER_MODEL", "claude-sonnet-4-5")

_PROMPT = """You are reading a sportsbook bet-slip screenshot (likely bet365, DraftKings, FanDuel, or similar).

Extract structured data and respond with ONLY raw JSON, no markdown fences, no commentary, matching this exact schema:

{
  "book": "bet365" | "draftkings" | "fanduel" | "caesars" | "betmgm" | "other",
  "sport": "nba" | "mlb" | "nfl" | "nhl" | "other",
  "stake": <number, dollars>,
  "american_odds": <integer like +650 or -110>,
  "returned": <number, dollars actually returned; 0 if lost or open>,
  "status": "open" | "won" | "lost" | "push" | "void" | "cashout",
  "legs": [
    {
      "description": "<full leg text exactly as shown>",
      "player": "<player name if a player prop>",
      "stat": "<points|rebounds|assists|threes|pra|pr|pa|hits|total_bases|...>",
      "side": "OVER" | "UNDER" | "",
      "line": <number or null>,
      "status": "open" | "won" | "lost" | "push" | "void"
    }
  ]
}

Rules:
- Use the displayed odds (e.g. +650). Convert to integer.
- If status is "won" use the Returned amount; if "lost" or no return shown, returned=0.
- Combined stat lines like "Points, Assists & Rebounds (Combined)" → stat="pra".
- "Points & Rebounds" → "pr"; "Points & Assists" → "pa"; "Rebounds & Assists" → "ra".
- If a leg's individual status is shown by a green check it is "won"; red X → "lost"; gray → "open".
- If you cannot read the screenshot, return {"book":"other","sport":"other","stake":0,"american_odds":0,"returned":0,"status":"open","legs":[]}.
"""


def parse_bet_screenshot(image_bytes: bytes, media_type: str = "image/png") -> dict[str, Any]:
    """Send the image to Claude and return parsed bet data.

    Returns a dict in the schema above. On failure, raises RuntimeError
    so callers can surface a clear error to the UI.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot parse screenshots")

    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic SDK not installed") from e

    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode()

    msg = client.messages.create(
        model=_DEFAULT_MODEL,
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    text = "".join(block.text for block in msg.content if getattr(block, "type", "") == "text").strip()

    # Strip ```json fences if Claude included them despite the instruction
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("Bet parser returned unparseable JSON: %s", text[:300])
        raise RuntimeError(f"Could not parse bet slip: {e}") from e
