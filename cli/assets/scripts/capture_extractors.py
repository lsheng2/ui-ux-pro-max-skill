#!/usr/bin/env python3
"""Stdlib-only signal extraction for ui-ux-pro-max captures."""

from __future__ import annotations

import fnmatch
import re
from collections import Counter
from pathlib import Path
from typing import Iterable

from capture_shared import counter_items, relpath_or_name

DEFAULT_INCLUDE_PATTERNS = (
    "*.css", "*.html", "*.htm", "*.jsx", "*.tsx", "*.js", "*.ts", "*.vue",
    "*.svelte", "**/*.css", "**/*.html", "**/*.htm", "**/*.jsx", "**/*.tsx",
    "**/*.js", "**/*.ts", "**/*.vue", "**/*.svelte",
)
EXCLUDED_DIRS = {
    ".git", ".hg", ".next", ".nuxt", ".svelte-kit", ".venv", "__pycache__",
    "build", "coverage", "dist", "node_modules", "out", "target", "vendor",
}
MAX_FILE_BYTES = 262_144
COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|"
    r"\b(?:rgb|rgba|hsl|hsla)\(\s*[^)]+\)",
)
SPACING_PROP_RE = re.compile(
    r"\b(?:margin|padding|gap|inset|top|right|bottom|left|width|height|min-width|max-width)"
    r"(?:-[a-z-]+)?\s*:\s*([^;{}]+)",
    re.I,
)
RADIUS_RE = re.compile(r"\bborder-radius\s*:\s*([^;{}]+)", re.I)
SHADOW_RE = re.compile(r"\bbox-shadow\s*:\s*([^;{}]+)", re.I)
MOTION_RE = re.compile(
    r"\b(?:transition(?:-[a-z-]+)?|animation(?:-[a-z-]+)?)\s*:\s*([^;{}]+)",
    re.I,
)
FONT_FAMILY_RE = re.compile(r"\bfont-family\s*:\s*([^;{}]+)", re.I)
FONT_SIZE_RE = re.compile(r"\bfont-size\s*:\s*([^;{}]+)", re.I)
CSS_SELECTOR_RE = re.compile(r"(^|[}\n])\s*([^{}@][^{}]{0,160})\s*\{", re.M)
TAILWIND_TOKEN_RE = re.compile(
    r"\b(?:p|px|py|pt|pr|pb|pl|m|mx|my|mt|mr|mb|ml|gap|space-[xy])-"
    r"(?:0|0\.5|1|1\.5|2|2\.5|3|3\.5|4|5|6|7|8|9|10|11|12|14|16|20|24|28|32)\b"
)
CSS_VAR_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s*:\s*([^;{}]+)")
ROLE_PATTERNS = {
    "topbar": r"\b(?:topbar|top-bar|appbar|app-bar|navbar|nav-bar|header)\b|<header\b|<nav\b",
    "sidebar": r"\b(?:sidebar|side-nav|rail)\b|<aside\b",
    "table": r"\b(?:data-table|datatable|table|grid-row)\b|<table\b",
    "card": r"\b(?:card|panel|tile|surface)\b",
    "filter": r"\b(?:filter|facet|search-box|combobox)\b",
    "toast": r"\b(?:toast|snackbar|notification)\b",
    "modal": r"\b(?:modal|dialog|popover|sheet|drawer)\b|<dialog\b",
    "form": r"\b(?:form|input|select|textarea|field)\b|<form\b|<input\b",
    "button": r"\b(?:button|btn|cta)\b|<button\b",
    "tabs": r"\b(?:tabs?|tabpanel)\b",
    "chart": r"\b(?:chart|graph|sparkline|plot)\b",
}
LAYOUT_PATTERNS = {
    "grid": r"\bdisplay\s*:\s*grid\b|\bgrid-template\b|\bgrid-cols-",
    "flex": r"\bdisplay\s*:\s*flex\b|\bflex(?:-|:|\s)",
    "dense": r"\b(?:dense|compact|tight|small)\b",
    "responsive": r"@media\b|\b(?:sm|md|lg|xl):",
    "sticky": r"\bposition\s*:\s*sticky\b|\bsticky\b",
}


def _split_pattern_list(raw: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    for index, char in enumerate(raw):
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(raw[start:index].strip())
            start = index + 1
    parts.append(raw[start:].strip())
    return [part for part in parts if part]


def expand_include_patterns(patterns: Iterable[str] | None) -> list[str]:
    expanded: list[str] = []
    for raw in patterns or DEFAULT_INCLUDE_PATTERNS:
        for item in _split_pattern_list(str(raw)):
            match = re.search(r"\{([^{}]+)\}", item)
            if not match:
                expanded.append(item)
                continue
            for option in match.group(1).split(","):
                expanded.append(item[:match.start()] + option + item[match.end():])
    return expanded


def iter_project_files(root: Path, patterns: Iterable[str], max_files: int = 120) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, pattern) for pattern in patterns):
            files.append(path)
    return sorted(files)[:max_files]


def read_limited_text(path: Path) -> str:
    data = path.read_bytes()[:MAX_FILE_BYTES]
    return data.decode("utf-8", errors="ignore")


def _normalized_css_values(matches: Iterable[str]) -> list[str]:
    values: list[str] = []
    for match in matches:
        for part in re.split(r"\s+", match.strip()):
            token = part.strip().strip(",")
            if re.match(r"^-?\d+(?:\.\d+)?(?:px|rem|em|%)$", token):
                values.append(token.lower())
    return values


