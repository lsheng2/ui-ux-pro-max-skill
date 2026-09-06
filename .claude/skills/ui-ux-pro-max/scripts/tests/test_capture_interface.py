#!/usr/bin/env python3
"""Tests for capture, normalization, draft rows, and style indexing."""

from __future__ import annotations

import tempfile
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import capture  # noqa: E402
import capture_extractors  # noqa: E402
import normalize_capture  # noqa: E402
import style_from_capture  # noqa: E402
import style_index  # noqa: E402
import validate_style_draft  # noqa: E402
from assess_style_quality import assess_quality  # noqa: E402
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


def _write_capture_set(root: Path) -> Path:
    capture_path = root / "captures" / "fixture" / "capture.json"
    normalized_path = capture_path.with_name("normalized.json")
    write_json(capture_path, _capture_payload())
    write_json(normalized_path, normalize_capture.normalize_capture(_capture_payload()))
    return normalized_path


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
        self.assertIn("fixture-dashboard-grid-dense", {row["styleId"] for row in rows})
        self.assertEqual(
            "draft",
            next(row for row in rows if row["styleId"] == "fixture-dashboard-grid-dense")["registrationState"],
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

    def test_hides_capture_draft_after_registered_provenance_consumes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            styles = data / "styles.csv"
            captures = root / "captures"
            normalized = _write_capture_set(root)
            data.mkdir()
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("fixture-dashboard-grid-dense", "supplemental")])
            write_json(data / "data-provenance.json", {
                "schemaVersion": 1,
                "records": [{
                    "entityKind": "style",
                    "entityId": "fixture-dashboard-grid-dense",
                    "sources": [{"type": "derived", "ref": "captures/fixture/normalized.json#captureId=fixture-dashboard"}],
                }],
            })
            rows = style_index.build_index(styles, captures, True, "all")
        self.assertEqual(["registered"], [row["registrationState"] for row in rows if row["styleId"] == "fixture-dashboard-grid-dense"])

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
    def test_quality_assessment_blocks_missing_capture_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = root / "captures" / "fixture" / "normalized.json"
            write_json(normalized, normalize_capture.normalize_capture(_capture_payload()))
            style_from_capture.main([str(normalized), "--style-id", "draft-style"])
            report = read_json(normalized.with_name("quality-report.json"))
        self.assertEqual("draft-only", report["readiness"])
        self.assertIn("capture artifact is missing", report["issues"]["traceability"])

    def test_quality_assessment_detects_duplicate_design_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = _write_capture_set(root)
            draft = normalized.with_name("style-row.draft.csv")
            provenance = normalized.with_name("provenance.draft.json")
            row = style_from_capture.build_style_row(
                normalize_capture.normalize_capture(_capture_payload()),
                style_id="draft-style",
                style_name="Draft Style",
                status="supplemental",
                parent_style_id="registered-style",
                aliases="Draft Alias",
            )
            row["Design System Variables"] = "--radius-control: 6px; --radius-control: 3px"
            write_csv_rows(draft, STYLE_HEADERS, [row])
            write_json(provenance, {"schemaVersion": 1, "records": [style_from_capture.provenance_record(normalized, read_json(normalized), row)]})
            report = assess_quality(normalized, draft_path=draft, provenance_path=provenance)
        self.assertIn("duplicate design variables: --radius-control", report["issues"]["tokens"])

    def test_quality_assessment_detects_font_family_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = _write_capture_set(root)
            draft = normalized.with_name("style-row.draft.csv")
            provenance = normalized.with_name("provenance.draft.json")
            row = style_from_capture.build_style_row(
                normalize_capture.normalize_capture(_capture_payload()),
                style_id="draft-style",
                style_name="Draft Style",
                status="supplemental",
                parent_style_id="registered-style",
                aliases="Draft Alias",
            )
            row["Design System Variables"] = "--font-secondary: 16px; --font-size-body: 0.875rem"
            write_csv_rows(draft, STYLE_HEADERS, [row])
            write_json(provenance, {"schemaVersion": 1, "records": [style_from_capture.provenance_record(normalized, read_json(normalized), row)]})
            report = assess_quality(normalized, draft_path=draft, provenance_path=provenance)
        self.assertEqual("draft-only", report["readiness"])
        self.assertIn("font family token contains a font-size value", report["issues"]["tokens"])

    def test_quality_assessment_detects_shadow_and_motion_positional_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = _write_capture_set(root)
            draft = normalized.with_name("style-row.draft.csv")
            provenance = normalized.with_name("provenance.draft.json")
            row = style_from_capture.build_style_row(
                normalize_capture.normalize_capture(_capture_payload()),
                style_id="draft-style",
                style_name="Draft Style",
                status="supplemental",
                parent_style_id="registered-style",
                aliases="Draft Alias",
            )
            row["Design System Variables"] = "--shadow-1: 0 1px 2px #000; --motion-1: opacity 0.15s"
            write_csv_rows(draft, STYLE_HEADERS, [row])
            write_json(provenance, {"schemaVersion": 1, "records": [style_from_capture.provenance_record(normalized, read_json(normalized), row)]})
            report = assess_quality(normalized, draft_path=draft, provenance_path=provenance)
        self.assertEqual("draft-only", report["readiness"])
        self.assertIn("Design System Variables uses positional token names instead of semantic roles", report["issues"]["tokens"])

    def test_quality_report_uses_portable_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = _write_capture_set(root)
            style_from_capture.main([str(normalized), "--style-id", "draft-style", "--aliases", "Draft Alias"])
            report = read_json(normalized.with_name("quality-report.json"))
        self.assertNotIn(str(root), report["evidence"]["normalizedPath"])
        self.assertNotIn(str(root), report["evidence"]["capturePath"])

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
            normalized = _write_capture_set(root)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
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
            normalized = _write_capture_set(root)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
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
            normalized = _write_capture_set(root)
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
            normalized = _write_capture_set(root)
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
                        "--skip-post-apply-validation",
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
            normalized = _write_capture_set(root)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_json(data / "catalog-summary.json", {"schemaVersion": 1, "verifiedAt": "2026-09-05", "counts": {}})
            write_json(data / "data-provenance.json", {"schemaVersion": 1, "records": []})
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "registered-style-child",
                "--parent-style-id", "registered-style",
                "--aliases", "Registered Style Child",
                "--data-dir", str(data),
                "--apply",
                "--confirm", "registered-style-child",
                "--skip-post-apply-validation",
            ])
            _, rows = style_from_capture.read_csv_rows(styles)
            provenance = read_json(data / "data-provenance.json")
            summary = read_json(data / "catalog-summary.json")
        self.assertEqual(0, exit_code)
        self.assertEqual(["registered-style", "registered-style-child"], [row["Style ID"] for row in rows])
        self.assertEqual("registered-style-child", provenance["records"][0]["entityId"])
        self.assertEqual("owned", provenance["records"][0]["legalMode"])
        self.assertEqual(2, summary["counts"]["styles"]["total"])

    def test_update_existing_replaces_row_provenance_and_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "src" / "ui-ux-pro-max" / "data"
            data.mkdir(parents=True)
            styles = data / "styles.csv"
            normalized = _write_capture_set(root)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style"), _style_row("target-style", "supplemental")])
            write_json(data / "catalog-summary.json", {"schemaVersion": 1, "verifiedAt": "2026-09-05", "counts": {}})
            write_json(data / "data-provenance.json", {"schemaVersion": 1, "records": [{"entityKind": "style", "entityId": "target-style", "sourceFile": "styles.csv", "sourceKey": {"Style ID": "target-style"}, "legalMode": "owned", "appliesTo": ["style-search"], "confidence": 0.1, "sources": [{"type": "derived", "ref": "old"}]}]})
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "target-style",
                "--style-name", "Updated Target Style",
                "--parent-style-id", "registered-style",
                "--aliases", "Target Alias",
                "--data-dir", str(data),
                "--apply",
                "--update-existing",
                "--confirm", "target-style",
                "--skip-post-apply-validation",
            ])
            _, rows = style_from_capture.read_csv_rows(styles)
            provenance = read_json(data / "data-provenance.json")
            overlay = read_json(data.parent / "overlays" / "styles" / "target-style.json")
        self.assertEqual(0, exit_code)
        self.assertEqual(1, sum(row["Style ID"] == "target-style" for row in rows))
        self.assertEqual("Updated Target Style", next(row for row in rows if row["Style ID"] == "target-style")["Style Category"])
        self.assertEqual(1, sum(record["entityId"] == "target-style" for record in provenance["records"]))
        self.assertEqual("Updated Target Style", overlay["style"]["Style Category"])

    def test_validate_style_draft_accepts_generated_draft_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normalized = _write_capture_set(root)
            draft = normalized.with_name("style-row.draft.csv")
            provenance = normalized.with_name("provenance.draft.json")
            exit_code = style_from_capture.main([
                str(normalized),
                "--style-id", "draft-style",
                "--parent-style-id", "registered-style",
                "--aliases", "Draft Alias",
            ])
            errors = (
                validate_style_draft.validate_draft_csv(draft, register_ready=True)
                + validate_style_draft.validate_provenance(provenance)
            )
        self.assertEqual(0, exit_code)
        self.assertEqual([], errors)

    def test_register_runs_post_apply_validation_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            styles = data / "styles.csv"
            normalized = _write_capture_set(root)
            write_csv_rows(styles, STYLE_HEADERS, [_style_row("registered-style")])
            write_json(data / "catalog-summary.json", {"schemaVersion": 1, "verifiedAt": "2026-09-05", "counts": {}})
            write_json(data / "data-provenance.json", {"schemaVersion": 1, "records": []})
            with patch.object(style_from_capture, "_run_post_apply_validation") as validator:
                exit_code = style_from_capture.main([
                    str(normalized),
                    "--style-id", "registered-style-child",
                    "--parent-style-id", "registered-style",
                    "--aliases", "Registered Style Child",
                    "--data-dir", str(data),
                    "--apply",
                    "--confirm", "registered-style-child",
                ])
        self.assertEqual(0, exit_code)
        validator.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
