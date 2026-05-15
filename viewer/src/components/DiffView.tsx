import {
  memo,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from 'react';
import { useTranslation } from '../i18n/useTranslation';
import './Diff.css';

/* Files with more than this many content+hunk+meta lines start collapsed. */
const FILE_AUTO_COLLAPSE_THRESHOLD = 200;

/* Files with more than this many content+hunk+meta lines are rendered in a
 * truncated form (only LARGE_FILE_RENDER_LIMIT lines) when expanded; the
 * remainder is gated behind a "Show all N lines" button. This protects the
 * DOM from explosion when the user expands a single huge file (e.g. a
 * lockfile or generated diff). The truncation itself is the guard — no
 * confirm modal — so the user can always opt-in to the full render. */
const LARGE_FILE_THRESHOLD = 5000;
const LARGE_FILE_RENDER_LIMIT = 1000;
const MAX_CLAIM_LOOKUP_RANGE_LINES = LARGE_FILE_THRESHOLD;

const SUMMARY_BAR_STYLE: CSSProperties = { contain: 'layout' };

/* ── Line model ──────────────────────────────────────────────── */

type LineType = 'add' | 'del' | 'ctx' | 'hunk' | 'meta';
type SourceSide = 'old' | 'new' | 'either';
export type DiffViewMode = 'unified' | 'split';

export interface DiffLine {
  type: LineType;
  text: string;
  oldLineNo: number | null;
  newLineNo: number | null;
  filePath: string | null;
  oldPath: string | null;
  newPath: string | null;
}

export type DiffClaimVerdict =
  | 'verified'
  | 'weak'
  | 'not_proven'
  | 'contradicted'
  | 'rejected';

const VERDICT_SEVERITY: Record<DiffClaimVerdict, number> = {
  verified: 0,
  weak: 1,
  not_proven: 2,
  contradicted: 3,
  rejected: 4,
};

function worstClaim(claims: readonly DiffClaimAnchor[]): DiffClaimAnchor | undefined {
  let worst: DiffClaimAnchor | undefined;
  let worstSev = -1;
  for (const c of claims) {
    if (c.verdict && VERDICT_SEVERITY[c.verdict] > worstSev) {
      worst = c;
      worstSev = VERDICT_SEVERITY[c.verdict];
    }
  }
  return worst;
}

function worstVerdict(claims: readonly DiffClaimAnchor[]): DiffClaimVerdict | undefined {
  return worstClaim(claims)?.verdict;
}

export interface DiffClaimAnchor {
  claim_id: string;
  file: string;
  line_start: number;
  line_end: number;
  source_side?: SourceSide;
  /**
   * Verdict used to color the gutter dot indicator. Optional for
   * backwards-compatibility with callers that only need claim mapping.
   */
  verdict?: DiffClaimVerdict;
}

export interface DiffSourceLine {
  file: string;
  side: Exclude<SourceSide, 'either'>;
  line_no: number;
  type: Extract<LineType, 'add' | 'del' | 'ctx'>;
  text: string;
}

export interface DiffFocusTarget {
  file: string;
  line: number;
  side?: SourceSide;
}

export type SplitDiffRow =
  | { kind: 'span'; line: DiffLine }
  | { kind: 'pair'; oldLine: DiffLine | null; newLine: DiffLine | null };

/* ── Parser ──────────────────────────────────────────────────── */

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;
const DRIVE_PREFIX_RE = /^[A-Za-z]:/;
const OCTAL_ESCAPE_RE = /^[0-7]{1,3}/;
const C_STYLE_ESCAPE_CHARS = new Set(['\\', '"', 't', 'n', 'r', 'a', 'b', 'f', 'v']);

function normalizePathSeparators(value: string): string {
  return value.replace(/\\/g, '/');
}

function looksLikeRawWindowsQuotedPath(value: string): boolean {
  return (
    (value.startsWith('a\\') || value.startsWith('b\\') || DRIVE_PREFIX_RE.test(value)) ||
    (!value.includes('/') && value.includes('\\') && !/[\\][tnrabfv"0-7]/.test(value))
  );
}

function normalizeQuotedDiffPathSeparators(value: string): string {
  if (looksLikeRawWindowsQuotedPath(value)) return normalizePathSeparators(value);
  let out = '';
  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (ch !== '\\') {
      out += ch;
      continue;
    }
    const next = value[i + 1];
    if (!next) {
      out += '/';
      continue;
    }
    if (C_STYLE_ESCAPE_CHARS.has(next) || /[0-7]/.test(next)) {
      out += `\\${next}`;
      i += 1;
      continue;
    }
    out += '/';
  }
  return out;
}

function unquoteGitPath(value: string): string {
  let out = '';
  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (ch !== '\\') {
      out += ch;
      continue;
    }
    const next = value[i + 1];
    if (!next) {
      out += '\\';
      continue;
    }
    if (next === 't') out += '\t';
    else if (next === 'n') out += '\n';
    else if (next === 'r') out += '\r';
    else if (next === 'a') out += '\u0007';
    else if (next === 'b') out += '\b';
    else if (next === 'f') out += '\f';
    else if (next === 'v') out += '\v';
    else if (next === '"' || next === '\\') out += next;
    else if (/[0-7]/.test(next)) {
      const octal = value.slice(i + 1).match(OCTAL_ESCAPE_RE)?.[0] ?? next;
      out += String.fromCharCode(Number.parseInt(octal, 8));
      i += octal.length - 1;
    } else {
      out += next;
    }
    i += 1;
  }
  return out;
}

function splitGitHeaderTokens(rest: string): string[] {
  const tokens: string[] = [];
  let current = '';
  let inQuotes = false;
  let escaped = false;
  for (const ch of rest) {
    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }
    if (ch === '\\') {
      current += ch;
      escaped = true;
      continue;
    }
    if (ch === '"') {
      current += ch;
      inQuotes = !inQuotes;
      continue;
    }
    if (!inQuotes && /\s/.test(ch)) {
      if (current) {
        tokens.push(current);
        current = '';
      }
      continue;
    }
    current += ch;
  }
  if (current) tokens.push(current);
  return tokens;
}

function stripDiffPrefix(path: string): string {
  return path.startsWith('a/') || path.startsWith('b/') ? path.slice(2) : path;
}

function normalizeRelativeDiffPath(raw: string): string | null {
  const path = raw.trim();
  if (
    !path ||
    path === '/dev/null' ||
    path.startsWith('/') ||
    path.startsWith('//') ||
    DRIVE_PREFIX_RE.test(path)
  ) {
    return null;
  }
  const parts: string[] = [];
  for (const part of path.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') {
      if (parts.length === 0) return null;
      parts.pop();
      continue;
    }
    parts.push(part);
  }
  return parts.length > 0 ? parts.join('/').normalize('NFC') : null;
}

