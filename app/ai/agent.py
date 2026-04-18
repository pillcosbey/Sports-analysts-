"""Claude analyst agent wrapper.

Thin wrapper around the Anthropic SDK that routes one of our three prompts
(pregame / live / postmortem) and returns parsed JSON. The agent has
*zero* access to numbers the caller did not already put in the prompt.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from app.ai.prompts import (
    build_live_prompt, build_postmortem_prompt, build_pregame_prompt,
)

# Default to the latest Sonnet model; swap for Opus if you want maximum
# quality at higher cost. Haiku is fine for batch pre-game runs.
DEFAULT_MODEL = "claude-sonnet-4-6"


def _client():
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "Install `anthropic` (pip install anthropic) to use the AI layer."
        ) from e
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    return anthropic.Anthropic(api_key=key)


def _call(system: str, user: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    client = _client()
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    ).strip()
    # Strip markdown code fences if model wrapped the JSON
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "non_json_response", "raw": text}


def analyze_pregame(**kwargs) -> Dict[str, Any]:
    system, user = build_pregame_prompt(**kwargs)
    return _call(system, user)


def analyze_live(**kwargs) -> Dict[str, Any]:
    system, user = build_live_prompt(**kwargs)
    return _call(system, user)


def review_postmortem(**kwargs) -> Dict[str, Any]:
    system, user = build_postmortem_prompt(**kwargs)
    return _call(system, user)
