#!/usr/bin/env python3
"""Capture structural UI signals into a deterministic capture.json artifact."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from capture_browser import load_url_document
from capture_extractors import DEFAULT_INCLUDE_PATTERNS, extract_signals, third_party_exclusions
from capture_project import load_html_document, load_project_documents
from capture_shared import (
    CAPTURE_SCHEMA_VERSION,
    DEFAULT_VIEWPORTS,
    LEGAL_MODES,
    SOURCE_KINDS,
    slugify,
    utc_now,
    write_json,
)
from validate_capture import validate_capture_artifact


def _parse_viewport(raw: str) -> dict[str, int | str]:
    size, _, label = raw.partition(":")
    width, sep, height = size.lower().partition("x")
    if not sep:
        raise argparse.ArgumentTypeError("viewport must use WIDTHxHEIGHT[:label]")
    try:
        parsed = {"width": int(width), "height": int(height), "label": label or size}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("viewport width and height must be integers") from exc
    if parsed["width"] <= 0 or parsed["height"] <= 0:
        raise argparse.ArgumentTypeError("viewport width and height must be positive")
    return parsed


def _documents_for(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.source_kind == "project":
        return load_project_documents(args.source, args.include, args.max_files)
    if args.source_kind == "html":
        return load_html_document(args.source)
    return load_url_document(args.source)


def build_capture(args: argparse.Namespace) -> dict:
    documents = _documents_for(args)
    signals, selectors, source_files = extract_signals(documents)
    for item in signals["colors"]:
        item.setdefault("kind", "raw-sample")

    exclusions: list[dict[str, str]] = []
    if args.legal_mode == "third_party_reference":
        exclusions.extend(third_party_exclusions(text for _, text in documents))
        selectors = [
            selector for selector in selectors
            if not re.search(r"\b(?:brand|logo)\b", selector, re.I)
        ]

    return {
        "schemaVersion": CAPTURE_SCHEMA_VERSION,
        "captureId": slugify(args.name or args.source),
        "capturedAt": utc_now(),
        "source": {
            "kind": args.source_kind,
            "value": args.source,
            "legalMode": args.legal_mode,
        },
        "viewports": args.viewport or list(DEFAULT_VIEWPORTS),
        "signals": signals,
        "evidence": {
            "screenshots": [],
            "sampledSelectors": selectors,
            "sourceFiles": source_files,
        },
        "exclusions": exclusions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="URL, local HTML file, or project directory")
    parser.add_argument("--source-kind", required=True, choices=sorted(SOURCE_KINDS))
    parser.add_argument("--legal-mode", required=True, choices=sorted(LEGAL_MODES))
    parser.add_argument("--name", required=True, help="Human-readable capture name")
    parser.add_argument("--out", required=True, help="Path to write capture.json")
    parser.add_argument("--include", action="append", help="Project include glob; repeatable")
    parser.add_argument("--max-files", type=int, default=120)
    parser.add_argument(
        "--viewport",
        action="append",
        type=_parse_viewport,
        help="Viewport as WIDTHxHEIGHT[:label]; repeatable",
    )
    args = parser.parse_args(argv)

    try:
        capture = build_capture(args)
        errors = validate_capture_artifact(capture)
        if errors:
            raise ValueError("; ".join(errors))
        out = Path(args.out)
        write_json(out, capture)
    except (OSError, ValueError) as exc:
        print(f"capture: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote capture artifact: {out}")
    print("Capture is complete. Should this style be automatically named and registered as a supplemental catalog style, or kept as a draft?")
    print("Options: keep draft | name and register")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