function parseDiffGitHeaderPaths(line: string): [string | null, string | null] | null {
  const prefix = 'diff --git ';
  if (!line.startsWith(prefix)) return null;
  const tokens = splitGitHeaderTokens(line.slice(prefix.length));
  if (tokens.length < 2) return null;
  return [normalizeDiffPath(tokens[0] ?? ''), normalizeDiffPath(tokens[1] ?? '')];
}

function normalizeDiffPath(raw: string): string | null {
  let path = raw.trim();
  if (!path || path === '/dev/null') return null;
  if (path.startsWith('"') && path.endsWith('"')) {
    path = unquoteGitPath(normalizeQuotedDiffPathSeparators(path.slice(1, -1)));
  } else {
    path = normalizePathSeparators(path);
  }
  return normalizeRelativeDiffPath(stripDiffPrefix(path));
}

function normalizeClaimPath(raw: string): string | null {
  return normalizeDiffPath(raw);
}

export function parseUnifiedDiff(raw: string): DiffLine[] {
  const normalizedRaw = raw.endsWith('\n') ? raw.slice(0, -1) : raw;
  if (!normalizedRaw) return [];
  const src = normalizedRaw.split('\n');
  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  let oldPath: string | null = null;
  let newPath: string | null = null;
  // Track whether we're inside a hunk so `--- ` / `+++ ` and `\ No newline`
  // markers are interpreted correctly. Inside a hunk, a content line that
  // happens to start with `-- ` or `++ ` (e.g. C++ decrement, comment) is a
  // del/add line, not a file header.
  let inHunk = false;

  const makeLine = (
    type: LineType,
    text: string,
    oldLineNo: number | null,
    newLineNo: number | null,
  ): DiffLine => ({
    type,
    text,
    oldLineNo,
    newLineNo,
    filePath: newPath ?? oldPath,
    oldPath,
    newPath,
  });

  for (const line of src) {
    // File-level meta: always resets hunk state.
    if (line.startsWith('diff --git')) {
      const gitPaths = parseDiffGitHeaderPaths(line);
      oldPath = gitPaths?.[0] ?? null;
      newPath = gitPaths?.[1] ?? null;
      inHunk = false;
      lines.push(makeLine('meta', line, null, null));
      continue;
    }
    if (line.startsWith('index ')) {
      inHunk = false;
      lines.push(makeLine('meta', line, null, null));
      continue;
    }
    // `--- ` / `+++ ` are file headers only when we're between hunks; once
    // a hunk has begun, the same prefix is content (a `-`/`+` line whose body
    // starts with `- ` / `+ `).
    if (!inHunk && line.startsWith('--- ')) {
      oldPath = normalizeDiffPath(line.slice(4));
      lines.push(makeLine('meta', line, null, null));
      continue;
    }
    if (!inHunk && line.startsWith('+++ ')) {
      newPath = normalizeDiffPath(line.slice(4));
      lines.push(makeLine('meta', line, null, null));
      continue;
    }

    const hunkMatch = HUNK_RE.exec(line);
    if (hunkMatch) {
      oldNo = Number(hunkMatch[1]);
      newNo = Number(hunkMatch[2]);
      inHunk = true;
      lines.push(makeLine('hunk', line, null, null));
      continue;
    }

    // `\ No newline at end of file` — render but do not advance line numbers.
    if (inHunk && line.startsWith('\\')) {
      lines.push(makeLine('meta', line, null, null));
      continue;
    }

    if (line.startsWith('+')) {
      lines.push(makeLine('add', line.slice(1), null, newNo));
      newNo += 1;
    } else if (line.startsWith('-')) {
      lines.push(makeLine('del', line.slice(1), oldNo, null));
      oldNo += 1;
    } else {
      // Context line (starts with ' ') or empty line within a hunk
      const text = line.length > 0 && line[0] === ' ' ? line.slice(1) : line;
      lines.push(makeLine('ctx', text, oldNo, newNo));
      oldNo += 1;
      newNo += 1;
    }
  }

  return lines;
}

/* ── Stats ───────────────────────────────────────────────────── */

export interface DiffStats {
  files: number;
  additions: number;
  deletions: number;
}

export function computeDiffStats(lines: ReadonlyArray<DiffLine>): DiffStats {
  let files = 0;
  let additions = 0;
  let deletions = 0;
  for (const l of lines) {
    if (l.type === 'meta' && l.text.startsWith('diff --git')) files += 1;
    else if (l.type === 'add') additions += 1;
    else if (l.type === 'del') deletions += 1;
  }
  return { files, additions, deletions };
}

/* ── File-section grouping ───────────────────────────────────── */

export interface DiffFileSection {
  /** Display path (newPath when known, falls back to oldPath). null = pre-amble. */
  filePath: string | null;
  /** Original path before rename, when oldPath != newPath. */
  oldPath: string | null;
  newPath: string | null;
  /** True when oldPath/newPath are both set and differ. */
  isRename: boolean;
  stats: { added: number; removed: number };
  lines: DiffLine[];
}

/**
 * Group a flat parsed diff into per-file sections. Each `diff --git ...`
 * meta line opens a new section; lines preceding the first `diff --git`
 * are grouped into a leading section with `filePath: null` (rare).
 *
 * Renames are detected when both `oldPath` and `newPath` are present and
 * differ; the section header may render "old -> new".
 */
export function parseDiffFileSections(
  lines: ReadonlyArray<DiffLine>,
): DiffFileSection[] {
  const sections: DiffFileSection[] = [];
  let current: DiffFileSection | null = null;

  const flush = () => {
    if (current && current.lines.length > 0) sections.push(current);
    current = null;
  };

  const startSection = (line: DiffLine): DiffFileSection => ({
    filePath: line.newPath ?? line.oldPath ?? line.filePath,
    oldPath: line.oldPath,
    newPath: line.newPath,
    isRename: Boolean(line.oldPath && line.newPath && line.oldPath !== line.newPath),
    stats: { added: 0, removed: 0 },
    lines: [],
  });

  for (const line of lines) {
    if (line.type === 'meta' && line.text.startsWith('diff --git')) {
      flush();
      current = startSection(line);
    } else if (current === null) {
      // Pre-amble lines before any `diff --git` (e.g. raw `--- ` / `+++ `
      // or commit headers). Bucket into a header-less section so they remain
      // visible.
      current = {
        filePath: null,
        oldPath: null,
        newPath: null,
        isRename: false,
        stats: { added: 0, removed: 0 },
        lines: [],
      };
    }

    // Update tracked paths from inline `--- ` / `+++ ` headers.
    if (line.type === 'meta' && line.text.startsWith('--- ') && current && current.oldPath === null) {
      current.oldPath = line.oldPath;
      if (current.filePath === null) current.filePath = line.oldPath;
    }
    if (line.type === 'meta' && line.text.startsWith('+++ ') && current) {
      if (line.newPath !== null) {
        current.newPath = line.newPath;
        current.filePath = line.newPath;
        if (current.oldPath !== null && current.oldPath !== line.newPath) {
          current.isRename = true;
        }
      }
    }

    if (line.type === 'add') current.stats.added += 1;
    else if (line.type === 'del') current.stats.removed += 1;

    current.lines.push(line);
  }

  flush();
  return sections;
}