def _font_source_type(family: str, text: str) -> str:
    lowered = family.casefold()
    if any(name in lowered for name in ("system-ui", "-apple-system", "arial", "sans-serif", "serif", "monospace")):
        return "system"
    if "@import" in text and "fonts.googleapis.com" in text:
        return "web import"
    if "@font-face" in text and re.search(r"url\([^)]*\.(?:woff2?|ttf|otf|eot)", text, re.I):
        return "bundled"
    return "unknown"


def _font_families(text: str) -> list[tuple[str, str]]:
    families: list[tuple[str, str]] = []
    for raw in FONT_FAMILY_RE.findall(text):
        first = raw.split(",", 1)[0].strip().strip("'\"")
        if first:
            families.append((first, _font_source_type(first, text)))
    return families


def _selectors(text: str, limit: int = 40) -> list[str]:
    selectors: list[str] = []
    for match in CSS_SELECTOR_RE.finditer(text):
        for selector in match.group(2).split(","):
            cleaned = re.sub(r"\s+", " ", selector.strip())
            if cleaned and cleaned not in selectors:
                selectors.append(cleaned)
            if len(selectors) >= limit:
                return selectors
    return selectors


def _count_patterns(text: str, patterns: dict[str, str]) -> Counter[str]:
    lowered = text.casefold()
    counts: Counter[str] = Counter()
    for name, pattern in patterns.items():
        count = len(re.findall(pattern, lowered, re.I))
        if count:
            counts[name] = count
    return counts


def extract_signals(documents: list[tuple[Path | str, str]]) -> tuple[dict[str, list[dict]], list[str], list[dict]]:
    colors: Counter[str] = Counter()
    spacing: Counter[str] = Counter()
    radius: Counter[str] = Counter()
    shadows: Counter[str] = Counter()
    motion: Counter[str] = Counter()
    font_pairs: Counter[tuple[str, str]] = Counter()
    font_sizes: Counter[str] = Counter()
    components: Counter[str] = Counter()
    layout: Counter[str] = Counter()
    accessibility: Counter[str] = Counter()
    selectors: list[str] = []
    css_vars: list[dict] = []
    source_files: list[dict] = []

    for source, text in documents:
        colors.update(value.lower() for value in COLOR_RE.findall(text))
        spacing.update(_normalized_css_values(SPACING_PROP_RE.findall(text)))
        radius.update(value.strip().lower() for value in RADIUS_RE.findall(text))
        shadows.update(value.strip()[:120] for value in SHADOW_RE.findall(text))
        motion.update(value.strip()[:120] for value in MOTION_RE.findall(text))
        font_sizes.update(_normalized_css_values(FONT_SIZE_RE.findall(text)))
        font_pairs.update(_font_families(text))
        components.update(_count_patterns(text, ROLE_PATTERNS))
        layout.update(_count_patterns(text, LAYOUT_PATTERNS))
        selectors.extend(selector for selector in _selectors(text) if selector not in selectors)
        if re.search(r"\baria-[a-z-]+\b", text, re.I):
            accessibility["aria-attributes"] += len(re.findall(r"\baria-[a-z-]+\b", text, re.I))
        if re.search(r"\brole\s*=", text, re.I):
            accessibility["explicit-roles"] += len(re.findall(r"\brole\s*=", text, re.I))
        if re.search(r"\balt\s*=", text, re.I):
            accessibility["image-alt-text"] += len(re.findall(r"\balt\s*=", text, re.I))
        source_files.append({"path": relpath_or_name(Path(source)) if isinstance(source, Path) else str(source)})
        for name, value in CSS_VAR_RE.findall(text):
            css_vars.append({"name": name, "value": value.strip()[:120]})

    typography = [
        {"family": family, "sourceType": source_type, "count": count}
        for (family, source_type), count in font_pairs.most_common(20)
    ]
    typography.extend({"value": value, "role": "font-size", "count": count}
                      for value, count in font_sizes.most_common(20))

    return {
        "colors": counter_items(colors, source="literal"),
        "typography": typography,
        "spacing": counter_items(spacing, source="css-or-class"),
        "radius": counter_items(radius, source="css"),
        "shadows": counter_items(shadows, source="css"),
        "motion": counter_items(motion, source="css"),
        "components": [{"role": role, "count": count} for role, count in components.most_common(20)],
        "layout": [{"pattern": name, "count": count} for name, count in layout.most_common(20)],
        "accessibility": [{"signal": name, "count": count} for name, count in accessibility.most_common(20)],
    }, selectors[:80], source_files


def third_party_exclusions(texts: Iterable[str]) -> list[dict[str, str]]:
    joined = "\n".join(texts)
    exclusions = [
        {"type": "full-css", "reason": "third_party_reference captures never persist complete CSS"},
        {"type": "full-dom", "reason": "third_party_reference captures never persist complete DOM"},
        {"type": "copy-text", "reason": "third_party_reference captures never persist marketing copy"},
        {"type": "images", "reason": "third_party_reference captures keep only screenshot paths as evidence"},
    ]
    if re.search(r"\blogo\b|logo\.(?:svg|png|jpg|webp)", joined, re.I):
        exclusions.append({"type": "logo", "reason": "brand logo references were excluded"})
    if re.search(r"\.(?:woff2?|ttf|otf|eot)\b|@font-face", joined, re.I):
        exclusions.append({"type": "font-file", "reason": "font file references were excluded"})
    return exclusions
