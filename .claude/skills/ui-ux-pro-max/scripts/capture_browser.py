#!/usr/bin/env python3
"""URL capture adapter for ui-ux-pro-max.

This phase intentionally uses a bounded stdlib HTML fetch. A future Playwright
adapter can live here, but this script must never auto-install browsers or
system dependencies.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from capture_extractors import read_limited_text

MAX_URL_BYTES = 1_000_000


def load_url_document(source: str) -> list[tuple[str, str]]:
    parsed = urllib.parse.urlsplit(source)
    if parsed.scheme == "file":
        path = Path(urllib.request.url2pathname(parsed.path)).expanduser().resolve()
        return [(source, read_limited_text(path))]
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("--source-kind url requires http(s) or file URL")
    request = urllib.request.Request(
        source,
        headers={"User-Agent": "ui-ux-pro-max-capture/1.0 structural-reference"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_URL_BYTES + 1)
    except urllib.error.URLError as exc:
        raise ValueError(f"unable to fetch URL for structural capture: {exc}") from exc
    if len(raw) > MAX_URL_BYTES:
        raise ValueError(f"URL response exceeds {MAX_URL_BYTES} byte capture limit")
    return [(source, raw.decode("utf-8", errors="ignore"))]
