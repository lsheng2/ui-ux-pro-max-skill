# Project Authority Boundary Review Overlay

This project-local overlay customizes `authority-boundary-review` for this repository. Keep cross-project authority-boundary mechanics in the skill-level base rule asset; put only project-specific authorities, forbidden degradations, fixtures, and validation commands here.

## Project-Specific Authorities

- Source-of-truth authority: `src/ui-ux-pro-max/` owns runtime data, scripts,
  and templates. `cli/assets/` and `.claude/skills/ui-ux-pro-max/{data,scripts}`
  are generated mirrors and must not become independent truth.
- User-facing action authority: `src/ui-ux-pro-max/templates/base/skill-content.md`
  owns generated platform `SKILL.md` action text; `.claude/skills/ui-ux-pro-max/SKILL.md`
  is hand-authored and must be intentionally kept in semantic sync.
- Capture/legal authority: `capture.py`, `capture_extractors.py`, and
  `validate_capture.py` own `capture.json` schema and third-party reference
  exclusions. Third-party captures must not persist logos, images, proprietary
  font files, complete CSS, complete DOM, marketing copy, or brand selectors.
- Candidate/register authority: `normalize_capture.py` owns selected reusable
  tokens; `style_from_capture.py` owns draft row generation and the only
  confirmed catalog mutation path.
- Style index authority: `style_index.py` owns read-side merging of registered
  rows with draft capture artifacts and must preserve explicit conflict state.

## Project-Specific Surface Matrix Requirements

- Producer surfaces: `src/ui-ux-pro-max/scripts/*.py`,
  `src/ui-ux-pro-max/templates/base/skill-content.md`, `cli/src/utils/template.ts`,
  and `cli/scripts/sync-assets.mjs`.
- Consumer/mirror surfaces: `cli/assets/scripts/*.py`,
  `cli/assets/templates/base/skill-content.md`, `.claude/skills/ui-ux-pro-max/scripts/*.py`,
  generated universal `.agents/skills/ui-ux-pro-max/SKILL.md`, and hand-authored
  `.claude/skills/ui-ux-pro-max/SKILL.md`.
- Persistence surfaces: `captures/**/capture.json`,
  `captures/**/normalized.json`, `captures/**/style-row*.csv`,
  `captures/**/provenance*.json`, `src/ui-ux-pro-max/data/styles.csv`,
  `src/ui-ux-pro-max/data/catalog-summary.json`, and
  `src/ui-ux-pro-max/data/data-provenance.json`.
- Diagnostic surfaces: script stdout/stderr, `style_index.py --format table/json`,
  `npm run check:assets`, `npm run validate:*`, `npm run test:python`, and
  universal install smoke output.
- Fixture surfaces: `src/ui-ux-pro-max/scripts/tests/test_capture_interface.py`,
  `cli/tests/e2e/template-script-paths.spec.ts`, and mirrored test copies.
- Report product/source changes separately from review/process artifacts under
  `.github/skills/lsheng2-coding/` and session-state files.

## Project-Specific Negative Fixtures

- Duplicate identity fixture: a registered `Style ID` and draft
  `style-row.draft.csv` with the same `Style ID` must list both rows and mark
  the draft `registrationState: conflict`.
- Missing/falsy authority fixture: capture artifacts missing `source.legalMode`
  must fail validation.
- Third-party protected-evidence fixture: `third_party_reference` artifacts
  containing logo/image/font/fullCss/fullDOM/copyText/brand-selector evidence
  must fail validation.
- Long-tail fixture: one-off raw values in `capture.json` must appear in
  `excludedSignals`, not `selectedTokens`.
- Register bypass fixture: draft generation must not mutate `styles.csv`; apply
  must fail unless `--apply --confirm <style-id>` is explicit and exact.
- Partial draft fixture: a `normalized.json` without `style-row.draft.csv` must
  still appear as an unregistered draft in `style_index.py`.

## Project-Specific Derived-Claim Artifacts

- `cli/assets/**`: `derived` from `src/ui-ux-pro-max/**` and sibling sub-skills
  through `npm run sync:assets`; pinned by `npm run check:assets`.
- `.claude/skills/ui-ux-pro-max/{data,scripts}`: `derived` from
  `src/ui-ux-pro-max/{data,scripts}` through `npm run sync:assets`; pinned by
  `npm run check:assets`.
- `cli/assets/templates/base/skill-content.md`: `derived` from
  `src/ui-ux-pro-max/templates/base/skill-content.md`; pinned by
  `npm run check:assets`.
- Generated installed universal `SKILL.md`: `derived` at install time from CLI
  templates; pinned by universal install smoke and template path e2e tests.
- `.claude/skills/ui-ux-pro-max/SKILL.md`: `pinned` hand-authored copy whose
  semantic sync with the source template must be checked in review; no generator
  owns it.
- Historical docs outside this fork and session-state review artifacts are
  `descoped` from product implementation review.

## Project-Specific Validation Rules

- Tier 1 targeted: `python -m unittest src/ui-ux-pro-max/scripts/tests/test_capture_interface.py -v`.
- Tier 2 focused feature suite: `npm --prefix cli run test:python`.
- Tier 3 static/data/sync gates: `npm --prefix cli run check:assets`,
  `npm --prefix cli run validate:csv`, `npm --prefix cli run validate:semantic`,
  `npm --prefix cli run validate:catalog-summary`,
  `npm --prefix cli run validate:agent-guide`, `npm --prefix cli run typecheck`,
  and `npm --prefix cli run build`.
- Tier 4 install/runtime smoke: build then run `node cli/dist/index.js init --ai universal --force`
  in a temporary project, verify installed `.agents/skills/ui-ux-pro-max/SKILL.md`
  documents all capture/catalog actions, verify installed scripts exist, and run
  installed `scripts/style_index.py show minimalism-and-swiss-style --format json`.
- Code changes under scripts/templates/install path must rerun Tier 1, Tier 2,
  Tier 3, and the Tier 4 install smoke before closure. Doc-only action text
  changes must rerun `check:assets`, `validate:agent-guide`, template e2e, and
  install smoke. Process-artifact-only changes do not require product gates.

## Reviewer Prompt Additions

- Require the reviewer to inspect the project-specific authorities named above.
- Require every clean pass to state which surfaces were covered and which
  residual surfaces remain deferred.
- Treat any automatic catalog mutation during capture/normalize/draft as P1.
- Treat missing mirror sync, unresolved template placeholders, hidden style-id
  conflicts, or third-party protected evidence persistence as P1/P2 findings.
