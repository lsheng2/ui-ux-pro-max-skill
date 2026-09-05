#!/usr/bin/env python3
"""Tests for capture, normalization, draft rows, and style indexing."""

from __future__ import annotations

import tempfile
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import capture  # noqa: E402
import capture_extractors  # noqa: E402
import normalize_capture  # noqa: E402
import style_from_capture  # noqa: E402
import style_index  # noqa: E402
from capture_shared import STYLE_HEADERS, read_json, write_csv_rows, write_json  # noqa: E402
from validate_capture import validate_capture_artifact  # noqa: E402


def _style_row(style_id: str, status: str = "active") -> dict[str, str]:
    row = {header: "" for header in STYLE_HEADERS}
    row.update({
        "No": "1",
        "Style Category": "Registered Style",
        "Best For": "Registered catalog tests",
        "Style ID": style_id,
        "Aliases": "Registered Alias",
        "Status": status,
        "Preferred Mode": "auto",
    })
    return row


def _capture_payload() -> dict:
    return {
        "schemaVersion": 1,
        "captureId": "fixture-dashboard",
        "capturedAt": "2026-09-05T00:00:00Z",
        "source": {"kind": "project", "value": "fixture", "legalMode": "owned"},
        "viewports": [{"width": 1440, "height": 1000, "label": "desktop"}],
        "signals": {
            "colors": [
                {"value": "#111111", "count": 4},
                {"value": "#eeeeee", "count": 2},
                {"value": "#123456", "count": 1},
            ],
            "typography": [{"family": "Inter", "sourceType": "system", "count": 3}],
            "spacing": [{"value": "8px", "count": 3}, {"value": "13px", "count": 1}],
            "radius": [{"value": "6px", "count": 2}],
            "shadows": [],
            "motion": [],
            "components": [{"role": "card", "count": 3}],
            "layout": [{"pattern": "grid", "count": 2}],
            "accessibility": [{"signal": "aria-attributes", "count": 2}],
        },
        "evidence": {"screenshots": [], "sampledSelectors": [".card"], "sourceFiles": []},
        "exclusions": [],
    }


class StyleIndexTests(unittest.TestCase):
    def test_lists_registered_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            styles = Path(tmp) / "styles.csv"
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            rows = style_index.build_index(styles, None, False, "all")
        self.assertEqual(["registered-style"], [row["styleId"] for row in rows])
        self.assertEqual("registered", rows[0]["registrationState"])

    def test_lists_draft_styles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            styles = root / "styles.csv"
            captures = root / "captures"
            draft_dir = captures / "draft"
            draft_dir.mkdir(parents=True)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_csv_rows(draft_dir / "style-row.draft.csv", STYLE_HEADERS, [_style_row("draft-style", "supplemental")])
            rows = style_index.build_index(styles, captures, True, "all")
        self.assertIn("draft", {row["registrationState"] for row in rows})
        self.assertIn("draft-style", {row["styleId"] for row in rows})

    def test_lists_normalized_capture_as_draft_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            styles = root / "styles.csv"
            capture_dir = root / "captures" / "normalized-only"
            capture_dir.mkdir(parents=True)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_json(capture_dir / "normalized.json", normalize_capture.normalize_capture(_capture_payload()))
            rows = style_index.build_index(styles, root / "captures", True, "all")
        self.assertIn("fixture-dashboard", {row["styleId"] for row in rows})
        self.assertEqual(
            "draft",
            next(row for row in rows if row["styleId"] == "fixture-dashboard")["registrationState"],
        )

    def test_marks_draft_registered_id_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            styles = root / "styles.csv"
            captures = root / "captures"
            draft_dir = captures / "draft"
            draft_dir.mkdir(parents=True)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("same-style")])
            write_csv_rows(draft_dir / "style-row.draft.csv", STYLE_HEADERS, [_style_row("same-style", "supplemental")])
            rows = style_index.build_index(styles, captures, True, "all")
        states = [row["registrationState"] for row in rows if row["styleId"] == "same-style"]
        self.assertEqual(["registered", "conflict"], states)
        conflict = next(row for row in rows if row["registrationState"] == "conflict")
        self.assertEqual("same-style", conflict["conflictsWith"]["styleId"])

    def test_active_status_filter_keeps_conflicting_draft_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            styles = root / "styles.csv"
            captures = root / "captures"
            draft_dir = captures / "draft"
            draft_dir.mkdir(parents=True)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("same-style")])
            write_csv_rows(draft_dir / "style-row.draft.csv", STYLE_HEADERS, [_style_row("same-style", "supplemental")])
            rows = style_index.build_index(styles, captures, True, "active")
        states = [row["registrationState"] for row in rows if row["styleId"] == "same-style"]
        self.assertEqual(["registered", "conflict"], states)


