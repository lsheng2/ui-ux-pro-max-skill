#!/usr/bin/env python3
"""Generate or explicitly register a styles.csv row from normalized capture data."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from capture_shared import (
    STYLE_HEADERS,
    STYLE_STATUSES,
    read_csv_rows,
    read_json,
    slugify,
    title_from_slug,
    utc_now,
    word_limited,
    write_csv_rows,
    write_json,
)
from validate_capture import validate_normalized_artifact
from validate_style_draft import validate_draft_csv, validate_provenance

GENERATED_DATA_DIR_MARKERS = (
    "/.agents/skills/ui-ux-pro-max/data",
    "/.augment/skills/ui-ux-pro-max/data",
    "/.claude/skills/ui-ux-pro-max/data",
    "/.codebuddy/skills/ui-ux-pro-max/data",
    "/.codewhale/skills/ui-ux-pro-max/data",
    "/.continue/skills/ui-ux-pro-max/data",
    "/.cursor/skills/ui-ux-pro-max/data",
    "/.factory/skills/ui-ux-pro-max/data",
    "/.gemini/skills/ui-ux-pro-max/data",
    "/.github/prompts/ui-ux-pro-max/data",
    "/.kilocode/skills/ui-ux-pro-max/data",
    "/.kiro/steering/ui-ux-pro-max/data",
    "/.opencode/skills/ui-ux-pro-max/data",
    "/.qoder/skills/ui-ux-pro-max/data",
    "/.roo/skills/ui-ux-pro-max/data",
    "/.trae/skills/ui-ux-pro-max/data",
    "/.warp/skills/ui-ux-pro-max/data",
    "/.windsurf/skills/ui-ux-pro-max/data",
    "/cli/assets/data",
)


def _token_values(normalized: dict[str, Any], group: str, limit: int = 6) -> list[str]:
    tokens = normalized.get("selectedTokens", {}).get(group, [])
    values = []
    for item in tokens:
        if isinstance(item, dict):
            value = item.get("value")
            if value:
                values.append(str(value))
    return values[:limit]


def _structural_values(normalized: dict[str, Any], group: str, limit: int = 5) -> list[str]:
    rows = normalized.get("structuralSignals", {}).get(group, [])
    values = []
    for item in rows:
        if isinstance(item, dict):
            value = item.get("value")
            if value:
                values.append(str(value))
    return values[:limit]


def _design_vars(normalized: dict[str, Any]) -> str:
    pairs: list[str] = []
    for group in ("colors", "typography", "spacing", "radius", "shadows", "motion"):
        for item in normalized.get("selectedTokens", {}).get(group, [])[:4]:
            if isinstance(item, dict) and item.get("name") and item.get("value"):
                pairs.append(f"{item['name']}: {item['value']}")
    return "; ".join(pairs) or "--capture-review-required: true"


def _csv_technical_keywords(normalized: dict[str, Any]) -> str:
    parts = []
    components = _structural_values(normalized, "components")
    layout = _structural_values(normalized, "layout")
    colors = _token_values(normalized, "colors", 4)
    spacing = _token_values(normalized, "spacing", 4)
    if components:
        parts.append("components: " + ", ".join(components))
    if layout:
        parts.append("layout: " + ", ".join(layout))
    if colors:
        parts.append("colors: " + ", ".join(colors))
    if spacing:
        parts.append("spacing: " + ", ".join(spacing))
    return "; ".join(parts) or "captured structural tokens; review before implementation"


def _preferred_mode(normalized: dict[str, Any]) -> str:
    colors = " ".join(_token_values(normalized, "colors", 12)).casefold()
    if any(value in colors for value in ("#000", "#000000", "#0", "#111", "#121212")):
        return "dark"
    return "auto"


def _prompt_keywords(style_name: str, normalized: dict[str, Any]) -> str:
    parts = [style_name, "captured structural reference", "tokenized UI"]
    parts.extend(_structural_values(normalized, "components", 4))
    parts.extend(_structural_values(normalized, "layout", 3))
    if _token_values(normalized, "spacing", 2):
        parts.append("consistent spacing")
    if _token_values(normalized, "radius", 1):
        parts.append("rounded controls")
    prompt = ", ".join(dict.fromkeys(part for part in parts if part))
    return word_limited(prompt, 40)


def _next_no(rows: list[dict[str, str]]) -> str:
    numbers = [int(row["No"]) for row in rows if row.get("No", "").isdigit()]
    return str(max(numbers, default=0) + 1)


def build_style_row(
    normalized: dict[str, Any],
    *,
    style_id: str,
    style_name: str,
    status: str,
    parent_style_id: str,
    aliases: str,
) -> dict[str, str]:
    legal_mode = normalized.get("legalMode")
    do_not_use = "Copying logos, images, proprietary fonts, full CSS/DOM, marketing copy, or brand identity."
    if legal_mode == "owned":
        do_not_use = "Using one captured screen as a universal product system without review."
    components = _structural_values(normalized, "components")
    layout = _structural_values(normalized, "layout")
    keywords = ", ".join(dict.fromkeys([
        "captured", "reference", "tokenized", *components, *layout,
        *[slugify(value, value) for value in _token_values(normalized, "colors", 3)],
    ]))
    return {
        "No": "",
        "Style Category": style_name,
        "Type": "General",
        "Keywords": keywords,
        "Primary Colors": ", ".join(_token_values(normalized, "colors", 4)) or "Captured semantic color tokens pending review",
        "Secondary Colors": ", ".join(_token_values(normalized, "colors", 8)[4:]) or "Captured secondary tokens pending review",
        "Effects & Animation": "; ".join(_token_values(normalized, "shadows", 3) + _token_values(normalized, "motion", 3)) or "Captured motion and elevation pending review",
        "Best For": f"{style_name} implementations based on normalized structural capture signals",
        "Do Not Use For": do_not_use,
        "Light Mode ✓": "conditional",
        "Dark Mode ✓": "conditional",
        "Performance": "cost:moderate|drivers:animation,blur",
        "Accessibility": "risk:conditional|requires:contrast-text-4.5,keyboard,visible-focus,reduced-motion",
        "Mobile-Friendly": "adaptable",
        "Conversion-Focused": "◐ Medium",
        "Framework Compatibility": "html-tailwind|react|vue|svelte|custom",
        "Era/Origin": f"Captured {date.today().year}",
        "Complexity": "Medium",
        "AI Prompt Keywords": _prompt_keywords(style_name, normalized),
        "CSS/Technical Keywords": _csv_technical_keywords(normalized),
        "Implementation Checklist": (
            "Review normalized tokens; map values to semantic design variables; "
            "verify contrast, keyboard focus, responsive density, and reduced motion; "
            "do not copy excluded brand or asset evidence"
        ),
        "Design System Variables": _design_vars(normalized),
        "Style ID": style_id,
        "Aliases": aliases,
        "Status": status,
        "Parent Style ID": parent_style_id,
        "Replacement Domain": "",
        "Replacement ID": "",
        "Preferred Mode": _preferred_mode(normalized),
    }


def provenance_record(normalized_path: Path, normalized: dict[str, Any], row: dict[str, str]) -> dict[str, Any]:
    ref = f"captures/{normalized_path.parent.name}/{normalized_path.name}#captureId={normalized['captureId']}"
    return {
        "entityKind": "style",
        "entityId": row["Style ID"],
        "sourceFile": "styles.csv",
        "sourceKey": {"Style ID": row["Style ID"]},
        "legalMode": normalized.get("legalMode"),
        "status": row["Status"],
        "verifiedAt": date.today().isoformat(),
        "sla": "needs-review",
        "appliesTo": ["style-search", "gallery"],
        "confidence": normalized.get("confidence", 0.5),
        "sources": [{"type": "derived", "ref": ref}],
    }


def _write_draft(row: dict[str, str], out: Path) -> None:
    write_csv_rows(out, STYLE_HEADERS, [row])


def _update_catalog_summary(data_dir: Path, rows: list[dict[str, str]]) -> None:
    path = data_dir / "catalog-summary.json"
    summary = read_json(path) if path.exists() else {"schemaVersion": 1, "verifiedAt": date.today().isoformat(), "counts": {}}
    counts = summary.setdefault("counts", {})
    counts["styles"] = {
        "total": len(rows),
        "searchable": sum(row.get("Status") != "deprecated" for row in rows),
        "active": sum(row.get("Status") == "active" for row in rows),
        "supplemental": sum(row.get("Status") == "supplemental" for row in rows),
        "deprecated": sum(row.get("Status") == "deprecated" for row in rows),
    }
    write_json(path, summary)


def _update_provenance(data_dir: Path, record: dict[str, Any]) -> None:
    path = data_dir / "data-provenance.json"
    payload = read_json(path) if path.exists() else {"schemaVersion": 1, "records": []}
    payload.setdefault("generatedAt", utc_now())
    records = payload.setdefault("records", [])
    if any(item.get("entityKind") == "style" and item.get("entityId") == record["entityId"] for item in records):
        raise ValueError(f"provenance already contains style {record['entityId']}")
    records.append(record)
    write_json(path, payload)


def _assert_apply_allowed(row: dict[str, str], data_dir: Path, rows: list[dict[str, str]]) -> None:
    normalized_dir = str(data_dir.resolve()).replace("\\", "/").casefold()
    if any(marker in normalized_dir for marker in GENERATED_DATA_DIR_MARKERS):
        raise ValueError("--data-dir must point at the source-of-truth data directory, not an installed or generated mirror")
    if row["Style ID"] in {existing.get("Style ID") for existing in rows}:
        raise ValueError(f"style {row['Style ID']} is already registered")
    by_id = {existing.get("Style ID"): existing for existing in rows}
    if row["Status"] == "supplemental":
        parent = row["Parent Style ID"]
        if not parent:
            raise ValueError("--parent-style-id is required before applying a supplemental style")
        if parent not in by_id:
            raise ValueError(f"--parent-style-id does not exist: {parent}")
        if by_id[parent].get("Status") != "active":
            raise ValueError(f"--parent-style-id must target an active style: {parent}")
    provenance_path = data_dir / "data-provenance.json"
    if provenance_path.exists():
        payload = read_json(provenance_path)
        records = payload.get("records", [])
        if any(item.get("entityKind") == "style" and item.get("entityId") == row["Style ID"] for item in records):
            raise ValueError(f"provenance already contains style {row['Style ID']}")


def _apply_row(row: dict[str, str], data_dir: Path, record: dict[str, Any]) -> None:
    styles_path = data_dir / "styles.csv"
    headers, rows = read_csv_rows(styles_path)
    _assert_apply_allowed(row, data_dir, rows)
    row["No"] = _next_no(rows)
    write_csv_rows(styles_path, headers or STYLE_HEADERS, [*rows, row])
    _update_catalog_summary(data_dir, [*rows, row])
    _update_provenance(data_dir, record)


def _run_command(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        details = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        raise ValueError(f"post-apply validation failed: {' '.join(command)}\n{details}")


def _run_post_apply_validation(data_dir: Path, row: dict[str, str]) -> None:
    source_root = data_dir.parent
    repo_root = source_root.parent.parent
    scripts_dir = source_root / "scripts"
    validate_data = scripts_dir / "validate_data.py"
    search = scripts_dir / "search.py"
    catalog_summary = repo_root / "scripts" / "generate-catalog-summary.py"
    if not validate_data.exists() or not search.exists():
        raise ValueError("post-apply validation requires a source tree with scripts/validate_data.py and scripts/search.py")
    _run_command([sys.executable, str(validate_data)], repo_root)
    if catalog_summary.exists():
        _run_command([sys.executable, str(catalog_summary), "--check"], repo_root)
    exact = subprocess.run(
        [sys.executable, str(search), row["Style ID"], "--domain", "style", "--json"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if exact.returncode != 0:
        raise ValueError(f"exact style-id search failed: {exact.stderr.strip()}")
    payload = json.loads(exact.stdout)
    if payload.get("count") != 1 or payload["results"][0].get("Style ID") != row["Style ID"]:
        raise ValueError(f"exact style-id search did not return {row['Style ID']}")
    aliases = [alias.strip() for alias in row.get("Aliases", "").split("|") if alias.strip()]
    if aliases:
        alias = subprocess.run(
            [sys.executable, str(search), aliases[0], "--domain", "style", "--json"],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if alias.returncode != 0:
            raise ValueError(f"alias style search failed: {alias.stderr.strip()}")
        alias_payload = json.loads(alias.stdout)
        if alias_payload.get("count") != 1 or alias_payload["results"][0].get("Style ID") != row["Style ID"]:
            raise ValueError(f"alias search did not return {row['Style ID']}")
    negative = subprocess.run(
        [sys.executable, str(search), "sourdough starter crumb fermentation", "--domain", "style", "--json"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if negative.returncode != 0:
        raise ValueError(f"negative style search failed: {negative.stderr.strip()}")
    negative_payload = json.loads(negative.stdout)
    if any(result.get("Style ID") == row["Style ID"] for result in negative_payload.get("results", [])):
        raise ValueError("negative style search returned the newly registered style")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normalized", help="Path to normalized.json")
    parser.add_argument("--style-id", help="Style ID for the generated row")
    parser.add_argument("--style-name", help="Human readable Style Category")
    parser.add_argument("--status", choices=sorted(STYLE_STATUSES), default=None)
    parser.add_argument("--parent-style-id", default="")
    parser.add_argument("--aliases", default="")
    parser.add_argument("--out", help="Draft CSV path; defaults to style-row.draft.csv next to normalized.json")
    parser.add_argument("--provenance-out", help="Draft provenance JSON path")
    parser.add_argument("--data-dir", help="Source-of-truth catalog data directory; required with --apply")
    parser.add_argument("--apply", action="store_true", help="Append to data/styles.csv and provenance after confirmation")
    parser.add_argument("--confirm", help="Required with --apply; must equal the final style id")
    parser.add_argument("--skip-post-apply-validation", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    normalized_path = Path(args.normalized)
    try:
        normalized = read_json(normalized_path)
        errors = validate_normalized_artifact(normalized)
        if errors:
            raise ValueError("; ".join(errors))
        candidate = normalized["recommendedStyleId"]
        style_id = slugify(args.style_id or candidate.get("candidate") or normalized["captureId"])
        style_name = args.style_name or title_from_slug(style_id)
        status = args.status or "supplemental"
        row = build_style_row(
            normalized,
            style_id=style_id,
            style_name=style_name,
            status=status,
            parent_style_id=args.parent_style_id,
            aliases=args.aliases,
        )
        if len(row["AI Prompt Keywords"].split()) > 40:
            raise ValueError("AI Prompt Keywords exceeds 40 words")
        out = Path(args.out) if args.out else normalized_path.with_name("style-row.draft.csv")
        _write_draft(row, out)
        record = provenance_record(normalized_path, normalized, row)
        provenance_out = Path(args.provenance_out) if args.provenance_out else normalized_path.with_name("provenance.draft.json")
        write_json(provenance_out, {"schemaVersion": 1, "generatedAt": utc_now(), "records": [record]})
        draft_errors = validate_draft_csv(out)
        provenance_errors = validate_provenance(provenance_out)
        if draft_errors or provenance_errors:
            raise ValueError("; ".join(draft_errors + provenance_errors))
        if args.apply:
            if args.confirm != style_id:
                raise ValueError(f"--apply requires --confirm {style_id}")
            if not args.data_dir:
                raise ValueError("--apply requires --data-dir pointing at the source-of-truth catalog data directory")
            _apply_row(row, Path(args.data_dir), record)
            if not args.skip_post_apply_validation:
                _run_post_apply_validation(Path(args.data_dir), row)
            print(f"Registered style {style_id} into {Path(args.data_dir) / 'styles.csv'}")
        else:
            print(f"Wrote draft style row: {out}")
            print(f"Wrote draft provenance: {provenance_out}")
    except (OSError, ValueError, csv.Error) as exc:
        print(f"style_from_capture: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
