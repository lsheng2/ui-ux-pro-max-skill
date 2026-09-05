import { existsSync } from 'node:fs';
import { readFile, mkdir, writeFile, cp, access, readdir, lstat, rm } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ASSETS_CANDIDATES = [
  // Bun bundle: dist/index.js
  join(__dirname, '..', 'assets'),
  // TypeScript fallback: dist/utils/template.js
  join(__dirname, '..', '..', 'assets'),
];
const ASSETS_DIR = ASSETS_CANDIDATES.find(path => existsSync(path)) ?? ASSETS_CANDIDATES[0];

type CsvRecord = Record<string, string>;

export interface PlatformConfig {
  platform: string;
  displayName: string;
  installType: 'full' | 'reference';
  folderStructure: {
    root: string;
    skillPath: string;
    filename: string;
    dataPath?: string;
  };
  scriptPath: string;
  frontmatter: Record<string, string> | null;
  sections: {
    quickReference: boolean;
  };
  title: string;
  description: string;
  skillOrWorkflow: string;
}

// Map AIType to platform config file name
const AI_TO_PLATFORM: Record<string, string> = {
  claude: 'claude',
  cursor: 'cursor',
  windsurf: 'windsurf',
  antigravity: 'agent',
  copilot: 'copilot',
  kiro: 'kiro',
  opencode: 'opencode',
  roocode: 'roocode',
  codex: 'codex',
  qoder: 'qoder',
  gemini: 'gemini',
  trae: 'trae',
  continue: 'continue',
  codebuddy: 'codebuddy',
  droid: 'droid',
  kilocode: 'kilocode',
  warp: 'warp',
  augment: 'augment',
  codewhale: 'codewhale',
  universal: 'universal',
};

async function exists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

/**
 * Load platform configuration from JSON file
 */
export async function loadPlatformConfig(aiType: string): Promise<PlatformConfig> {
  const platformName = AI_TO_PLATFORM[aiType];
  if (!platformName) {
    throw new Error(`Unknown AI type: ${aiType}`);
  }

  const configPath = join(ASSETS_DIR, 'templates', 'platforms', `${platformName}.json`);
  const content = await readFile(configPath, 'utf-8');
  return JSON.parse(content) as PlatformConfig;
}

/**
 * Load all available platform configs
 */
export async function loadAllPlatformConfigs(): Promise<Map<string, PlatformConfig>> {
  const configs = new Map<string, PlatformConfig>();

  for (const [aiType, platformName] of Object.entries(AI_TO_PLATFORM)) {
    try {
      const config = await loadPlatformConfig(aiType);
      configs.set(aiType, config);
    } catch {
      // Skip if config doesn't exist
    }
  }

  return configs;
}

/**
 * Load a template file
 */
async function loadTemplate(templateName: string): Promise<string> {
  const templatePath = join(ASSETS_DIR, 'templates', templateName);
  return readFile(templatePath, 'utf-8');
}

/**
 * Render frontmatter section
 */
function renderFrontmatter(frontmatter: Record<string, string> | null): string {
  if (!frontmatter) return '';

  const lines = ['---'];
  for (const [key, value] of Object.entries(frontmatter)) {
    // Quote values that contain special characters
    if (value.includes(':') || value.includes('"') || value.includes('\n')) {
      lines.push(`${key}: "${value.replace(/"/g, '\\"')}"`);
    } else {
      lines.push(`${key}: ${value}`);
    }
  }
  lines.push('---', '');
  return lines.join('\n');
}

/**
 * Render skill file content from template
 * When isGlobal=true, rewrites script paths to use ~/{root}/ prefix
 */
