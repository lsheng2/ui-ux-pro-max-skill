#!/usr/bin/env python3
"""Shared helpers for deterministic ui-ux-pro-max capture artifacts."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CAPTURE_SCHEMA_VERSION = 1
LEGAL_MODES = {"owned", "internal_reference", "third_party_reference"}
SOURCE_KINDS = {"url", "project", "html"}
SIGNAL_GROUPS = (
    "colors", "typography", "spacing", "radius", "shadows", "motion",
    "components", "layout", "accessibility",
)
DEFAULT_VIEWPORTS = (
    {"width": 375, "height": 812, "label": "mobile"},
    {"width": 768, "height": 1024, "label": "tablet"},
    {"width": 1440, "height": 1000, "label": "desktop"},
)
STYLE_STATUSES = {"active", "supplemental", "deprecated"}
STYLE_HEADERS = (
    "No", "Style Category", "Type", "Keywords", "Primary Colors",
    "Secondary Colors", "Effects & Animation", "Best For", "Do Not Use For",
    "Light Mode ✓", "Dark Mode ✓", "Performance", "Accessibility",
    "Mobile-Friendly", "Conversion-Focused", "Framework Compatibility",
    "Era/Origin", "Complexity", "AI Prompt Keywords", "CSS/Technical Keywords",
    "Implementation Checklist", "Design System Variables", "Style ID",
    "Aliases", "Status", "Parent Style ID", "Replacement Domain",
    "Replacement ID", "Preferred Mode",
)


def script_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str, fallback: str = "captured-style") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").casefold()).strip("-")
    return slug or fallback


def title_from_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", value) if part)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(path: Path, headers: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(headers), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key) for key in writer.fieldnames})


def compact(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def counter_items(counter: Counter[str], limit: int = 40, *, source: str = "") -> list[dict[str, Any]]:
    rows = []
    for value, count in counter.most_common(limit):
        item: dict[str, Any] = {"value": value, "count": count}
        if source:
            item["source"] = source
        rows.append(item)
    return rows


def ensure_signal_shape(signals: Any) -> dict[str, list[Any]]:
    result = {name: [] for name in SIGNAL_GROUPS}
    if isinstance(signals, dict):
        for name in SIGNAL_GROUPS:
            value = signals.get(name, [])
            result[name] = value if isinstance(value, list) else []
    return result


def word_limited(text: str, max_words: int = 40) -> str:
    words = re.findall(r"\S+", text)
    return " ".join(words[:max_words])


def relpath_or_name(path: Path, root: Path | None = None) -> str:
    try:
        return str(path.relative_to(root or Path.cwd()))
    except ValueError:
        return str(path)
