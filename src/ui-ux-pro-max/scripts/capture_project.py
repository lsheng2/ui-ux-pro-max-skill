#!/usr/bin/env python3
"""Project and local-HTML capture adapters for ui-ux-pro-max."""

from __future__ import annotations

from pathlib import Path

from capture_extractors import DEFAULT_INCLUDE_PATTERNS, expand_include_patterns, iter_project_files, read_limited_text


def load_project_documents(source: str, includes: list[str] | None, max_files: int) -> list[tuple[str, str]]:
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


def load_html_document(source: str) -> list[tuple[str, str]]:
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"html source must be a file: {path}")
    return [(path.name, read_limited_text(path))]
