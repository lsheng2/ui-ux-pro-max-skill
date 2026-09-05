#!/usr/bin/env python3
"""Capture structural UI signals into a deterministic capture.json artifact."""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from capture_extractors import (
    DEFAULT_INCLUDE_PATTERNS,
    expand_include_patterns,
    extract_signals,
    iter_project_files,
    read_limited_text,
    third_party_exclusions,
)
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

MAX_URL_BYTES = 1_000_000


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


def _load_project_documents(source: str, includes: list[str] | None, max_files: int) -> list[tuple[str, str]]:
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project source must be a directory: {root}")
    patterns = expand_include_patterns(includes or list(DEFAULT_INCLUDE_PATTERNS))
    documents: list[tuple[str, str]] = []
    for path in iter_project_files(root, patterns, max_files):
        documents.append((path.relative_to(root).as_posix(), read_limited_text(path)))
    if not documents:
        raise ValueError(f"no source files matched include patterns under {root}")
    return documents


def _load_html_document(source: str) -> list[tuple[str, str]]:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"html source must be a file: {path}")
    return [(path.name, read_limited_text(path))]


def _load_url_document(source: str) -> list[tuple[str, str]]:
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


def _documents_for(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.source_kind == "project":
        return _load_project_documents(args.source, args.include, args.max_files)
    if args.source_kind == "html":
        return _load_html_document(args.source)
    return _load_url_document(args.source)


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
