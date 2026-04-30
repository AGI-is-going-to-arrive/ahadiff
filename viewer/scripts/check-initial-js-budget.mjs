import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

/**
 * Phase 4 raised the budget from 80 KB to 84 KB to accommodate the AppShell
 * Cmd/Ctrl+K wiring + verdict-filter UI. R4-F1 set 80 KB based on a
 * React 19 + react-router-dom floor of ~57 KB; 84 KB still leaves only a
 * ~27 KB shell — well under the React 19 + router + shell ceiling tracked in
 * doc/v6-alignment-gap-analysis.md and risk register R6.
 *
 * If you need to bump this further, prefer carving heavy deps into
 * `vendor-page-deps` (excluded from modulepreload, see vite.config.ts) over
 * raising the constant — the shell should stay shell-sized.
 */
const DEFAULT_BUDGET_BYTES = 84 * 1024;
const DEFAULT_DASHBOARD_ROUTE_BUDGET_BYTES = 112 * 1024;
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const distDir = resolve(root, 'dist');
const indexHtmlPath = resolve(distDir, 'index.html');
const manifestPath = resolve(distDir, '.vite', 'manifest.json');

function fail(message) {
  console.error(message);
  process.exit(1);
}

function parseBudget(raw, envName, defaultValue) {
  if (raw === undefined || raw === '') return defaultValue;
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) {
    fail(`Invalid ${envName}: ${raw}`);
  }
  return value;
}

const budgetBytes = parseBudget(
  process.env.AHADIFF_INITIAL_JS_GZIP_BUDGET_BYTES,
  'AHADIFF_INITIAL_JS_GZIP_BUDGET_BYTES',
  DEFAULT_BUDGET_BYTES,
);
const dashboardRouteBudgetBytes = parseBudget(
  process.env.AHADIFF_DASHBOARD_ROUTE_JS_GZIP_BUDGET_BYTES,
  'AHADIFF_DASHBOARD_ROUTE_JS_GZIP_BUDGET_BYTES',
  DEFAULT_DASHBOARD_ROUTE_BUDGET_BYTES,
);

function attr(tag, name) {
  const match = tag.match(new RegExp(`\\b${name}\\s*=\\s*(['"])(.*?)\\1`, 'i'));
  return match?.[2] ?? null;
}

function hasRel(tag, rel) {
  return (
    attr(tag, 'rel')
      ?.split(/\s+/)
      .some((value) => value.toLowerCase() === rel) ?? false
  );
}

function localAssetPath(ref) {
  const trimmed = ref.trim();
  if (!trimmed) return null;
  if (/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(trimmed)) {
    fail(`Initial JS reference must be local: ${ref}`);
  }
  const withoutQuery = trimmed.split(/[?#]/, 1)[0];
  if (!withoutQuery.endsWith('.js')) return null;

  const assetPath = resolve(distDir, withoutQuery.replace(/^\.\//, '').replace(/^\//, ''));
  const rel = relative(distDir, assetPath);
  if (isAbsolute(rel) || rel === '..' || rel.startsWith(`..${sep}`)) {
    fail(`Initial JS reference escapes dist/: ${ref}`);
  }
  return assetPath;
}

function collectInitialJs(html) {
  const refs = new Map();
  for (const tag of html.match(/<(script|link)\b[^>]*>/gi) ?? []) {
    const lower = tag.toLowerCase();
    const ref =
      lower.startsWith('<script') && attr(tag, 'type')?.toLowerCase() === 'module'
        ? attr(tag, 'src')
        : lower.startsWith('<link') && hasRel(tag, 'modulepreload')
          ? attr(tag, 'href')
          : null;
    if (!ref) continue;
    const assetPath = localAssetPath(ref);
    if (assetPath) refs.set(ref, assetPath);
  }
  return [...refs.entries()].map(([ref, assetPath]) => ({ ref, assetPath }));
}

function assetRef(file) {
  return file.startsWith('./') || file.startsWith('/') ? file : `./${file}`;
}

function loadManifest() {
  if (!existsSync(manifestPath)) {
    fail(`Missing Vite manifest: ${manifestPath}`);
  }
  try {
    return JSON.parse(readFileSync(manifestPath, 'utf8'));
  } catch (error) {
    fail(`Invalid Vite manifest: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function findManifestKey(manifest, source) {
  for (const [key, entry] of Object.entries(manifest)) {
    if (key === source || entry?.src === source) return key;
  }
  fail(`Missing manifest entry for ${source}`);
}

function collectManifestJs(manifest, source) {
  const refs = new Map();
  const seen = new Set();
  const visit = (key) => {
    if (seen.has(key)) return;
    seen.add(key);
    const entry = manifest[key];
    if (!entry) fail(`Manifest import not found: ${key}`);
    if (typeof entry.file === 'string' && entry.file.endsWith('.js')) {
      const ref = assetRef(entry.file);
      refs.set(ref, localAssetPath(ref));
    }
    for (const imported of entry.imports ?? []) {
      visit(imported);
    }
  };
  visit(findManifestKey(manifest, source));
  return [...refs.entries()].map(([ref, assetPath]) => ({ ref, assetPath }));
}

function combineEntries(...groups) {
  const refs = new Map();
  for (const entries of groups) {
    for (const entry of entries) {
      refs.set(entry.assetPath, entry);
    }
  }
  return [...refs.values()];
}

function measure(entries, label) {
  const sizes = entries.map(({ ref, assetPath }) => {
    if (!existsSync(assetPath)) fail(`Missing ${label} JavaScript asset: ${ref}`);
    const gzipBytes = gzipSync(readFileSync(assetPath)).byteLength;
    return { ref, gzipBytes };
  });
  const total = sizes.reduce((sum, item) => sum + item.gzipBytes, 0);
  for (const item of sizes) {
    console.log(`${label}-js-gzip ${item.ref}: ${item.gzipBytes} bytes`);
  }
  return total;
}

if (!existsSync(indexHtmlPath)) {
  fail(`Missing build output: ${indexHtmlPath}`);
}

const entries = collectInitialJs(readFileSync(indexHtmlPath, 'utf8'));
if (entries.length === 0) {
  fail('No initial JavaScript references found in dist/index.html');
}

const total = measure(entries, 'initial');
console.log(`initial-js-gzip total: ${total} bytes (budget ${budgetBytes} bytes)`);

if (total > budgetBytes) {
  fail(`Initial JS gzip budget exceeded: ${total} > ${budgetBytes}`);
}

const manifest = loadManifest();
const dashboardEntries = collectManifestJs(manifest, 'src/pages/DashboardPage.tsx');
const dashboardFirstRouteEntries = combineEntries(entries, dashboardEntries);
const dashboardFirstRouteTotal = measure(dashboardFirstRouteEntries, 'dashboard-first-route');
console.log(
  `dashboard-first-route-js-gzip total: ${dashboardFirstRouteTotal} bytes ` +
    `(budget ${dashboardRouteBudgetBytes} bytes)`,
);

if (dashboardFirstRouteTotal > dashboardRouteBudgetBytes) {
  fail(
    `Dashboard first-route JS gzip budget exceeded: ` +
      `${dashboardFirstRouteTotal} > ${dashboardRouteBudgetBytes}`,
  );
}
