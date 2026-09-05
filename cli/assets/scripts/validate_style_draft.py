#!/usr/bin/env python3
"""Validate ui-ux-pro-max draft style rows and draft provenance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from capture_shared import LEGAL_MODES, STYLE_HEADERS, STYLE_STATUSES, read_csv_rows, read_json

STYLE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_style_row(row: dict[str, str], *, register_ready: bool = False) -> list[str]:
    problems: list[str] = []
    style_id = row.get("Style ID", "")
    if not STYLE_ID_RE.fullmatch(style_id):
        problems.append(f"invalid Style ID: {style_id!r}")
    if not row.get("Style Category", "").strip():
        problems.append("Style Category is required")
    if row.get("Status") not in STYLE_STATUSES:
        problems.append("Status must be active, supplemental, or deprecated")
    if row.get("Preferred Mode") not in {"auto", "light", "dark"}:
        problems.append("Preferred Mode must be auto, light, or dark")
    if len(row.get("AI Prompt Keywords", "").split()) > 40:
        problems.append("AI Prompt Keywords must be <= 40 words")
    if register_ready and row.get("Status") == "supplemental" and not row.get("Parent Style ID", "").strip():
        problems.append("register-ready supplemental rows require Parent Style ID")
    return problems


def validate_draft_csv(path: Path, *, register_ready: bool = False) -> list[str]:
    headers, rows = read_csv_rows(path)
    problems: list[str] = []
    missing = [header for header in STYLE_HEADERS if header not in headers]
    if missing:
        problems.append(f"{path} missing styles.csv headers: {', '.join(missing)}")
    if not rows:
        problems.append(f"{path} must contain at least one draft row")
    for index, row in enumerate(rows, start=2):
        for problem in validate_style_row(row, register_ready=register_ready):
            problems.append(f"{path}:{index}: {problem}")
    return problems


def validate_provenance(path: Path) -> list[str]:
    payload = read_json(path)
    problems: list[str] = []
    records = payload.get("records")
    if payload.get("schemaVersion") != 1 or not isinstance(records, list) or not records:
        return [f"{path} must contain schemaVersion 1 and a non-empty records array"]
    for index, record in enumerate(records):
        label = f"{path}:records[{index}]"
        if record.get("entityKind") != "style":
            problems.append(f"{label}: entityKind must be style")
        if record.get("sourceFile") != "styles.csv":
            problems.append(f"{label}: sourceFile must be styles.csv")
        if not isinstance(record.get("sourceKey"), dict) or not record["sourceKey"].get("Style ID"):
            problems.append(f"{label}: sourceKey.Style ID is required")
        if record.get("legalMode") not in LEGAL_MODES:
            problems.append(f"{label}: legalMode is required")
        if not isinstance(record.get("appliesTo"), list) or not record["appliesTo"]:
            problems.append(f"{label}: appliesTo must be non-empty")
        confidence = record.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
            problems.append(f"{label}: confidence must be 0..1")
        if not isinstance(record.get("sources"), list) or not record["sources"]:
            problems.append(f"{label}: sources must be non-empty")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft_csv", help="style-row.draft.csv or style-row.csv")
    parser.add_argument("--provenance", help="Optional provenance.draft.json")
    parser.add_argument("--register-ready", action="store_true", help="Require fields needed before catalog apply")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    results: list[dict[str, Any]] = []
    try:
        draft_errors = validate_draft_csv(Path(args.draft_csv), register_ready=args.register_ready)
        results.append({"path": args.draft_csv, "valid": not draft_errors, "errors": draft_errors})
        if args.provenance:
            provenance_errors = validate_provenance(Path(args.provenance))
            results.append({"path": args.provenance, "valid": not provenance_errors, "errors": provenance_errors})
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        results.append({"path": args.draft_csv, "valid": False, "errors": [str(exc)]})

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            if result["valid"]:
                print(f"OK: {result['path']}")
            else:
                print(f"INVALID: {result['path']}", file=sys.stderr)
                for error in result["errors"]:
                    print(f"  - {error}", file=sys.stderr)
    return 0 if all(result["valid"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
