#!/usr/bin/env python3
"""Validate ui-ux-pro-max capture and normalized capture artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from capture_shared import LEGAL_MODES, SIGNAL_GROUPS, SOURCE_KINDS, read_json

ASSET_EXTENSIONS = {
    ".ai", ".avif", ".eot", ".gif", ".ico", ".jpeg", ".jpg", ".otf", ".png",
    ".svg", ".ttf", ".webp", ".woff", ".woff2",
}
FORBIDDEN_EVIDENCE_KEYS = {
    "asset", "assets", "brandasset", "brandassets", "copy", "copytext", "css",
    "csstext", "dom", "domsnapshot", "fontfile", "fontfiles", "fonturl",
    "fullcss", "fulldom", "html", "image", "images", "innerhtml", "logo",
    "logos", "marketingcopy", "outerhtml", "text", "textcontent",
}
SCREENSHOT_PAYLOAD_KEYS = {"base64", "bytes", "content", "data", "imagebytes"}
INLINE_IMAGE_RE = re.compile(r"^[A-Za-z0-9+/=\s]{200,}$")


def _fold_key(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _path_label(path: list[str]) -> str:
    return ".".join(path) or "<root>"


def _valid_source(source: Any, problems: list[str]) -> str | None:
    if not isinstance(source, dict):
        problems.append("source must be an object")
        return None
    kind = source.get("kind")
    value = source.get("value")
    legal_mode = source.get("legalMode")
    if kind not in SOURCE_KINDS:
        problems.append("source.kind must be one of url, project, html")
    if not isinstance(value, str) or not value.strip():
        problems.append("source.value is required")
    if legal_mode not in LEGAL_MODES:
        problems.append("source.legalMode must be owned, internal_reference, or third_party_reference")
        return None
    return legal_mode


def _valid_viewports(viewports: Any, problems: list[str]) -> None:
    if not isinstance(viewports, list) or not viewports:
        problems.append("viewports must be a non-empty array")
        return
    for index, viewport in enumerate(viewports):
        if not isinstance(viewport, dict):
            problems.append(f"viewports[{index}] must be an object")
            continue
        if not isinstance(viewport.get("width"), int) or viewport["width"] <= 0:
            problems.append(f"viewports[{index}].width must be a positive integer")
        if not isinstance(viewport.get("height"), int) or viewport["height"] <= 0:
            problems.append(f"viewports[{index}].height must be a positive integer")
        if not isinstance(viewport.get("label"), str) or not viewport["label"].strip():
            problems.append(f"viewports[{index}].label is required")


def _valid_signals(signals: Any, problems: list[str]) -> None:
    if not isinstance(signals, dict):
        problems.append("signals must be an object")
        return
    for name in SIGNAL_GROUPS:
        if name not in signals:
            problems.append(f"signals.{name} is required")
        elif not isinstance(signals[name], list):
            problems.append(f"signals.{name} must be an array")


def _check_third_party_evidence(value: Any, path: list[str], problems: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            folded = _fold_key(str(key))
            current = [*path, str(key)]
            in_screenshot = "screenshots" in [part.casefold() for part in path]
            if folded in FORBIDDEN_EVIDENCE_KEYS:
                problems.append(
                    f"{_path_label(current)} is not allowed for third_party_reference captures"
                )
            if in_screenshot and folded in SCREENSHOT_PAYLOAD_KEYS:
                problems.append(
                    f"{_path_label(current)} stores screenshot payload bytes; keep only local paths"
                )
            if folded == "path" and not in_screenshot:
                suffix = Path(str(nested)).suffix.casefold()
                if suffix in ASSET_EXTENSIONS:
                    problems.append(
                        f"{_path_label(current)} points at copied asset/font evidence"
                    )
            _check_third_party_evidence(nested, current, problems)
    elif isinstance(value, str):
        lowered_path = [part.casefold() for part in path]
        lowered = value.strip().casefold()
        if "sampledselectors" in lowered_path and any(token in lowered for token in (".logo", "#logo", " brand", ".brand", "#brand")):
            problems.append(
                f"{_path_label(path)} contains brand/logo selector evidence"
            )
        if "screenshots" in lowered_path and (
            lowered.startswith("data:")
            or lowered.startswith("data:image/")
            or INLINE_IMAGE_RE.fullmatch(value.strip())
        ):
            problems.append(
                f"{_path_label(path)} stores inline screenshot payload; keep only local paths"
            )
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _check_third_party_evidence(nested, [*path, str(index)], problems)


def validate_capture_artifact(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if payload.get("schemaVersion") != 1:
        problems.append("schemaVersion must be 1")
    if not isinstance(payload.get("captureId"), str) or not payload["captureId"].strip():
        problems.append("captureId is required")
    if not isinstance(payload.get("capturedAt"), str) or not payload["capturedAt"].strip():
        problems.append("capturedAt is required")
    legal_mode = _valid_source(payload.get("source"), problems)
    _valid_viewports(payload.get("viewports"), problems)
    _valid_signals(payload.get("signals"), problems)
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        problems.append("evidence must be an object")
    else:
        for key in ("screenshots", "sampledSelectors", "sourceFiles"):
            if key not in evidence:
                problems.append(f"evidence.{key} is required")
            elif not isinstance(evidence[key], list):
                problems.append(f"evidence.{key} must be an array")
    if not isinstance(payload.get("exclusions"), list):
        problems.append("exclusions must be an array")
    if legal_mode == "third_party_reference":
        _check_third_party_evidence(evidence, ["evidence"], problems)
    return problems


def validate_normalized_artifact(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if payload.get("schemaVersion") != 1:
        problems.append("schemaVersion must be 1")
    if not isinstance(payload.get("captureId"), str) or not payload["captureId"].strip():
        problems.append("captureId is required")
    legal_mode = payload.get("legalMode")
    if legal_mode not in LEGAL_MODES:
        problems.append("legalMode must be owned, internal_reference, or third_party_reference")
    for key in ("selectedTokens", "structuralSignals", "recommendedStyleId"):
        if not isinstance(payload.get(key), dict):
            problems.append(f"{key} must be an object")
    if not isinstance(payload.get("excludedSignals"), list):
        problems.append("excludedSignals must be an array")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        problems.append("confidence must be a number between 0 and 1")
    if legal_mode == "third_party_reference":
        _check_third_party_evidence(payload.get("evidence", {}), ["evidence"], problems)
    return problems


def validate_path(path: Path) -> list[str]:
    payload = read_json(path)
    if "source" in payload and "signals" in payload:
        return validate_capture_artifact(payload)
    if "selectedTokens" in payload and "structuralSignals" in payload:
        return validate_normalized_artifact(payload)
    return [f"{path} is neither a capture.json nor normalized.json artifact"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="capture.json or normalized.json files to validate")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    results = []
    for raw_path in args.paths:
        path = Path(raw_path)
        try:
            errors = validate_path(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors = [str(exc)]
        results.append({"path": str(path), "valid": not errors, "errors": errors})

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