/* ── File icon by extension ──────────────────────────────────── */

const EXT_ICON: Record<string, string> = {
  ts: 'TS',
  tsx: 'TSX',
  js: 'JS',
  jsx: 'JSX',
  py: 'PY',
  md: 'MD',
  json: '{ }',
  css: 'CSS',
  scss: 'CSS',
  html: '<>',
  yaml: 'YML',
  yml: 'YML',
  toml: 'TOML',
  sh: 'SH',
  go: 'GO',
  rs: 'RS',
  rb: 'RB',
  java: 'JV',
  sql: 'SQL',
  txt: 'TXT',
};

function getFileIcon(filePath: string | null): string {
  if (!filePath) return '...';
  const idx = filePath.lastIndexOf('.');
  if (idx < 0 || idx === filePath.length - 1) return 'FILE';
  const ext = filePath.slice(idx + 1).toLowerCase();
  return EXT_ICON[ext] ?? ext.slice(0, 4).toUpperCase();
}

/* ── Claim matching ───────────────────────────────────────────── */

function isContentLine(line: DiffLine): line is DiffLine & { type: 'add' | 'del' | 'ctx' } {
  return line.type === 'add' || line.type === 'del' || line.type === 'ctx';
}

function isInRange(lineNo: number | null, claim: DiffClaimAnchor): boolean {
  if (lineNo == null || claim.line_start <= 0) return false;
  const end = claim.line_end > 0 ? claim.line_end : claim.line_start;
  return lineNo >= claim.line_start && lineNo <= end;
}

function claimMatchesFile(line: DiffLine, claim: DiffClaimAnchor): boolean {
  const claimPath = normalizeClaimPath(claim.file);
  if (!claimPath) return false;
  return [line.filePath, line.oldPath, line.newPath]
    .filter((path): path is string => Boolean(path))
    .some((path) => normalizeClaimPath(path) === claimPath);
}

function matchingSide(line: DiffLine, claim: DiffClaimAnchor): DiffSourceLine['side'] | null {
  const side = claim.source_side ?? 'either';
  if (side !== 'old' && isInRange(line.newLineNo, claim)) return 'new';
  if (side !== 'new' && isInRange(line.oldLineNo, claim)) return 'old';
  return null;
}

export function diffLineMatchesClaim(line: DiffLine, claim: DiffClaimAnchor): boolean {
  return isContentLine(line) && claimMatchesFile(line, claim) && matchingSide(line, claim) !== null;
}

export function getClaimSourceLines(
  lines: ReadonlyArray<DiffLine>,
  claim: DiffClaimAnchor,
): DiffSourceLine[] {
  const result: DiffSourceLine[] = [];
  for (const line of lines) {
    if (!isContentLine(line) || !claimMatchesFile(line, claim)) continue;
    const side = matchingSide(line, claim);
    if (side == null) continue;
    const lineNo = side === 'new' ? line.newLineNo : line.oldLineNo;
    if (lineNo == null) continue;
    result.push({
      file: line.filePath ?? line.newPath ?? line.oldPath ?? claim.file,
      side,
      line_no: lineNo,
      type: line.type,
      text: line.text,
    });
  }
  return result;
}

export function diffLineMatchesFocusTarget(line: DiffLine, target: DiffFocusTarget): boolean {
  if (!isContentLine(line)) return false;
  const targetPath = normalizeClaimPath(target.file);
  if (!targetPath) return false;
  const paths = normalizedLinePaths(line);
  if (!paths.includes(targetPath)) return false;
  const side = target.side ?? 'either';
  if (side !== 'old' && line.newLineNo === target.line) return true;
  if (side !== 'new' && line.oldLineNo === target.line) return true;
  return false;
}

/**
 * Precomputed claim lookup: maps `"normalizedPath:side:lineNo"` to the
 * full list of claims that cover that position. Built once per `claims`
 * array, then queried per row in O(1) Map.get + O(k) array work where
 * k is the number of claims on that exact line (typically 1).
 *
 * Storing an array (not a single claim) preserves *every* claim that
 * references the same file:line. The previous single-claim map silently
 * dropped duplicates because the keying was lossy. Per-line consumers
 * (gutter dot, claim-linked styling, selected-claim highlight) decide
 * how to fold the array — see `lookupClaimsForLine` callers.
 *
 * Side is one of `"new"` / `"old"`. The lookup is queried twice per row
 * (once for each side present on the line) to mirror the
 * `matchingSide()` precedence in `diffLineMatchesClaim` (new before old
 * when `source_side === 'either'`).
 *
 * Path normalization mirrors `claimMatchesFile()` so quoted/Windows /
 * Unicode-NFD paths key identically regardless of how the diff or claim
 * spelled them.
 */
export type ClaimLookup = ReadonlyMap<string, DiffClaimAnchor[]>;

function normalizeClaimLookupRange(
  claim: DiffClaimAnchor,
): { start: number; end: number } | null {
  const start = Number.isFinite(claim.line_start) ? Math.trunc(claim.line_start) : 0;
  if (start <= 0) return null;
  const rawEnd =
    Number.isFinite(claim.line_end) && claim.line_end > 0
      ? Math.trunc(claim.line_end)
      : start;
  const orderedEnd = Math.max(start, rawEnd);
  return {
    start,
    end: Math.min(orderedEnd, start + MAX_CLAIM_LOOKUP_RANGE_LINES - 1),
  };
}

export function buildClaimLookup(claims: ReadonlyArray<DiffClaimAnchor>): ClaimLookup {
  const map = new Map<string, DiffClaimAnchor[]>();
  const pushUnique = (key: string, claim: DiffClaimAnchor): void => {
    const existing = map.get(key);
    if (!existing) {
      map.set(key, [claim]);
      return;
    }
    // Dedupe by claim_id so the same claim record indexed multiple times
    // (e.g. multi-line range overlap) is not double-counted, but distinct
    // claims pointing at the same file:line are all preserved.
    if (existing.some((c) => c.claim_id === claim.claim_id)) return;
    existing.push(claim);
  };
  for (const claim of claims) {
    const claimPath = normalizeClaimPath(claim.file);
    const range = normalizeClaimLookupRange(claim);
    if (!claimPath || !range) continue;
    const side = claim.source_side ?? 'either';
    for (let n = range.start; n <= range.end; n += 1) {
      if (side !== 'old') {
        pushUnique(`${claimPath}:new:${n}`, claim);
      }
      if (side !== 'new') {
        pushUnique(`${claimPath}:old:${n}`, claim);
      }
    }
  }
  return map;
}

