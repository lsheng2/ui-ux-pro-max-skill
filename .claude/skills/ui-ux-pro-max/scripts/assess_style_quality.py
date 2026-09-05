#!/usr/bin/env python3
"""Assess capture-derived style readiness before registration or update."""

from __future__ import annotations

import argparse
import json
import re
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

from capture_shared import read_csv_rows, read_json, write_json

TEMPLATE_PHRASES = (
    "implementations based on normalized structural capture signals",
    "captured structural reference",
    "captured structural tokens",
)
TEXT_CONTRAST_MIN = 4.5


def _hex_colors(value: str) -> list[str]:
    return [match.group(0).lower() for match in re.finditer(r"#[0-9a-fA-F]{6}\b", value or "")]


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    text = color.lstrip("#")
    red, green, blue = (int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return round((high + 0.05) / (low + 0.05), 2)


def _score_from_issues(issues: list[str], *, base: float = 1.0, penalty: float = 0.2) -> float:
    return round(max(0.0, base - len(issues) * penalty), 2)


def _file_digest(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    return sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path | None) -> str:
    if not path:
        return ""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.name


def _first_row(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    _, rows = read_csv_rows(path)
    return rows[0] if rows else {}


def _find_registered_row(path: Path | None, style_id: str) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    _, rows = read_csv_rows(path)
    return next((row for row in rows if row.get("Style ID") == style_id), {})


def _design_var_names(row: dict[str, str]) -> list[str]:
    names = []
    for part in row.get("Design System Variables", "").split(";"):
        name, sep, _ = part.strip().partition(":")
        if sep and name:
            names.append(name)
    return names


def _traceability(normalized_path: Path, capture_path: Path | None, provenance_path: Path | None) -> tuple[float, list[str], dict[str, Any]]:
    issues: list[str] = []
    evidence = {
        "normalizedPath": _display_path(normalized_path),
        "normalizedSha256": _file_digest(normalized_path),
        "capturePath": _display_path(capture_path),
        "captureSha256": _file_digest(capture_path),
        "provenancePath": _display_path(provenance_path),
        "provenanceSha256": _file_digest(provenance_path),
    }
    normalized = read_json(normalized_path)
    capture = read_json(capture_path) if capture_path and capture_path.exists() else None
    if not capture:
        issues.append("capture artifact is missing")
    elif capture.get("captureId") != normalized.get("captureId"):
        issues.append("captureId mismatch between capture and normalized artifacts")
    if provenance_path and provenance_path.exists():
        provenance = read_json(provenance_path)
        refs = [source.get("ref", "") for record in provenance.get("records", []) for source in record.get("sources", []) if isinstance(source, dict)]
        if not refs:
            issues.append("provenance has no source refs")
        elif not any(normalized_path.name in ref for ref in refs):
            issues.append("provenance does not reference the normalized artifact")
    else:
        issues.append("provenance draft is missing")
    return _score_from_issues(issues, penalty=0.25), issues, evidence


def _semantic(row: dict[str, str]) -> tuple[float, list[str]]:
    issues: list[str] = []
    for field in ("Best For", "Do Not Use For", "AI Prompt Keywords", "CSS/Technical Keywords", "Implementation Checklist"):
        text = row.get(field, "").strip()
        if not text:
            issues.append(f"{field} is empty")
        if any(phrase in text.casefold() for phrase in TEMPLATE_PHRASES):
            issues.append(f"{field} still contains template capture wording")
    if len(row.get("Best For", "").split()) < 6:
        issues.append("Best For is too short to guide reuse")
    if len(row.get("Do Not Use For", "").split()) < 6:
        issues.append("Do Not Use For is too short to set boundaries")
    return _score_from_issues(issues, penalty=0.14), issues


def _token_quality(row: dict[str, str]) -> tuple[float, list[str]]:
    issues: list[str] = []
    names = _design_var_names(row)
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        issues.append("duplicate design variables: " + ", ".join(duplicates))
    if not names:
        issues.append("Design System Variables has no token assignments")
    if any(re.fullmatch(r"--(?:color|space|radius|typography|shadow|motion)-\d+", name) for name in names):
        issues.append("Design System Variables uses positional token names instead of semantic roles")
    for part in row.get("Design System Variables", "").split(";"):
        name, sep, value = part.strip().partition(":")
        if not sep:
            continue
        value = value.strip()
        if name.startswith("--font-") and not name.startswith("--font-size") and re.fullmatch(r"-?\d+(?:\.\d+)?(?:px|rem|em|%)", value):
            issues.append("font family token contains a font-size value")
        if name.startswith("--font-size") and not re.fullmatch(r"-?\d+(?:\.\d+)?(?:px|rem|em|%)", value):
            issues.append("font-size token contains a non-size value")
    raw_color_keywords = [value for value in row.get("Keywords", "").split(",") if re.fullmatch(r"\s*[0-9a-fA-F]{6}\s*", value)]
    if raw_color_keywords:
        issues.append("Keywords include raw hex fragments instead of semantic words")
    return _score_from_issues(issues, penalty=0.18), issues


def _contrast(row: dict[str, str]) -> tuple[float, list[str], list[dict[str, Any]]]:
    colors = []
    for field in ("Primary Colors", "Secondary Colors", "Design System Variables"):
        for color in _hex_colors(row.get(field, "")):
            if color not in colors:
                colors.append(color)
    pairs: list[dict[str, Any]] = []
    passing = 0
    for index, foreground in enumerate(colors):
        for background in colors[index + 1:]:
            ratio = contrast_ratio(foreground, background)
            passes = ratio >= TEXT_CONTRAST_MIN
            passing += int(passes)
            pairs.append({
                "foreground": foreground,
                "background": background,
                "ratio": ratio,
                "passesTextAA": passes,
            })
    issues = [] if passing >= 2 else ["fewer than two color pairs meet 4.5:1 text contrast"]
    score = round(min(1.0, passing / 2), 2) if pairs else 0.0
    if not pairs:
        issues.append("no hex color pairs available for contrast assessment")
    return score, issues, sorted(pairs, key=lambda item: item["ratio"], reverse=True)[:8]


def _searchability(row: dict[str, str], registered_row: dict[str, str]) -> tuple[float, list[str]]:
    issues: list[str] = []
    style_id = row.get("Style ID", "")
    if registered_row and registered_row.get("Style ID") != style_id:
        issues.append("registered lookup did not resolve this style id")
    if not style_id:
        issues.append("Style ID is empty")
    if not row.get("Aliases", "").strip():
        issues.append("Aliases are empty, so alias search cannot help recall")
    keywords = [part.strip() for part in row.get("Keywords", "").split(",") if part.strip()]
    if len([item for item in keywords if not re.fullmatch(r"[0-9a-fA-F]{6}", item)]) < 6:
        issues.append("not enough semantic keywords for natural-language recall")
    return _score_from_issues(issues, penalty=0.2), issues


def readiness(scores: dict[str, float], issues: dict[str, list[str]]) -> str:
    if scores["traceabilityScore"] <= 0.75 or issues["tokens"] or issues["semantic"]:
        return "draft-only"
    if min(scores.values()) >= 0.8 and not any(issues.values()):
        return "recommendable"
    return "registerable"


def assess_quality(
    normalized_path: Path,
    *,
    capture_path: Path | None = None,
    draft_path: Path | None = None,
    provenance_path: Path | None = None,
    registered_path: Path | None = None,
    style_id: str = "",
) -> dict[str, Any]:
    normalized_path = normalized_path.resolve()
    capture_path = capture_path.resolve() if capture_path else normalized_path.with_name("capture.json")
    draft_path = draft_path.resolve() if draft_path else normalized_path.with_name("style-row.draft.csv")
    provenance_path = provenance_path.resolve() if provenance_path else normalized_path.with_name("provenance.draft.json")
    row = _first_row(draft_path)
    style_id = style_id or row.get("Style ID", "")
    registered_row = _find_registered_row(registered_path, style_id)

    trace_score, trace_issues, evidence = _traceability(normalized_path, capture_path, provenance_path)
    semantic_score, semantic_issues = _semantic(row)
    token_score, token_issues = _token_quality(row)
    contrast_score, contrast_issues, contrast_pairs = _contrast(row)
    search_score, search_issues = _searchability(row, registered_row)
    scores = {
        "traceabilityScore": trace_score,
        "semanticScore": semantic_score,
        "tokenScore": token_score,
        "contrastScore": contrast_score,
        "searchabilityScore": search_score,
    }
    issues = {
        "traceability": trace_issues,
        "semantic": semantic_issues,
        "tokens": token_issues,
        "contrast": contrast_issues,
        "searchability": search_issues,
    }
    return {
        "schemaVersion": 1,
        "styleId": style_id,
        "readiness": readiness(scores, issues),
        "scores": scores,
        "issues": issues,
        "evidence": evidence,
        "contrastPairs": contrast_pairs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("normalized", help="Path to normalized.json")
    parser.add_argument("--capture", help="Path to capture.json; defaults next to normalized.json")
    parser.add_argument("--draft", help="Path to style-row.draft.csv; defaults next to normalized.json")
    parser.add_argument("--provenance", help="Path to provenance.draft.json; defaults next to normalized.json")
    parser.add_argument("--registered", help="Optional registered styles.csv for lookup")
    parser.add_argument("--style-id", default="")
    parser.add_argument("--out", help="Path to write quality-report.json")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        report = assess_quality(
            Path(args.normalized),
            capture_path=Path(args.capture) if args.capture else None,
            draft_path=Path(args.draft) if args.draft else None,
            provenance_path=Path(args.provenance) if args.provenance else None,
            registered_path=Path(args.registered) if args.registered else None,
            style_id=args.style_id,
        )
        out = Path(args.out) if args.out else Path(args.normalized).with_name("quality-report.json")
        write_json(out, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"assess_style_quality: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Quality readiness: {report['readiness']} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())