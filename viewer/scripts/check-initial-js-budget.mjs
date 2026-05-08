import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

/**
 * Phase 2G/4E keep JavaScript size observable without blocking builds on a
 * hard byte ceiling. Initial JavaScript and Dashboard first-route JavaScript
 * are both reported here; Dashboard includes the route chunk, static imports,
 * and lazy children that are rendered on the first dashboard screen.
 *
 * Keep carving heavy deps into `vendor-page-deps` (excluded from modulepreload,
 * see vite.config.ts) so the shell stays small, but do not fail the build only
 * because a frontend phase crosses an arbitrary bundle threshold.
 */
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const distDir = resolve(root, process.env.AHADIFF_BUDGET_DIST_DIR ?? 'dist');
const indexHtmlPath = resolve(distDir, 'index.html');
const manifestPath = resolve(distDir, '.vite', 'manifest.json');

function fail(message) {
  console.error(message);
  process.exit(1);
}

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

function manifestKeys(entry, key, property) {
  const value = entry[property] ?? [];
  if (!Array.isArray(value)) {
    fail(`Manifest ${property} must be an array for ${key}`);
  }
  for (const item of value) {
    if (typeof item !== 'string' || item.length === 0) {
      fail(`Manifest ${property} contains an invalid key for ${key}`);
    }
  }
  return value;
}

function collectManifestJs(manifest, source, options = {}) {
  const { immediateDynamicImports = [] } = options;
  const immediateDynamicImportSet = new Set(immediateDynamicImports);
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
    for (const imported of manifestKeys(entry, key, 'imports')) {
      visit(imported);
    }
  };
  const rootKey = findManifestKey(manifest, source);
  visit(rootKey);

  if (immediateDynamicImportSet.size > 0) {
    const rootEntry = manifest[rootKey];
    if (!rootEntry) fail(`Manifest import not found: ${rootKey}`);
    for (const imported of manifestKeys(rootEntry, rootKey, 'dynamicImports')) {
      if (!immediateDynamicImportSet.has(imported)) continue;
      visit(imported);
    }
  }

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
console.log(`initial-js-gzip total: ${total} bytes (observed, no budget cap)`);

const manifest = loadManifest();
const dashboardEntries = collectManifestJs(manifest, 'src/pages/DashboardPage.tsx', {
  // GraphifyCard is rendered immediately on Dashboard. LearnModeDialog is also
  // a Dashboard dynamic import, but it is user-triggered after the first route
  // is interactive, so it stays out of this first-route observation.
  immediateDynamicImports: ['src/components/GraphifyCard.tsx'],
});
const dashboardFirstRouteEntries = combineEntries(entries, dashboardEntries);
const dashboardFirstRouteTotal = measure(dashboardFirstRouteEntries, 'dashboard-first-route');
console.log(
  `dashboard-first-route-js-gzip total: ${dashboardFirstRouteTotal} bytes ` +
    `(observed, no budget cap)`,
);