class ValidateCaptureTests(unittest.TestCase):
    def test_rejects_missing_legal_mode(self):
        payload = _capture_payload()
        del payload["source"]["legalMode"]
        errors = validate_capture_artifact(payload)
        self.assertTrue(any("legalMode" in error for error in errors))

    def test_rejects_forbidden_third_party_evidence(self):
        payload = _capture_payload()
        payload["source"]["legalMode"] = "third_party_reference"
        payload["evidence"]["sampledSelectors"] = [".logo"]
        payload["evidence"].update({
            "logos": [{"path": "logo.svg"}],
            "images": [{"path": "hero.png"}],
            "fontFiles": [{"path": "brand.woff2"}],
            "fullCss": "body{}",
            "fullDOM": "<html></html>",
            "copyText": "marketing words",
        })
        errors = "\n".join(validate_capture_artifact(payload))
        for token in ("sampledSelectors", "logos", "images", "fontFiles", "fullCss", "fullDOM", "copyText"):
            self.assertIn(token, errors)

    def test_rejects_third_party_inline_screenshot_payload(self):
        payload = _capture_payload()
        payload["source"]["legalMode"] = "third_party_reference"
        payload["evidence"]["screenshots"] = ["data:image/png;base64,abcd"]
        errors = validate_capture_artifact(payload)
        self.assertTrue(any("inline screenshot payload" in error for error in errors))


class CaptureAndNormalizeFixtureTests(unittest.TestCase):
    def test_project_file_selection_sorts_before_max_files_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("z-last.css", "a-first.css", "m-middle.css"):
                (root / name).write_text(".card{color:#111111}", encoding="utf-8")
            selected = capture_extractors.iter_project_files(root, ["*.css"], max_files=2)
        self.assertEqual(["a-first.css", "m-middle.css"], [path.name for path in selected])

    def test_local_url_capture_writes_capture_json(self):
        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text(
                "<style>.card{color:#111111;padding:8px}</style><main class='card'>Demo</main>",
                encoding="utf-8",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                out = root / "url-capture.json"
                exit_code = capture.main([
                    "--source", f"http://127.0.0.1:{server.server_port}/index.html",
                    "--source-kind", "url",
                    "--legal-mode", "third_party_reference",
                    "--name", "url fixture",
                    "--out", str(out),
                ])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertEqual(0, exit_code)
            payload = read_json(out)
            self.assertEqual("url", payload["source"]["kind"])
            self.assertEqual("third_party_reference", payload["source"]["legalMode"])

    def test_project_and_html_capture_write_capture_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "style.css").write_text(
                ".card{color:#111111;padding:8px;border-radius:6px;}"
                ".panel{color:#111111;padding:8px;display:grid;}",
                encoding="utf-8",
            )
            html = root / "index.html"
            html.write_text("<main class='card'><button aria-label='Save'>Save</button></main>", encoding="utf-8")
            for kind, source in (("project", root), ("html", html)):
                out = root / f"{kind}-capture.json"
                exit_code = capture.main([
                    "--source", str(source),
                    "--source-kind", kind,
                    "--legal-mode", "owned",
                    "--name", f"{kind} fixture",
                    "--out", str(out),
                ])
                self.assertEqual(0, exit_code)
                self.assertEqual(kind, read_json(out)["source"]["kind"])

    def test_normalize_excludes_long_tail_one_off_values(self):
        normalized = normalize_capture.normalize_capture(_capture_payload())
        excluded_values = {item["value"] for item in normalized["excludedSignals"] if "value" in item}
        selected_colors = {item["value"] for item in normalized["selectedTokens"]["colors"]}
        self.assertIn("#123456", excluded_values)
        self.assertIn("#111111", selected_colors)
        self.assertNotIn("#123456", selected_colors)


