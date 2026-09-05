# ui-ux-pro-max-cli

CLI to install UI/UX Pro Max skill for AI coding assistants.

## Installation

```bash
npm install -g ui-ux-pro-max-cli
```

## Usage

```bash
# Install for specific AI assistant
uipro init --ai claude      # Claude Code
uipro init --ai cursor      # Cursor
uipro init --ai windsurf    # Windsurf
uipro init --ai antigravity # Antigravity
uipro init --ai copilot     # GitHub Copilot
uipro init --ai kiro        # Kiro
uipro init --ai codex       # Codex (Skills)
uipro init --ai roocode     # Roo Code
uipro init --ai qoder       # Qoder
uipro init --ai gemini      # Gemini CLI
uipro init --ai trae        # Trae
uipro init --ai opencode    # OpenCode
uipro init --ai universal   # Universal / Agent Standard (.agents/skills/)
uipro init --ai all         # All assistants

# Options
uipro init --offline        # Compatibility flag; installs bundled templates
uipro init --force          # Overwrite existing files
uipro init --global         # Install globally to home directory (~/)

# Other commands
uipro versions              # List available versions
uipro update                # Update the global CLI to the latest release
uipro update --global       # Refresh globally installed skill files from this CLI package
```

## GitHub Authentication

GitHub's unauthenticated API allows 60 requests/hour per IP. If you hit rate limits, you can provide a GitHub Personal Access Token (PAT) to raise the limit to 5,000 requests/hour.

**Options (in order of precedence):**

```bash
# 1. Pass directly as a flag (one-off use)
uipro init --token ghp_yourtoken
uipro versions --token ghp_yourtoken
uipro update --token ghp_yourtoken

# 2. Set as a project-scoped environment variable (recommended)
export UI_PRO_MAX_GITHUB_TOKEN=ghp_yourtoken
uipro init

# 3. Fallback: GITHUB_TOKEN is also read if UI_PRO_MAX_GITHUB_TOKEN is not set
export GITHUB_TOKEN=ghp_yourtoken
uipro init
```

**Creating a token:** Go to <https://github.com/settings/tokens>, click **Generate new token (classic)**, and select **no scopes** — public repo access requires no permissions. Copy the token and store it as an environment secret; never hardcode it in source files.

> **Warning:** `GITHUB_TOKEN` is automatically injected by GitHub Actions with broad repo permissions. Prefer `UI_PRO_MAX_GITHUB_TOKEN` in CI to avoid accidentally attaching workflow credentials to release download requests.

## How It Works

`uipro init` generates assistant-specific files from the templates bundled with the installed CLI package. To get newer templates and data, update the package, then regenerate:

```bash
uipro update                   # updates the global CLI to the latest release
uipro init --ai codex --force  # regenerate skill files from the new package
```

`uipro update` runs `npm install -g ui-ux-pro-max-cli@latest` for you (it shells out to `npm` only on Windows, where `npm` is a `.cmd`). You can still run that command manually if you prefer. When the CLI is already current, `uipro update` just refreshes the installed skill files.

## Catalog Capture Actions

After `uipro init`, the installed `ui-ux-pro-max/SKILL.md` documents the
user-facing catalog actions:

- `capture-style` — capture a website, local HTML file, or project UI as
  structural design evidence.
- `normalize-capture` — convert `capture.json` into reusable selected tokens.
- `draft-style` — generate `style-row.draft.csv` and `provenance.draft.json`
  without mutating the catalog.
- `register-style` — explicitly promote a reviewed draft into the
  source-of-truth `src/ui-ux-pro-max/data` catalog. Do not register into
  generated mirrors under `.agents`, `.claude`, `.cursor`, `.github/prompts`,
  `.kiro`, or `cli/assets`.
- `list-styles` / `show-style` — show registered styles plus captured draft
  styles, including `registrationState: registered | draft | conflict`.

Example natural-language requests:

```text
Use ui-ux-pro-max to capture https://example.com as a third-party style reference.
Use ui-ux-pro-max to capture this repo's dashboard UI and draft a supplemental style candidate named internal-dashboard-dense.
/ui-ux-pro-max list styles
/ui-ux-pro-max show style minimalism-and-swiss-style
```

Third-party captures default to `third_party_reference` and must not save or
copy logos, images, proprietary font files, complete CSS, complete DOM,
marketing copy, or inline screenshot payloads.

## Development

```bash
# Install dependencies
bun install

# Run locally
bun run src/index.ts --help

# Build
bun run build

# Sync bundled CLI assets from the source skill
npm run sync:assets

# Verify bundled assets are current before publishing
npm run check:assets

# Link for local testing
bun link
```

## License

CC-BY-NC-4.0