export async function renderSkillFile(config: PlatformConfig, isGlobal = false): Promise<string> {
  // Load base template
  let content = await loadTemplate('base/skill-content.md');

  // Load quick reference if needed
  let quickReferenceContent = '';
  if (config.sections.quickReference) {
    quickReferenceContent = await loadTemplate('base/quick-reference.md');
  }

  // scriptPath is relative to the platform root. Generated commands run from
  // the user's project root, so local installs need the platform root prefix;
  // global installs need the same path anchored at the user's home directory.
  const rootedScriptPath = `${config.folderStructure.root}/${config.scriptPath}`
    .replace(/\/{2,}/g, '/');
  const commandScriptPath = isGlobal ? `~/${rootedScriptPath}` : rootedScriptPath;
  const commandScriptDir = commandScriptPath.replace(/\/[^/]+$/, '');

  // Build the final content
  const frontmatter = renderFrontmatter(config.frontmatter);

  // Replace placeholders
  // Add newline before quick reference content if it exists
  const quickRefWithNewline = quickReferenceContent ? '\n' + quickReferenceContent : '';

  content = content
    .replace(/\{\{TITLE\}\}/g, config.title)
    .replace(/\{\{DESCRIPTION\}\}/g, config.description)
    .replace(/\{\{SCRIPT_PATH\}\}/g, commandScriptPath)
    .replace(/\{\{SCRIPT_DIR\}\}/g, commandScriptDir)
    .replace(/\{\{SKILL_OR_WORKFLOW\}\}/g, config.skillOrWorkflow)
    .replace(/\{\{QUICK_REFERENCE\}\}/g, quickRefWithNewline);

  return frontmatter + content;
}

/**
 * Replace a pre-existing non-directory at `path` so a real directory can be
 * created there. Older CLI installs (and Windows checkouts of the repo's
 * symlinked data/scripts) can leave plain "pointer" files at these paths;
 * mkdir then throws EEXIST and the install silently leaves stale files.
 */
async function ensureCleanDir(path: string): Promise<void> {
  try {
    const stat = await lstat(path);
    if (!stat.isDirectory()) {
      await rm(path, { recursive: true, force: true });
    }
  } catch {
    // Nothing exists at the path yet — mkdir will create it.
  }
}

function parseCsv(text: string): { headers: string[]; rows: CsvRecord[] } {
  const records: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
      continue;
    }
    if (char === '"') {
      quoted = true;
    } else if (char === ',') {
      row.push(field);
      field = '';
    } else if (char === '\n') {
      row.push(field);
      records.push(row);
      row = [];
      field = '';
    } else if (char !== '\r') {
      field += char;
    }
  }
  if (field || row.length) {
    row.push(field);
    records.push(row);
  }
  const headers = records.shift() ?? [];
  const rows = records
    .filter(values => values.some(value => value !== ''))
    .map(values => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ''])));
  return { headers, rows };
}