export function lookupClaimsForLine(line: DiffLine, lookup: ClaimLookup): DiffClaimAnchor[] {
  if (!isContentLine(line)) return [];
  // Mirror matchingSide() precedence: prefer "new" before "old" when the
  // line carries both line numbers (context line). Each line has at most
  // one filePath/oldPath/newPath spelling that could match a claim, so
  // probing all three under both sides is cheap and avoids missing a
  // match when the diff header lists `oldPath !== newPath` (rename).
  const paths = normalizedLinePaths(line);
  if (paths.length === 0) return [];
  // Collect from every (path, side) probe and dedupe by claim_id while
  // preserving order (new-side hits first to mirror prior precedence).
  const seen = new Set<string>();
  const result: DiffClaimAnchor[] = [];
  const pushFrom = (key: string): void => {
    const hits = lookup.get(key);
    if (!hits) return;
    for (const hit of hits) {
      if (seen.has(hit.claim_id)) continue;
      seen.add(hit.claim_id);
      result.push(hit);
    }
  };
  if (line.newLineNo != null) {
    for (const path of paths) {
      pushFrom(`${path}:new:${line.newLineNo}`);
    }
  }
  if (line.oldLineNo != null) {
    for (const path of paths) {
      pushFrom(`${path}:old:${line.oldLineNo}`);
    }
  }
  return result;
}

function normalizedLinePaths(line: DiffLine): string[] {
  const paths: string[] = [];
  for (const raw of [line.filePath, line.newPath, line.oldPath]) {
    if (!raw) continue;
    const normalized = normalizeClaimPath(raw);
    if (normalized && !paths.includes(normalized)) paths.push(normalized);
  }
  return paths;
}

function lookupClaimsForLineSide(
  line: DiffLine,
  lookup: ClaimLookup,
  side: Exclude<SourceSide, 'either'>,
): DiffClaimAnchor[] {
  if (!isContentLine(line)) return [];
  const lineNo = side === 'new' ? line.newLineNo : line.oldLineNo;
  if (lineNo == null) return [];
  const paths = normalizedLinePaths(line);
  if (paths.length === 0) return [];
  const seen = new Set<string>();
  const result: DiffClaimAnchor[] = [];
  for (const path of paths) {
    const hits = lookup.get(`${path}:${side}:${lineNo}`);
    if (!hits) continue;
    for (const hit of hits) {
      if (seen.has(hit.claim_id)) continue;
      seen.add(hit.claim_id);
      result.push(hit);
    }
  }
  return result;
}

export function getRenderedDiffLines(
  lines: ReadonlyArray<DiffLine>,
  expanded: boolean,
  showAllLines: boolean,
): ReadonlyArray<DiffLine> {
  if (!expanded) return [];
  if (lines.length > LARGE_FILE_THRESHOLD && !showAllLines) {
    return lines.slice(0, LARGE_FILE_RENDER_LIMIT);
  }
  return lines;
}

function formatLineAnchor(line: DiffLine): string {
  const lineNo = line.newLineNo ?? line.oldLineNo;
  return `${line.filePath ?? line.newPath ?? line.oldPath ?? 'diff'}${lineNo ? `:${lineNo}` : ''}`;
}

export function buildSplitDiffRows(lines: ReadonlyArray<DiffLine>): SplitDiffRow[] {
  const rows: SplitDiffRow[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line) break;
    if (line.type === 'meta' || line.type === 'hunk') {
      rows.push({ kind: 'span', line });
      index += 1;
      continue;
    }
    if (line.type === 'ctx') {
      rows.push({ kind: 'pair', oldLine: line, newLine: line });
      index += 1;
      continue;
    }
    if (line.type === 'del') {
      const dels: DiffLine[] = [];
      while (lines[index]?.type === 'del') {
        dels.push(lines[index]!);
        index += 1;
      }
      const adds: DiffLine[] = [];
      while (lines[index]?.type === 'add') {
        adds.push(lines[index]!);
        index += 1;
      }
      const pairCount = Math.max(dels.length, adds.length);
      for (let i = 0; i < pairCount; i += 1) {
        rows.push({ kind: 'pair', oldLine: dels[i] ?? null, newLine: adds[i] ?? null });
      }
      continue;
    }
    const adds: DiffLine[] = [];
    while (lines[index]?.type === 'add') {
      adds.push(lines[index]!);
      index += 1;
    }
    for (const add of adds) {
      rows.push({ kind: 'pair', oldLine: null, newLine: add });
    }
  }
  return rows;
}

/* ── Single line renderer ────────────────────────────────────── */

