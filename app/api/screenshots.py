"""FastAPI routes for the website screenshot agent.

Endpoints:
    POST /api/screenshots          { url | urls, full_page?, wait_for?, ... }
    GET  /api/screenshots          list every saved screenshot
    GET  /api/screenshots/{name}   download a single PNG by filename
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agents.screenshot_agent import (
    DEFAULT_OUT_DIR,
    PlaywrightUnavailable,
    ScreenshotAgent,
    list_saved,
)

router = APIRouter(prefix="/api/screenshots", tags=["screenshots"])


class CaptureBody(BaseModel):
    url: str | None = None
    urls: list[str] | None = None
    full_page: bool = True
    wait_for: str | None = None
    wait_ms: int = 0
    viewport_width: int = Field(default=1440, ge=320, le=3840)
    viewport_height: int = Field(default=900, ge=240, le=2160)
    label: str | None = None
    user_agent: str | None = None
    concurrency: int = Field(default=3, ge=1, le=8)


@router.post("")
async def capture(body: CaptureBody):
    targets = body.urls or ([body.url] if body.url else [])
    if not targets:
        raise HTTPException(status_code=400, detail="Provide `url` or `urls`.")

    agent = ScreenshotAgent()
    kwargs = dict(
        full_page=body.full_page,
        wait_for=body.wait_for,
        wait_ms=body.wait_ms,
        viewport_width=body.viewport_width,
        viewport_height=body.viewport_height,
        label=body.label,
        user_agent=body.user_agent,
    )
    try:
        batch = await agent.capture_many(targets, concurrency=body.concurrency, **kwargs)
    except PlaywrightUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    return batch.to_dict()


@router.get("")
def index():
    return {"items": list_saved()}


@router.get("/{filename}")
def download(filename: str):
    # prevent path traversal — only serve plain files from the screenshots dir
    safe = Path(filename).name
    target = DEFAULT_OUT_DIR / safe
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found.")
    return FileResponse(target, media_type="image/png", filename=safe)
