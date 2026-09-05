#!/usr/bin/env python3
"""List registered ui-ux-pro-max styles and captured draft style candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from capture_shared import read_csv_rows, read_json, script_data_dir, title_from_slug


def _public_row(row: dict[str, Any], source_path: Path, state: str) -> dict[str, Any]:
    style_id = str(row.get("Style ID") or row.get("styleId") or "").strip()
    name = str(row.get("Style Category") or row.get("name") or title_from_slug(style_id)).strip()
    return {
        "styleId": style_id,
        "name": name,
        "styleCategory": name,
        "aliases": str(row.get("Aliases") or row.get("aliases") or "").strip(),
        "status": str(row.get("Status") or row.get("status") or "supplemental").strip(),
        "preferredMode": str(row.get("Preferred Mode") or row.get("preferredMode") or "auto").strip(),
        "parentStyleId": str(row.get("Parent Style ID") or row.get("parentStyleId") or "").strip(),
        "registrationState": state,
        "sourcePath": str(source_path),
        "shortSummary": str(row.get("Best For") or row.get("shortSummary") or "").strip(),
        "bestFor": str(row.get("Best For") or row.get("bestFor") or "").strip(),
    }


def registered_styles(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"registered styles file not found: {path}")
    _, rows = read_csv_rows(path)
    return [_public_row(row, path, "registered") for row in rows if row.get("Style ID")]


def _draft_from_csv(path: Path) -> list[dict[str, Any]]:
    _, rows = read_csv_rows(path)
    return [_public_row(row, path, "draft") for row in rows if row.get("Style ID")]


def _recommended_id(payload: dict[str, Any]) -> str:
    recommended = payload.get("recommendedStyleId")
    if isinstance(recommended, dict):
        return str(recommended.get("candidate") or recommended.get("styleId") or "").strip()
    return str(recommended or "").strip()


def _draft_from_normalized(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    style_id = _recommended_id(payload)
    if not style_id:
        return []
    structural = payload.get("structuralSignals") if isinstance(payload.get("structuralSignals"), dict) else {}
    components = ", ".join(item.get("value", "") for item in structural.get("components", [])[:4]
                           if isinstance(item, dict))
    layout = ", ".join(item.get("value", "") for item in structural.get("layout", [])[:4]
                       if isinstance(item, dict))
    summary = "; ".join(part for part in (components, layout) if part)
    row = {
        "Style ID": style_id,
        "Style Category": title_from_slug(style_id),
        "Aliases": "",
        "Status": "supplemental",
        "Preferred Mode": "auto",
        "Parent Style ID": "",
        "Best For": summary or "Captured structural UI style candidate",
    }
    return [_public_row(row, path, "draft")]


def draft_styles(captures_dir: Path) -> list[dict[str, Any]]:
    if not captures_dir.exists():
        return []
    drafts: list[dict[str, Any]] = []
    dirs_with_rows: set[Path] = set()
    for name in ("style-row.csv", "style-row.draft.csv"):
        for path in sorted(captures_dir.rglob(name)):
            drafts.extend(_draft_from_csv(path))
            dirs_with_rows.add(path.parent)
    for path in sorted(captures_dir.rglob("normalized.json")):
        if path.parent not in dirs_with_rows:
            try:
                drafts.extend(_draft_from_normalized(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    return drafts


def build_index(registered: Path, captures: Path | None, include_drafts: bool, status: str) -> list[dict[str, Any]]:
    rows = registered_styles(registered)
    registered_by_id = {row["styleId"]: row for row in rows}
    if include_drafts and captures:
        for draft in draft_styles(captures):
            conflict = registered_by_id.get(draft["styleId"])
            if conflict:
                draft["registrationState"] = "conflict"
                draft["conflictsWith"] = {
                    "styleId": conflict["styleId"],
                    "name": conflict["name"],
                    "status": conflict["status"],
                    "sourcePath": conflict["sourcePath"],
                }
            rows.append(draft)
    if status != "all":
        rows = [row for row in rows if _matches_status(row, status)]
    return rows


def _matches_status(row: dict[str, Any], status: str) -> bool:
    if row["status"] == status:
        return True
    conflict = row.get("conflictsWith")
    return (
        row.get("registrationState") == "conflict"
        and isinstance(conflict, dict)
        and conflict.get("status") == status
    )


def _escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|")


def format_table(rows: list[dict[str, Any]]) -> str:
    headers = ["registrationState", "styleId", "styleCategory", "status",
               "preferredMode", "parentStyleId", "sourcePath", "shortSummary"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="list", help="list, show, or a style-id to show")
    parser.add_argument("style_id", nargs="?", help="Style ID for show")
    parser.add_argument("--registered", default=str(script_data_dir() / "styles.csv"))
    parser.add_argument("--captures", default="captures", help="Capture artifact root")
    parser.add_argument("--include-drafts", action="store_true")
    parser.add_argument("--status", choices=["active", "supplemental", "deprecated", "all"], default="all")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    args = parser.parse_args(argv)

    action = args.action
    style_id = args.style_id
    if action not in {"list", "show"}:
        style_id = action
        action = "show"
    if action == "show" and not style_id:
        print("style_index: show requires a style-id", file=sys.stderr)
        return 2

    try:
        rows = build_index(
            Path(args.registered),
            Path(args.captures) if args.include_drafts else None,
            args.include_drafts,
            args.status,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"style_index: {exc}", file=sys.stderr)
        return 1
    if action == "show":
        rows = [row for row in rows if row["styleId"] == style_id]
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(format_table(rows))
    return 0 if rows or action == "list" else 1


if __name__ == "__main__":
    raise SystemExit(main())