function DiffLineRow({
  line,
  claims: rowClaims,
  selectedClaimId,
  onSelectClaim,
  t,
}: {
  line: DiffLine;
  /**
   * All claims that anchor to this line. Empty when the line has no
   * associated claims; multiple entries are preserved so we never
   * silently drop a claim that shares a file:line with another.
   */
  claims: ReadonlyArray<DiffClaimAnchor>;
  /** Currently-selected claim id, or null when nothing is selected. */
  selectedClaimId: string | null;
  onSelectClaim?: (claimId: string) => void;
  t?: (key: string, params?: Record<string, string | number>) => string;
}) {
  const hasClaims = rowClaims.length > 0;
  // Prefer the selected claim when this row carries it. Otherwise use
  // the highest-severity verdict so the default click target matches
  // the aggregated dot color.
  const selectedOnRow = selectedClaimId
    ? rowClaims.find((c) => c.claim_id === selectedClaimId) ?? null
    : null;
  const primary = selectedOnRow ?? worstClaim(rowClaims) ?? (rowClaims[0] ?? null);
  const isSelected = selectedOnRow !== null;
  const primaryClaimId = primary?.claim_id ?? null;
  const isHunk = line.type === 'hunk';
  const cls = `diff-line diff-line--${line.type}${isHunk ? ' diff-hunk-marker' : ''}${hasClaims ? ' diff-line--claim-linked' : ''}${isSelected ? ' diff-line--claim-selected' : ''}`;
  const hunkMarkerProps = isHunk ? { 'data-hunk-mark': '§' } : {};
  // Visual gutter dot. The parent .diff-line button already exposes the
  // claim id via aria-label and is the accessible interaction surface, so
  const verdictTitle = (claim: DiffClaimAnchor): string => {
    if (claim.verdict && t) {
      return t('Claim_inspector.claim_dot_label', {
        claim_id: claim.claim_id,
        verdict: claim.verdict,
      });
    }
    return claim.claim_id;
  };
  const aggregated = hasClaims ? worstVerdict(rowClaims) : undefined;
  const claimCount = rowClaims.length;
  const dotNode = hasClaims ? (
    <span className="diff-line__claim-indicator" aria-hidden="true">
      <span
        className={`diff-line__claim-dot${aggregated ? ` diff-line__claim-dot--${aggregated}` : ''}`}
        title={rowClaims.map(verdictTitle).join(', ') || undefined}
        data-claim-dot-id={rowClaims[0].claim_id}
      />
      {claimCount >= 2 && (
        <span className={`diff-line__claim-count${aggregated ? ` diff-line__claim-count--${aggregated}` : ''}`}>
          {claimCount}
        </span>
      )}
    </span>
  ) : null;
  const changeIndicator = line.type === 'add' ? '+' : line.type === 'del' ? '−' : '';
  const body = (
    <>
      <span className="diff-line__change-indicator" aria-hidden="true">
        {changeIndicator}
      </span>
      {dotNode}
      <span className="diff-line__lineno" aria-hidden="true">
        {line.oldLineNo ?? ''}
      </span>
      <span className="diff-line__lineno" aria-hidden="true">
        {line.newLineNo ?? ''}
      </span>
      <span className="diff-line__text">
        <code>{line.text}</code>
      </span>
    </>
  );

  if (primaryClaimId && onSelectClaim) {
    // Click selects the primary claim. Additional claims on the same
    // line are still discoverable via their dots' titles and via the
    // ClaimInspector list; we cannot expose multiple click targets
    // without nesting buttons (invalid HTML).
    const claimDescription = rowClaims.map(verdictTitle).join(', ');
    const ariaLabel = `${formatLineAnchor(line)} ${claimDescription}`;
    return (
      <button
        type="button"
        className={cls}
        data-claim-id={primaryClaimId}
        data-claim-ids={rowClaims.map((c) => c.claim_id).join(',')}
        data-line-anchor={formatLineAnchor(line)}
        {...hunkMarkerProps}
        aria-pressed={isSelected}
        aria-label={ariaLabel}
        title={claimDescription || undefined}
        onClick={() => onSelectClaim(primaryClaimId)}
      >
        {body}
      </button>
    );
  }

  return (
    <div className={cls} data-line-anchor={formatLineAnchor(line)} {...hunkMarkerProps}>
      {body}
    </div>
  );
}

