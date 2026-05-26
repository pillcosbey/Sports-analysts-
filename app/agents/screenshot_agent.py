"""Website screenshot agent.

Drives a headless Chromium browser via Playwright to capture screenshots of
arbitrary URLs and persist them inside the repository under
``out/screenshots/``. The agent is async-first so it composes with the
FastAPI app, but it also ships a small CLI for one-off captures.

Usage (CLI):

    python -m app.agents.screenshot_agent https://example.com
    python -m app.agents.screenshot_agent https://example.com --full-page --label home
    python -m app.agents.screenshot_agent https://a.com https://b.com --label batch

Usage (Python):

    from app.agents.screenshot_agent import ScreenshotAgent
    agent = ScreenshotAgent()
    result = await agent.capture("https://example.com", full_page=True)
    print(result.path)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "out" / "screenshots"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return (slug[:max_len] or "page").strip("-") or "page"


def _host_slug(url: str) -> str:
    host = urlparse(url).netloc or "page"
    return _slugify(host)


def _short_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


@dataclass
class CaptureRequest:
    url: str
    full_page: bool = True
    wait_for: str | None = None  # CSS selector to await
    wait_ms: int = 0  # extra delay after load
    viewport_width: int = 1440
    viewport_height: int = 900
    label: str | None = None  # user-facing tag, becomes part of filename
    user_agent: str | None = None


@dataclass
class CaptureResult:
    url: str
    path: str  # absolute path on disk
    relative_path: str  # path relative to repo root
    bytes: int
    captured_at: str
    title: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class BatchResult:
    results: list[CaptureResult] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    def to_dict(self) -> dict:
        return {
            "ok_count": self.ok_count,
            "fail_count": self.fail_count,
            "results": [asdict(r) for r in self.results],
        }


class PlaywrightUnavailable(RuntimeError):
    """Raised when Playwright (or its browser binary) isn't installed."""


class ScreenshotAgent:
    """Headless-browser screenshot taker.

    The agent is intentionally thin: it doesn't try to be a generic scraper,
    just a reliable "URL in, PNG on disk, metadata out" pipeline that the
    rest of the analyst system can plug into.
    """

    def __init__(self, out_dir: Path | str | None = None) -> None:
        self.out_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ---------- public API ----------

    async def capture(self, url: str, **kwargs) -> CaptureResult:
        req = CaptureRequest(url=url, **kwargs)
        return await self._capture_one(req)

    async def capture_many(
        self, urls: Sequence[str], *, concurrency: int = 3, **kwargs
    ) -> BatchResult:
        sem = asyncio.Semaphore(concurrency)

        async def _run(u: str) -> CaptureResult:
            async with sem:
                return await self._capture_one(CaptureRequest(url=u, **kwargs))

        results = await asyncio.gather(*(_run(u) for u in urls))
        return BatchResult(results=list(results))

    # ---------- internals ----------

    def _build_filename(self, req: CaptureRequest) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        parts = [ts, req.label and _slugify(req.label) or _host_slug(req.url), _short_hash(req.url)]
        name = "-".join(p for p in parts if p) + ".png"
        return self.out_dir / name

    async def _capture_one(self, req: CaptureRequest) -> CaptureResult:
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except ImportError as e:
            raise PlaywrightUnavailable(
                "Playwright isn't installed. Run: pip install playwright && playwright install chromium"
            ) from e

        path = self._build_filename(req)
        captured_at = datetime.now(timezone.utc).isoformat()
        title: str | None = None
        error: str | None = None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(
                        viewport={"width": req.viewport_width, "height": req.viewport_height},
                        user_agent=req.user_agent,
                    )
                    page = await context.new_page()
                    await page.goto(req.url, wait_until="networkidle", timeout=45_000)
                    if req.wait_for:
                        await page.wait_for_selector(req.wait_for, timeout=15_000)
                    if req.wait_ms:
                        await page.wait_for_timeout(req.wait_ms)
                    try:
                        title = await page.title()
                    except Exception:
                        title = None
                    await page.screenshot(path=str(path), full_page=req.full_page)
                finally:
                    await browser.close()
        except PlaywrightUnavailable:
            raise
        except Exception as e:  # network failures, navigation timeouts, etc.
            error = f"{type(e).__name__}: {e}"

        size = path.stat().st_size if path.exists() else 0
        return CaptureResult(
            url=req.url,
            path=str(path),
            relative_path=str(path.relative_to(REPO_ROOT)),
            bytes=size,
            captured_at=captured_at,
            title=title,
            error=error,
        )


# ---------- helpers used by API + CLI ----------

def list_saved(out_dir: Path | str | None = None) -> list[dict]:
    """Return metadata for every PNG in the screenshots directory."""
    d = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    if not d.exists():
        return []
    items = []
    for p in sorted(d.glob("*.png"), reverse=True):
        st = p.stat()
        items.append({
            "filename": p.name,
            "path": str(p),
            "relative_path": str(p.relative_to(REPO_ROOT)),
            "bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return items


# ---------- CLI ----------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="screenshot-agent",
        description="Capture screenshots of one or more URLs into out/screenshots/.",
    )
    p.add_argument("urls", nargs="+", help="One or more URLs to capture.")
    p.add_argument("--label", help="Optional tag used in the output filename.")
    p.add_argument("--full-page", dest="full_page", action="store_true", default=True,
                   help="Capture the full scrollable page (default).")
    p.add_argument("--viewport-only", dest="full_page", action="store_false",
                   help="Capture only the viewport instead of the full page.")
    p.add_argument("--wait-for", help="CSS selector to wait for before capturing.")
    p.add_argument("--wait-ms", type=int, default=0, help="Extra delay (ms) after page load.")
    p.add_argument("--width", type=int, default=1440, help="Viewport width (default 1440).")
    p.add_argument("--height", type=int, default=900, help="Viewport height (default 900).")
    p.add_argument("--concurrency", type=int, default=3, help="Max parallel captures (default 3).")
    p.add_argument("--out-dir", help="Override output directory.")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return p


async def _amain(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    agent = ScreenshotAgent(out_dir=args.out_dir)
    try:
        batch = await agent.capture_many(
            args.urls,
            concurrency=args.concurrency,
            full_page=args.full_page,
            wait_for=args.wait_for,
            wait_ms=args.wait_ms,
            viewport_width=args.width,
            viewport_height=args.height,
            label=args.label,
        )
    except PlaywrightUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(batch.to_dict(), indent=2))
    else:
        for r in batch.results:
            tag = "OK" if r.ok else "FAIL"
            extra = r.error if r.error else f"{r.bytes} bytes -> {r.relative_path}"
            print(f"[{tag}] {r.url}  {extra}")
        print(f"\n{batch.ok_count} ok / {batch.fail_count} failed")
    return 0 if batch.fail_count == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    sys.exit(main())