class StyleFromCaptureTests(unittest.TestCase):
    def test_ai_prompt_keywords_are_at_most_40_words(self):
        normalized = normalize_capture.normalize_capture(_capture_payload())
        row = style_from_capture.build_style_row(
            normalized,
            style_id="fixture-dashboard-style",
            style_name="Fixture Dashboard Style With Many Useful Descriptive Words",
            status="supplemental",
            parent_style_id="",
            aliases="",
        )
        self.assertLessEqual(len(row["AI Prompt Keywords"].split()), 40)

    def test_draft_generation_does_not_mutate_registered_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            styles = data / "styles.csv"
            normalized = root / "normalized.json"
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_json(normalized, normalize_capture.normalize_capture(_capture_payload()))
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "draft-only-style",
                "--data-dir", str(data),
            ])
            _, rows = style_from_capture.read_csv_rows(styles)
        self.assertEqual(0, exit_code)
        self.assertEqual(["registered-style"], [row["Style ID"] for row in rows])

    def test_register_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            styles = data / "styles.csv"
            normalized = root / "normalized.json"
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_json(normalized, normalize_capture.normalize_capture(_capture_payload()))
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "registered-style-child",
                "--parent-style-id", "registered-style",
                "--data-dir", str(data),
                "--apply",
            ])
            _, rows = style_from_capture.read_csv_rows(styles)
        self.assertEqual(1, exit_code)
        self.assertEqual(["registered-style"], [row["Style ID"] for row in rows])

    def test_register_requires_explicit_source_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = root / "normalized.json"
            write_json(normalized, normalize_capture.normalize_capture(_capture_payload()))
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "registered-style-child",
                "--parent-style-id", "registered-style",
                "--apply",
                "--confirm", "registered-style-child",
            ])
        self.assertEqual(1, exit_code)

    def test_register_rejects_generated_mirror_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = root / "normalized.json"
            write_json(normalized, normalize_capture.normalize_capture(_capture_payload()))
            for relative in (
                ".agents/skills/ui-ux-pro-max/data",
                ".cursor/skills/ui-ux-pro-max/data",
                ".github/prompts/ui-ux-pro-max/data",
                ".kiro/steering/ui-ux-pro-max/data",
                "cli/assets/data",
            ):
                with self.subTest(relative=relative):
                    data = root / Path(relative)
                    data.mkdir(parents=True, exist_ok=True)
                    styles = data / "styles.csv"
                    write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
                    exit_code = style_from_capture.main([
                        str(normalized),
                        "--style-id", "registered-style-child",
                        "--parent-style-id", "registered-style",
                        "--data-dir", str(data),
                        "--apply",
                        "--confirm", "registered-style-child",
                    ])
                    _, rows = style_from_capture.read_csv_rows(styles)
                    self.assertEqual(1, exit_code)
                    self.assertEqual(["registered-style"], [row["Style ID"] for row in rows])

    def test_register_applies_after_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            styles = data / "styles.csv"
            normalized = root / "captures" / "fixture" / "normalized.json"
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_json(data / "catalog-summary.json", {"schemaVersion": 1, "verifiedAt": "2026-09-05", "counts": {}})
            write_json(data / "data-provenance.json", {"schemaVersion": 1, "records": []})
            write_json(normalized, normalize_capture.normalize_capture(_capture_payload()))
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "registered-style-child",
                "--parent-style-id", "registered-style",
                "--data-dir", str(data),
                "--apply",
                "--confirm", "registered-style-child",
            ])
            _, rows = style_from_capture.read_csv_rows(styles)
            provenance = read_json(data / "data-provenance.json")
            summary = read_json(data / "catalog-summary.json")
        self.assertEqual(0, exit_code)
        self.assertEqual(["registered-style", "registered-style-child"], [row["Style ID"] for row in rows])
        self.assertEqual("registered-style-child", provenance["records"][0]["entityId"])
        self.assertEqual(2, summary["counts"]["styles"]["total"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