function SplitDiffCell({
  line,
  side,
  claims: rowClaims,
  selectedClaimId,
  onSelectClaim,
  t,
}: {
  line: DiffLine | null;
  side: Exclude<SourceSide, 'either'>;
  claims: ReadonlyArray<DiffClaimAnchor>;
  selectedClaimId: string | null;
  onSelectClaim?: (claimId: string) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  if (line === null) {
    return (
      <div className={`diff-split-cell diff-split-cell--${side} diff-split-cell--empty`} aria-hidden="true">
        <span className="diff-line__lineno" />
        <span className="diff-line__text" />
      </div>
    );
  }

  const hasClaims = rowClaims.length > 0;
  const selectedOnCell = selectedClaimId
    ? rowClaims.find((c) => c.claim_id === selectedClaimId) ?? null
    : null;
  const primary = selectedOnCell ?? worstClaim(rowClaims) ?? (rowClaims[0] ?? null);
  const primaryClaimId = primary?.claim_id ?? null;
  const isSelected = selectedOnCell !== null;
  const cls = `diff-split-cell diff-split-cell--${side} diff-split-cell--${line.type}${hasClaims ? ' diff-line--claim-linked' : ''}${isSelected ? ' diff-line--claim-selected' : ''}`;
  const lineNo = side === 'new' ? line.newLineNo : line.oldLineNo;
  const verdictTitle = (claim: DiffClaimAnchor): string => {
    if (claim.verdict) {
      return t('Claim_inspector.claim_dot_label', {
        claim_id: claim.claim_id,
        verdict: claim.verdict,
      });
    }
    return claim.claim_id;
  };
  const aggregated = hasClaims ? worstVerdict(rowClaims) : undefined;
  const claimCount = rowClaims.length;
  const dotNode = hasClaims ? (
    <span className="diff-line__claim-indicator" aria-hidden="true">
      <span
        className={`diff-line__claim-dot${aggregated ? ` diff-line__claim-dot--${aggregated}` : ''}`}
        title={rowClaims.map(verdictTitle).join(', ') || undefined}
        data-claim-dot-id={rowClaims[0].claim_id}
      />
      {claimCount >= 2 && (
        <span className={`diff-line__claim-count${aggregated ? ` diff-line__claim-count--${aggregated}` : ''}`}>
          {claimCount}
        </span>
      )}
    </span>
  ) : null;
  const markerChar = line.type === 'add' ? '+' : line.type === 'del' ? '−' : ' ';
  const srText =
    line.type === 'add'
      ? t('Diff.line_added')
      : line.type === 'del'
        ? t('Diff.line_removed')
        : null;
  const body = (
    <>
      {dotNode}
      <span className="diff-line__lineno" aria-hidden="true">
        {lineNo ?? ''}
      </span>
      <span className="diff-line__marker" aria-hidden="true">{markerChar}</span>
      {srText && <span className="sr-only">{srText}</span>}
      <span className="diff-line__text">
        <code>{line.text}</code>
      </span>
    </>
  );

  if (primaryClaimId && onSelectClaim) {
    const claimDescription = rowClaims.map(verdictTitle).join(', ');
    return (
      <button
        type="button"
        className={cls}
        data-claim-id={primaryClaimId}
        data-claim-ids={rowClaims.map((c) => c.claim_id).join(',')}
        data-line-anchor={formatLineAnchor(line)}
        data-line-side={side}
        aria-pressed={isSelected}
        aria-label={`${side} ${formatLineAnchor(line)} ${claimDescription}`}
        title={claimDescription || undefined}
        onClick={() => onSelectClaim(primaryClaimId)}
      >
        {body}
      </button>
    );
  }

  return (
    <div className={cls} data-line-anchor={formatLineAnchor(line)} data-line-side={side}>
      {body}
    </div>
  );
}

function SplitDiffRowView({
  row,
  claimLookup,
  selectedClaimId,
  lineMatchesSelectedClaim,
  onSelectClaim,
  t,
}: {
  row: SplitDiffRow;
  claimLookup: ClaimLookup;
  selectedClaimId: string | null;
  lineMatchesSelectedClaim: (line: DiffLine) => boolean;
  onSelectClaim?: (claimId: string) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  if (row.kind === 'span') {
    return (
      <div className="diff-split-row diff-split-row--span">
        <DiffLineRow
          line={row.line}
          claims={lookupClaimsForLine(row.line, claimLookup)}
          selectedClaimId={lineMatchesSelectedClaim(row.line) ? selectedClaimId : null}
          onSelectClaim={onSelectClaim}
          t={t}
        />
      </div>
    );
  }
  return (
    <div className="diff-split-row diff-split-row--pair" data-split-row="true">
      <SplitDiffCell
        line={row.oldLine}
        side="old"
        claims={row.oldLine ? lookupClaimsForLineSide(row.oldLine, claimLookup, 'old') : []}
        selectedClaimId={
          row.oldLine && lineMatchesSelectedClaim(row.oldLine) ? selectedClaimId : null
        }
        onSelectClaim={onSelectClaim}
        t={t}
      />
      <SplitDiffCell
        line={row.newLine}
        side="new"
        claims={row.newLine ? lookupClaimsForLineSide(row.newLine, claimLookup, 'new') : []}
        selectedClaimId={
          row.newLine && lineMatchesSelectedClaim(row.newLine) ? selectedClaimId : null
        }
        onSelectClaim={onSelectClaim}
        t={t}
      />
    </div>
  );
}

/* ── File section view ──────────────────────────────────────── */

function DiffFileSectionView({
  section,
  index,
  sectionId,
  expanded,
  onToggle,
  onHeaderRef,
  claimLookup,
  selectedClaimId,
  lineMatchesSelectedClaim,
  onSelectClaim,
  showAllLines,
  onShowAllLines,
  mode,
  t,
}: {
  section: DiffFileSection;
  index: number;
  sectionId: string;
  expanded: boolean;
  onToggle: () => void;
  onHeaderRef: (el: HTMLElement | null) => void;
  claimLookup: ClaimLookup;
  selectedClaimId: string | null;
  lineMatchesSelectedClaim: (line: DiffLine) => boolean;
  onSelectClaim?: (claimId: string) => void;
  showAllLines: boolean;
  onShowAllLines: () => void;
  mode: DiffViewMode;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const { filePath, oldPath, isRename, stats } = section;
  const displayName = filePath ?? t('Diff.file_unknown');
  const renamedFrom = isRename && oldPath && oldPath !== filePath ? oldPath : null;
  const icon = getFileIcon(filePath);
  const ariaLabel = `${displayName} (+${stats.added} -${stats.removed})`;
  const collapsedClass = expanded ? '' : ' diff-file-section--collapsed';

  // Large-file truncation guard. When a single file holds more than
  // LARGE_FILE_THRESHOLD parsed lines and the user has not opted to
  // render the full list, only the first LARGE_FILE_RENDER_LIMIT lines
  // are mounted. The remainder stays unmounted (not just hidden) so the
  // DOM cost stays bounded for lockfiles and generated diffs. Claim
  // anchor selectors continue to work for the rendered prefix; the
  // overflow is exposed via a "Show all N lines" button at the bottom.
  const totalLineCount = section.lines.length;
  const isLargeFile = totalLineCount > LARGE_FILE_THRESHOLD;
  const truncated = expanded && isLargeFile && !showAllLines;
  const renderedLines = getRenderedDiffLines(section.lines, expanded, showAllLines);
  const splitRows = useMemo(() => buildSplitDiffRows(renderedLines), [renderedLines]);
  const hiddenLineCount = truncated ? totalLineCount - renderedLines.length : 0;

  return (
    <section
      className={`diff-file-section${collapsedClass}`}
      data-file-path={filePath ?? ''}
      data-file-index={index}
    >
      <div className="diff-file-header" ref={onHeaderRef}>
        <button
          type="button"
          className="diff-file-header__toggle"
          aria-expanded={expanded}
          aria-controls={sectionId}
          aria-label={ariaLabel}
          onClick={onToggle}
        >
          <span className="diff-file-header__chevron" aria-hidden="true">
            {/* CSS rotates this triangle by 90deg when expanded. */}
            &#x25B6;
          </span>
          <span className="diff-file-header__icon" aria-hidden="true">
            {icon}
          </span>
          <span className="diff-file-header__path">
            {renamedFrom ? (
              <>
                <span className="diff-file-header__path-old">{renamedFrom}</span>
                <span className="diff-file-header__path-arrow" aria-hidden="true">
                  {' → '}
                </span>
                <span className="diff-file-header__path-new">{displayName}</span>
              </>
            ) : (
              displayName
            )}
          </span>
          <span className="diff-file-header__stats" aria-hidden="true">
            <span className="diff-file-header__stat-add">+{stats.added}</span>
            <span className="diff-file-header__stat-del">-{stats.removed}</span>
          </span>
        </button>
      </div>
      <div
        id={sectionId}
        className="diff-file-section__body"
        role="region"
        aria-label={ariaLabel}
        hidden={!expanded}
      >
        {mode === 'split'
          ? splitRows.map((row, i) => (
              <SplitDiffRowView
                key={`split:${section.filePath ?? '_'}:${i}`}
                row={row}
                claimLookup={claimLookup}
                selectedClaimId={selectedClaimId}
                lineMatchesSelectedClaim={lineMatchesSelectedClaim}
                onSelectClaim={onSelectClaim}
                t={t}
              />
            ))
          : renderedLines.map((line, i) => (
              <DiffLineRow
                key={`${line.filePath ?? '_'}:${line.type}:${line.oldLineNo ?? '_'}:${line.newLineNo ?? '_'}:${i}`}
                line={line}
                claims={lookupClaimsForLine(line, claimLookup)}
                selectedClaimId={
                  lineMatchesSelectedClaim(line) ? selectedClaimId : null
                }
                onSelectClaim={onSelectClaim}
                t={t}
              />
            ))}
        {truncated && (
          <div className="diff-file-section__truncation" data-file-truncation="true">
            <p className="diff-file-section__truncation-msg">
              {t('Diff.large_file_truncated', {
                shown: renderedLines.length,
                total: totalLineCount,
              })}
            </p>
            <button
              type="button"
              className="diff-file-section__truncation-action"
              onClick={onShowAllLines}
            >
              {t('Diff.show_all_lines', { hidden: hiddenLineCount })}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

/* ── File summary bar ───────────────────────────────────────── */

function DiffFileSummaryBar({
  sections,
  activeIndex,
  onJump,
  expandedCount,
  onExpandAll,
  onCollapseAll,
  t,
}: {
  sections: ReadonlyArray<DiffFileSection>;
  activeIndex: number | null;
  onJump: (index: number) => void;
  expandedCount: number;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  if (sections.length === 0) return null;
  const allExpanded = expandedCount === sections.length;

  return (
    <div className="diff-file-summary" style={SUMMARY_BAR_STYLE} role="toolbar" aria-label={t('Diff.summary_label')}>
      <div className="diff-file-summary__actions">
        <button
          type="button"
          className="diff-file-summary__nav-btn"
          onClick={() => activeIndex !== null && activeIndex > 0 && onJump(activeIndex - 1)}
          disabled={activeIndex === null || activeIndex === 0}
        >
          {t('Diff.prev_file')}
        </button>
        <button
          type="button"
          className="diff-file-summary__nav-btn"
          onClick={() => activeIndex !== null && activeIndex < sections.length - 1 && onJump(activeIndex + 1)}
          disabled={activeIndex === null || activeIndex === sections.length - 1}
        >
          {t('Diff.next_file')}
        </button>
        <button
          type="button"
          className="diff-file-summary__action"
          onClick={allExpanded ? onCollapseAll : onExpandAll}
          aria-pressed={allExpanded}
        >
          {allExpanded ? t('Diff.collapse_all') : t('Diff.expand_all')}
        </button>
        <span className="diff-file-summary__count" aria-live="polite">
          {t('Diff.summary_count', { current: expandedCount, total: sections.length })}
        </span>
      </div>
      <ol className="diff-file-summary__list">
        {sections.map((section, i) => {
          const name = section.filePath ?? t('Diff.file_unknown');
          const active = i === activeIndex;
          return (
            <li key={`${section.filePath ?? '_'}:${i}`} className="diff-file-summary__item">
              <button
                type="button"
                className={`diff-file-summary__chip${active ? ' diff-file-summary__chip--active' : ''}`}
                aria-current={active ? 'true' : undefined}
                onClick={() => onJump(i)}
                title={name}
              >
                <span className="diff-file-summary__chip-name">{name.split('/').pop() ?? name}</span>
                <span className="diff-file-summary__chip-stats" aria-hidden="true">
                  <span className="diff-file-summary__chip-add">+{section.stats.added}</span>
                  <span className="diff-file-summary__chip-del">-{section.stats.removed}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/* ── DiffView (React.memo) ───────────────────────────────────── */

interface DiffViewProps {
  content?: string;
  lines?: ReadonlyArray<DiffLine>;
  claims?: ReadonlyArray<DiffClaimAnchor>;
  selectedClaimId?: string | null;
  onSelectClaim?: (claimId: string) => void;
  onStats?: (stats: DiffStats) => void;
  onActiveFileChange?: (index: number | null) => void;
  mode?: DiffViewMode;
  focusTarget?: DiffFocusTarget | null;
}

/**
 * Unified diff viewer with file-level collapsible sections.
 *
 * Wrapped with React.memo to prevent re-renders from locale changes
 * in parent components. The `content` string is the sole render dependency;
 * `useMemo` caches the parsed line array, file sections, and stats.
 *
 * Each file is rendered as a collapsible `<section>` with a sticky header
 * (file icon + path + add/remove counts + chevron toggle). Files larger
 * than `FILE_AUTO_COLLAPSE_THRESHOLD` (200) lines start collapsed; the
 * user can toggle each file or use the summary-bar toolbar to expand /
 * collapse all. Collapsed sections keep `.diff-line` rows in the DOM via
 * the `hidden` attribute so existing E2E selectors (`.diff-line--add`,
 * `.diff-line--meta`, etc.) continue to work and so claim-anchor scroll
 * targets stay reachable when the host expands the parent file.
 */
const DiffView = memo(function DiffView({
  content = '',
  lines: providedLines,
  claims = [],
  selectedClaimId = null,
  onSelectClaim,
  onStats,
  onActiveFileChange,
  mode = 'unified',
  focusTarget = null,
}: DiffViewProps) {
  const { t } = useTranslation();
  const reactInstanceId = useId();

  /* Parse lines — only recomputed when content changes */
  const lines = useMemo(
    () => providedLines ?? parseUnifiedDiff(content),
    [content, providedLines],
  );
  const stats = useMemo(() => computeDiffStats(lines), [lines]);
  const sections = useMemo(() => parseDiffFileSections(lines), [lines]);

  /* Precompute claim → line lookup once per claims array.
   * Replaces the previous per-row `findClaimForLine` linear scan
   * (O(rows × claims)) with a O(1) Map.get() per row. The map keys cover
   * every (file, side, lineNo) position the claim covers, so a single
   * lookup also encodes the side-precedence rules from
   * `diffLineMatchesClaim`. */
  const claimLookup = useMemo(() => buildClaimLookup(claims), [claims]);

  const lineMatchesSelectedClaim = useCallback(
    (line: DiffLine) =>
      selectedClaimId !== null &&
      claims.some((claim) => claim.claim_id === selectedClaimId && diffLineMatchesClaim(line, claim)),
    [claims, selectedClaimId],
  );

  /* Emit stats to parent (for BottomMiniPanel) — post-render side effect */
  useEffect(() => {
    if (onStats) {
      onStats(stats);
    }
  }, [stats, onStats]);

  /* Per-file collapse state. Defaults to collapsed for files larger than
   * FILE_AUTO_COLLAPSE_THRESHOLD. Keyed by `filePath || `__section_${i}__`
   * so that re-parses (e.g. content edits) preserve user toggle choices
   * for files that retain their path. */
  const sectionKeyForIndex = useCallback(
    (section: DiffFileSection, index: number): string =>
      section.filePath ?? `__section_${index}__`,
    [],
  );

  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  /* Per-section "render full file" override for large-file truncation
   * (Fix 2). A section keyed `true` here renders all of its lines; the
   * default (missing key) means truncate to LARGE_FILE_RENDER_LIMIT
   * when total > LARGE_FILE_THRESHOLD. Small files ignore this map.
   * This is independent of the collapsed map so the user's truncate /
   * show-all choice persists across collapse + re-expand cycles. */
  const [showAllLinesMap, setShowAllLinesMap] = useState<Record<string, boolean>>({});

  const setShowAllLinesForKey = useCallback((key: string) => {
    setShowAllLinesMap((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
  }, []);

  /* Auto-collapse newly-seen large files. Only sets a key the first time
   * we see it; user toggles persist across re-renders. */
  useEffect(() => {
    setCollapsed((prev) => {
      let changed = false;
      const next = { ...prev };
      sections.forEach((section, i) => {
        const key = sectionKeyForIndex(section, i);
        if (key in next) return;
        if (section.lines.length > FILE_AUTO_COLLAPSE_THRESHOLD) {
          next[key] = true;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [sections, sectionKeyForIndex]);

  const toggleSection = useCallback(
    (key: string) => {
      setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
    },
    [],
  );

  const expandAll = useCallback(() => {
    setCollapsed((prev) => {
      const next: Record<string, boolean> = { ...prev };
      sections.forEach((section, i) => {
        next[sectionKeyForIndex(section, i)] = false;
      });
      return next;
    });
  }, [sections, sectionKeyForIndex]);

  const collapseAll = useCallback(() => {
    setCollapsed((prev) => {
      const next: Record<string, boolean> = { ...prev };
      sections.forEach((section, i) => {
        next[sectionKeyForIndex(section, i)] = true;
      });
      return next;
    });
  }, [sections, sectionKeyForIndex]);

  const expandedCount = useMemo(
    () => sections.reduce((n, section, i) => (collapsed[sectionKeyForIndex(section, i)] ? n : n + 1), 0),
    [sections, collapsed, sectionKeyForIndex],
  );

  /* When a claim becomes selected, ensure its host file is expanded so the
   * highlighted line is reachable. Also opts the host section into "show
   * all" when the claim's matched row falls outside the truncated
   * prefix, so claim-to-row scroll targets remain reachable in
   * large-file mode (Fix 2). Only applies once per selectedClaimId. */
  useEffect(() => {
    if (!selectedClaimId) return;
    const claim = claims.find((c) => c.claim_id === selectedClaimId);
    if (!claim) return;
    setCollapsed((prev) => {
      let changed = false;
      const next = { ...prev };
      sections.forEach((section, i) => {
        if (!section.lines.some((line) => diffLineMatchesClaim(line, claim))) return;
        const key = sectionKeyForIndex(section, i);
        if (next[key]) {
          next[key] = false;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    setShowAllLinesMap((prev) => {
      let changed = false;
      const next = { ...prev };
      sections.forEach((section, i) => {
        if (section.lines.length <= LARGE_FILE_THRESHOLD) return;
        const key = sectionKeyForIndex(section, i);
        if (next[key]) return;
        // Probe only the truncated tail; if the claim only matches there,
        // we have to opt the file into full render so the row exists.
        const matchIdx = section.lines.findIndex((line) => diffLineMatchesClaim(line, claim));
        if (matchIdx >= LARGE_FILE_RENDER_LIMIT) {
          next[key] = true;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [selectedClaimId, claims, sections, sectionKeyForIndex]);

  useEffect(() => {
    if (!focusTarget) return;
    setCollapsed((prev) => {
      let changed = false;
      const next = { ...prev };
      sections.forEach((section, i) => {
        if (!section.lines.some((line) => diffLineMatchesFocusTarget(line, focusTarget))) return;
        const key = sectionKeyForIndex(section, i);
        if (next[key]) {
          next[key] = false;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    setShowAllLinesMap((prev) => {
      let changed = false;
      const next = { ...prev };
      sections.forEach((section, i) => {
        if (section.lines.length <= LARGE_FILE_THRESHOLD) return;
        const key = sectionKeyForIndex(section, i);
        if (next[key]) return;
        const matchIdx = section.lines.findIndex((line) =>
          diffLineMatchesFocusTarget(line, focusTarget),
        );
        if (matchIdx >= LARGE_FILE_RENDER_LIMIT) {
          next[key] = true;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [focusTarget, sections, sectionKeyForIndex]);

  /* Track active file in viewport for summary-bar highlight. Uses
   * IntersectionObserver on the sticky headers so we don't re-flow on
   * every scroll event. */
  const [activeIndex, setActiveIndex] = useState<number | null>(() => (sections.length > 0 ? 0 : null));
  const containerRef = useRef<HTMLDivElement | null>(null);
  const headerRefs = useRef<Array<HTMLElement | null>>([]);
  const setHeaderRef = useCallback(
    (index: number) => (el: HTMLElement | null) => {
      headerRefs.current[index] = el;
    },
    [],
  );

  useEffect(() => {
    setActiveIndex((current) => {
      const next =
        sections.length === 0
          ? null
          : current === null || current >= sections.length
            ? 0
            : current;
      return next;
    });
  }, [sections.length]);

  useEffect(() => {
    onActiveFileChange?.(activeIndex);
  }, [activeIndex, onActiveFileChange]);

  useEffect(() => {
    headerRefs.current.length = sections.length;
    const root = containerRef.current;
    if (!root || sections.length === 0) return;
    if (typeof IntersectionObserver === 'undefined') return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Pick the entry currently nearest the top of the scroll viewport.
        let bestIndex: number | null = null;
        let bestTop = Number.POSITIVE_INFINITY;
        for (const entry of entries) {
          const idxAttr = (entry.target as HTMLElement).dataset.headerIndex;
          if (idxAttr === undefined) continue;
          if (!entry.isIntersecting) continue;
          const top = entry.boundingClientRect.top;
          if (top >= 0 && top < bestTop) {
            bestTop = top;
            bestIndex = Number(idxAttr);
          }
        }
        if (bestIndex !== null) setActiveIndex(bestIndex);
      },
      { root, threshold: [0, 1], rootMargin: '0px 0px -70% 0px' },
    );

    headerRefs.current.forEach((el, i) => {
      if (!el) return;
      el.dataset.headerIndex = String(i);
      observer.observe(el);
    });
    return () => observer.disconnect();
  }, [sections, onActiveFileChange]);

  const jumpToFile = useCallback(
    (index: number) => {
      const section = sections[index];
      if (!section) return;
      const key = sectionKeyForIndex(section, index);
      // Expand the target file so the scroll lands inside its body.
      if (collapsed[key]) {
        setCollapsed((prev) => ({ ...prev, [key]: false }));
      }
      const el = headerRefs.current[index];
      if (el) {
        // Honor user's reduced-motion preference: skip smooth scroll animation.
        const prefersReducedMotion =
          typeof window !== 'undefined' &&
          typeof window.matchMedia === 'function' &&
          window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        el.scrollIntoView({
          behavior: prefersReducedMotion ? 'auto' : 'smooth',
          block: 'start',
        });
      }
      setActiveIndex(index);
    },
    [sections, collapsed, sectionKeyForIndex],
  );

  if (lines.length === 0) {
    return null;
  }

  return (
    <div className={`diff-view diff-view--${mode}`} role="region" aria-label={t('Diff.title')} ref={containerRef}>
      {sections.length > 0 && (
        <DiffFileSummaryBar
          sections={sections}
          activeIndex={activeIndex}
          onJump={jumpToFile}
          expandedCount={expandedCount}
          onExpandAll={expandAll}
          onCollapseAll={collapseAll}
          t={t}
        />
      )}
      <div className="diff-view__body">
        {sections.map((section, index) => {
          const key = sectionKeyForIndex(section, index);
          const expanded = !collapsed[key];
          const sectionId = `diff-file-${reactInstanceId}-${index}`;
          return (
            <DiffFileSectionView
              key={key + ':' + index}
              section={section}
              index={index}
              sectionId={sectionId}
              expanded={expanded}
              onToggle={() => toggleSection(key)}
              onHeaderRef={setHeaderRef(index)}
              claimLookup={claimLookup}
              selectedClaimId={selectedClaimId}
              lineMatchesSelectedClaim={lineMatchesSelectedClaim}
              onSelectClaim={onSelectClaim}
              showAllLines={showAllLinesMap[key] === true}
              onShowAllLines={() => setShowAllLinesForKey(key)}
              mode={mode}
              t={t}
            />
          );
        })}
      </div>
    </div>
  );
});

export default DiffView;