function formatCsvValue(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function formatCsv(headers: string[], rows: CsvRecord[]): string {
  const lines = [headers.map(formatCsvValue).join(',')];
  for (const row of rows) {
    lines.push(headers.map(header => formatCsvValue(row[header] ?? '')).join(','));
  }
  return `${lines.join('\n')}\n`;
}

function styleCounts(rows: CsvRecord[]): Record<string, number> {
  return {
    total: rows.length,
    searchable: rows.filter(row => row.Status !== 'deprecated').length,
    active: rows.filter(row => row.Status === 'active').length,
    supplemental: rows.filter(row => row.Status === 'supplemental').length,
    deprecated: rows.filter(row => row.Status === 'deprecated').length,
  };
}

async function applyCustomStyleOverlays(targetSkillDir: string): Promise<void> {
  const overlayDir = join(targetSkillDir, 'overlays', 'styles');
  if (!(await exists(overlayDir))) return;
  const entries = (await readdir(overlayDir, { withFileTypes: true }))
    .filter(entry => entry.isFile() && entry.name.endsWith('.json'))
    .map(entry => entry.name)
    .sort();
  if (!entries.length) return;

  const stylesPath = join(targetSkillDir, 'data', 'styles.csv');
  const summaryPath = join(targetSkillDir, 'data', 'catalog-summary.json');
  const provenancePath = join(targetSkillDir, 'data', 'data-provenance.json');
  const { headers, rows } = parseCsv(await readFile(stylesPath, 'utf-8'));
  const overlays: { style: CsvRecord; provenance?: Record<string, unknown>; path: string }[] = [];
  for (const name of entries) {
    const path = join(overlayDir, name);
    const payload = JSON.parse(await readFile(path, 'utf-8')) as { style?: CsvRecord; provenance?: Record<string, unknown> };
    if (!payload.style?.['Style ID']) {
      throw new Error(`style overlay ${path} must contain style["Style ID"]`);
    }
    overlays.push({ style: payload.style, provenance: payload.provenance, path });
  }

  const overlayIds = new Set(overlays.map(overlay => overlay.style['Style ID']));
  const merged = rows.filter(row => !overlayIds.has(row['Style ID']));
  let nextNo = Math.max(0, ...merged.map(row => Number.parseInt(row.No || '0', 10)).filter(Number.isFinite)) + 1;
  for (const overlay of overlays) {
    const style: CsvRecord = Object.fromEntries(headers.map(header => [header, overlay.style[header] ?? '']));
    style.No = String(nextNo);
    nextNo += 1;
    merged.push(style);
  }
  await writeFile(stylesPath, formatCsv(headers, merged), 'utf-8');

  if (await exists(summaryPath)) {
    const summary = JSON.parse(await readFile(summaryPath, 'utf-8')) as Record<string, any>;
    summary.counts = summary.counts ?? {};
    summary.counts.styles = styleCounts(merged);
    await writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf-8');
  }

  if (await exists(provenancePath)) {
    const provenance = JSON.parse(await readFile(provenancePath, 'utf-8')) as { records?: Record<string, unknown>[] };
    provenance.records = Array.isArray(provenance.records) ? provenance.records : [];
    provenance.records = provenance.records.filter(record => (
      record.entityKind !== 'style' || !overlayIds.has(String(record.entityId ?? ''))
    ));
    for (const overlay of overlays) {
      provenance.records.push(overlay.provenance ?? {
        entityKind: 'style',
        entityId: overlay.style['Style ID'],
        sourceFile: 'styles.csv',
        sourceKey: { 'Style ID': overlay.style['Style ID'] },
        status: overlay.style.Status || 'supplemental',
        verifiedAt: new Date().toISOString().slice(0, 10),
        sla: 'needs-review',
        appliesTo: ['style-search', 'design-system', 'gallery'],
        confidence: 0.86,
        sources: [{ type: 'derived', ref: `overlays/styles/${overlay.path.split(/[\\/]/).pop()}` }],
      });
    }
    await writeFile(provenancePath, `${JSON.stringify(provenance, null, 2)}\n`, 'utf-8');
  }
}

/**
 * Copy data and scripts to target directory
 */
async function copyDataAndScripts(targetSkillDir: string): Promise<void> {
  const capturesSource = join(ASSETS_DIR, 'captures');
  const dataSource = join(ASSETS_DIR, 'data');
  const scriptsSource = join(ASSETS_DIR, 'scripts');

  const capturesTarget = join(targetSkillDir, 'captures');
  const dataTarget = join(targetSkillDir, 'data');
  const scriptsTarget = join(targetSkillDir, 'scripts');

  // Copy source-controlled capture evidence used by provenance records.
  if (await exists(capturesSource)) {
    await ensureCleanDir(capturesTarget);
    await mkdir(capturesTarget, { recursive: true });
    await cp(capturesSource, capturesTarget, { recursive: true });
  }

  // Copy data
  if (await exists(dataSource)) {
    await ensureCleanDir(dataTarget);
    await mkdir(dataTarget, { recursive: true });
    await cp(dataSource, dataTarget, { recursive: true });
  }

  // Copy scripts
  if (await exists(scriptsSource)) {
    await ensureCleanDir(scriptsTarget);
    await mkdir(scriptsTarget, { recursive: true });
    await cp(scriptsSource, scriptsTarget, { recursive: true });
  }
}

async function copyBundledStyleOverlays(targetSkillDir: string): Promise<void> {
  const source = join(ASSETS_DIR, 'overlays', 'styles');
  if (!(await exists(source))) return;
  const target = join(targetSkillDir, 'overlays', 'styles');
  await mkdir(target, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
    const destination = join(target, entry.name);
    if (await exists(destination) && await isLocalStyleOverlayOverride(destination)) continue;
    await cp(join(source, entry.name), destination, { force: true });
  }
}

async function isLocalStyleOverlayOverride(path: string): Promise<boolean> {
  try {
    const payload = JSON.parse(await readFile(path, 'utf-8')) as {
      localOverride?: unknown;
      provenance?: { localOverride?: unknown };
    };
    return payload.localOverride === true || payload.provenance?.localOverride === true;
  } catch {
    return false;
  }
}

/**
 * List the static sub-skills bundled under assets/skills/ (everything except
 * the template-rendered orchestrator). Empty if the package predates bundling.
 */
export async function listBundledSubSkills(): Promise<string[]> {
  const skillsSource = join(ASSETS_DIR, 'skills');
  if (!(await exists(skillsSource))) return [];
  const entries = await readdir(skillsSource, { withFileTypes: true });
  return entries.filter(e => e.isDirectory()).map(e => e.name).sort();
}

/**
 * Install the bundled sub-skills as siblings of the orchestrator skill, so a
 * single `uipro init` delivers all 7 skills instead of only ui-ux-pro-max.
 */
async function copySubSkills(skillsParentDir: string, force: boolean): Promise<void> {
  const skillsSource = join(ASSETS_DIR, 'skills');
  if (!(await exists(skillsSource))) return;

  for (const name of await listBundledSubSkills()) {
    const target = join(skillsParentDir, name);
    if (await exists(target) && !force) continue;
    await mkdir(target, { recursive: true });
    await cp(join(skillsSource, name), target, { recursive: true });
  }
}

/**
 * Generate platform files for a specific AI type
 * All platforms use self-contained installation with data and scripts
 * When isGlobal=true, installs to ~/home directory with absolute script paths
 */
export async function generatePlatformFiles(
  targetDir: string,
  aiType: string,
  isGlobal = false,
  force = false
): Promise<string[]> {
  const config = await loadPlatformConfig(aiType);
  const createdFolders: string[] = [];

  // For global install, target the user's home directory
  const effectiveDir = isGlobal ? homedir() : targetDir;

  // Determine full skill directory path
  const skillDir = join(
    effectiveDir,
    config.folderStructure.root,
    config.folderStructure.skillPath
  );

  // Create directory structure
  await mkdir(skillDir, { recursive: true });

  // Render and write skill file (pass isGlobal to adjust paths)
  const skillContent = await renderSkillFile(config, isGlobal);
  const skillFilePath = join(skillDir, config.folderStructure.filename);

  const fileAlreadyExists = await exists(skillFilePath);
  if (fileAlreadyExists && !force) {
    console.log(`  Skipped (already exists): ${skillFilePath} — use --force to overwrite`);
    return [];
  }

  await writeFile(skillFilePath, skillContent, 'utf-8');
  createdFolders.push(config.folderStructure.root);

  // Copy data and scripts into the data directory (may differ from skill file location)
  const dataDir = config.folderStructure.dataPath
    ? join(effectiveDir, config.folderStructure.root, config.folderStructure.dataPath)
    : skillDir;
  await mkdir(dataDir, { recursive: true });
  await copyDataAndScripts(dataDir);
  await copyBundledStyleOverlays(dataDir);
  await applyCustomStyleOverlays(dataDir);

  // Install the sibling sub-skills (banner-design, brand, design, ...) next to
  // the orchestrator so all 7 skills are delivered. The skills parent is the
  // orchestrator's parent dir (skills/ for most platforms, prompts/ for
  // copilot, steering/ for kiro) — derived, not hardcoded. For platforms with
  // a separate dataPath (copilot), the orchestrator's data dir is the anchor.
  const skillsParentDir = join(
    effectiveDir,
    config.folderStructure.root,
    config.folderStructure.dataPath
      ? dirname(config.folderStructure.dataPath)
      : dirname(config.folderStructure.skillPath)
  );
  await copySubSkills(skillsParentDir, force);

  return createdFolders;
}

/**
 * Generate files for all AI types
 */
export async function generateAllPlatformFiles(targetDir: string, isGlobal = false, force = false): Promise<string[]> {
  const allFolders = new Set<string>();
  const generatedSkillFiles = new Set<string>();

  for (const aiType of Object.keys(AI_TO_PLATFORM)) {
    try {
      const config = await loadPlatformConfig(aiType);
      const skillFile = join(
        config.folderStructure.root,
        config.folderStructure.skillPath,
        config.folderStructure.filename
      );
      if (generatedSkillFiles.has(skillFile)) continue;

      const folders = await generatePlatformFiles(targetDir, aiType, isGlobal, force);
      generatedSkillFiles.add(skillFile);
      folders.forEach(f => allFolders.add(f));
    } catch {
      // Skip if generation fails for a platform
    }
  }

  return Array.from(allFolders);
}

/**
 * Get list of supported AI types
 */
export function getSupportedAITypes(): string[] {
  return Object.keys(AI_TO_PLATFORM);
}
