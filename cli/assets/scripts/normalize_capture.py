#!/usr/bin/env python3
"""Normalize capture.json into reviewable style-candidate signals."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from capture_shared import CAPTURE_SCHEMA_VERSION, read_json, slugify, write_json
from validate_capture import validate_capture_artifact, validate_normalized_artifact

TOKEN_NAMES = {
    "colors": ("--color-primary", "--color-secondary", "--color-surface", "--color-accent",
               "--color-muted", "--color-border"),
    "spacing": ("--space-1", "--space-2", "--space-3", "--space-4", "--space-5"),
    "radius": ("--radius-1", "--radius-2", "--radius-3"),
    "shadows": ("--shadow-1", "--shadow-2", "--shadow-3"),
    "motion": ("--motion-1", "--motion-2", "--motion-3"),
}


def _item_value(item: Any, group: str) -> str:
    if isinstance(item, dict):
        if group == "typography" and item.get("family"):
            return str(item["family"]).strip()
        return str(item.get("value") or item.get("pattern") or item.get("signal") or "").strip()
    return str(item or "").strip()


def _item_count(item: Any) -> int:
    if isinstance(item, dict):
        count = item.get("count", 1)
        return count if isinstance(count, int) and count > 0 else 1
    return 1


def _source_type(item: Any) -> str | None:
    if isinstance(item, dict) and isinstance(item.get("sourceType"), str):
        return item["sourceType"]
    return None


def _normalize_token_group(group: str, items: list[Any], min_count: int) -> tuple[list[dict], list[dict]]:
    buckets: dict[tuple[str, str | None], int] = {}
    for item in items:
        value = _item_value(item, group)
        if not value:
            continue
        key = (value, _source_type(item))
        buckets[key] = buckets.get(key, 0) + _item_count(item)

    selected: list[dict] = []
    excluded: list[dict] = []
    names = TOKEN_NAMES.get(group, tuple(f"--{group}-{index}" for index in range(1, 10)))
    ranked = sorted(buckets.items(), key=lambda entry: (-entry[1], entry[0][0].casefold()))
    for index, ((value, source_type), count) in enumerate(ranked):
        if count < min_count:
            excluded.append({
                "group": group,
                "value": value,
                "count": count,
                "reason": "long-tail one-off value",
            })
            continue
        token = {
            "name": names[min(index, len(names) - 1)] if names else f"--{group}-{index + 1}",
            "value": value,
            "count": count,
        }
        if source_type:
            token["sourceType"] = source_type
        selected.append(token)
    return selected, excluded


def _rank_structural(items: list[Any], key: str) -> list[dict]:
    rows: list[dict] = []
    for item in items:
        if isinstance(item, dict):
            value = item.get(key) or item.get("value") or item.get("signal")
            if value:
                rows.append({"value": str(value), "count": _item_count(item)})
        elif item:
            rows.append({"value": str(item), "count": 1})
    return sorted(rows, key=lambda row: (-row["count"], row["value"].casefold()))[:12]


def _density_label(selected_tokens: dict[str, list[dict]]) -> str:
    values = [item.get("value", "") for item in selected_tokens.get("spacing", []) if isinstance(item, dict)]
    numbers: list[float] = []
    for value in values:
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if match:
            numbers.append(float(match.group(0)))
    if not numbers:
        return "standard"
    median = sorted(numbers)[len(numbers) // 2]
    if median <= 8:
        return "dense"
    if median >= 32:
        return "spacious"
    return "standard"


def _candidate_style_id(capture_id: str, structural: dict[str, Any], selected_tokens: dict[str, list[dict]]) -> str:
    layout = "style"
    if structural.get("layout"):
        layout = slugify(str(structural["layout"][0]["value"]), "layout")
    elif structural.get("components"):
        layout = slugify(str(structural["components"][0]["value"]), "component")
    density = _density_label(selected_tokens)
    parts = [slugify(capture_id), layout, density]
    deduped: list[str] = []
    for part in parts:
        if part and (not deduped or deduped[-1] != part):
            deduped.append(part)
    return "-".join(deduped)


def normalize_capture(payload: dict[str, Any], *, min_count: int = 2) -> dict[str, Any]:
    errors = validate_capture_artifact(payload)
    if errors:
        raise ValueError("; ".join(errors))

    signals = payload.get("signals", {})
    selected_tokens: dict[str, list[dict]] = {}
    excluded: list[dict] = []
    for group in ("colors", "typography", "spacing", "radius", "shadows", "motion"):
        selected, dropped = _normalize_token_group(group, signals.get(group, []), min_count)
        selected_tokens[group] = selected
        excluded.extend(dropped)

    for item in payload.get("exclusions", []):
        if isinstance(item, dict):
            excluded.append({"group": item.get("type", "capture"), "reason": item.get("reason", "")})

    structural = {
        "components": _rank_structural(signals.get("components", []), "role"),
        "layout": _rank_structural(signals.get("layout", []), "pattern"),
        "accessibility": _rank_structural(signals.get("accessibility", []), "signal"),
        "source": payload.get("source", {}),
        "viewports": payload.get("viewports", []),
    }
    selected_groups = sum(1 for rows in selected_tokens.values() if rows)
    structural_groups = sum(1 for name in ("components", "layout", "accessibility") if structural[name])
    confidence = min(0.95, 0.45 + selected_groups * 0.06 + structural_groups * 0.04)
    if payload["source"]["legalMode"] == "third_party_reference":
        confidence = min(confidence, 0.75)

    normalized = {
        "schemaVersion": CAPTURE_SCHEMA_VERSION,
        "captureId": payload["captureId"],
        "legalMode": payload["source"]["legalMode"],
        "selectedTokens": selected_tokens,
        "structuralSignals": structural,
        "excludedSignals": excluded,
        "confidence": round(confidence, 2),
        "recommendedStyleId": {
            "candidate": _candidate_style_id(payload["captureId"], structural, selected_tokens),
            "reason": "derived from captureId, dominant layout/component, and density; review before registration",
        },
    }
    errors = validate_normalized_artifact(normalized)
    if errors:
        raise ValueError("; ".join(errors))
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", help="Path to capture.json")
    parser.add_argument("--out", required=True, help="Path to write normalized.json")
    parser.add_argument("--min-count", type=int, default=2, help="Minimum repeated count to select a token")
    args = parser.parse_args(argv)

    try:
        normalized = normalize_capture(read_json(Path(args.capture)), min_count=args.min_count)
        write_json(Path(args.out), normalized)
    except (OSError, ValueError) as exc:
        print(f"normalize_capture: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote normalized artifact: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
