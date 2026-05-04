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

const SUMMARY_BAR_STYLE: CSSProperties = { contain: 'layout' };

/* ── Line model ──────────────────────────────────────────────── */

type LineType = 'add' | 'del' | 'ctx' | 'hunk' | 'meta';
type SourceSide = 'old' | 'new' | 'either';

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

function findClaimForLine(
  line: DiffLine,
  claims: ReadonlyArray<DiffClaimAnchor>,
): DiffClaimAnchor | null {
  for (const claim of claims) {
    if (diffLineMatchesClaim(line, claim)) return claim;
  }
  return null;
}

function formatLineAnchor(line: DiffLine): string {
  const lineNo = line.newLineNo ?? line.oldLineNo;
  return `${line.filePath ?? line.newPath ?? line.oldPath ?? 'diff'}${lineNo ? `:${lineNo}` : ''}`;
}

/* ── Single line renderer ────────────────────────────────────── */

function DiffLineRow({
  line,
  claim,
  isSelected,
  onSelectClaim,
  t,
}: {
  line: DiffLine;
  claim: DiffClaimAnchor | null;
  isSelected: boolean;
  onSelectClaim?: (claimId: string) => void;
  t?: (key: string, params?: Record<string, string | number>) => string;
}) {
  const claimId = claim?.claim_id ?? null;
  const verdict = claim?.verdict ?? null;
  const isHunk = line.type === 'hunk';
  const cls = `diff-line diff-line--${line.type}${isHunk ? ' diff-hunk-marker' : ''}${claimId ? ' diff-line--claim-linked' : ''}${isSelected ? ' diff-line--claim-selected' : ''}`;
  const hunkMarkerProps = isHunk ? { 'data-hunk-mark': '§' } : {};
  // Visual gutter dot. The parent .diff-line button already exposes the
  // claim id via aria-label and is the accessible interaction surface, so
  // the dot itself stays decorative (aria-hidden) and lets clicks fall
  // through to the row (CSS sets pointer-events: none). This avoids the
  // invalid HTML of nesting a focusable element inside another <button>.
  const dotLabel =
    claimId && verdict && t
      ? t('Claim_inspector.claim_dot_label', { claim_id: claimId, verdict })
      : claimId ?? '';
  const dot =
    claimId !== null ? (
      <span
        className={`diff-line__claim-dot${verdict ? ` diff-line__claim-dot--${verdict}` : ''}`}
        aria-hidden="true"
        title={dotLabel || undefined}
        data-claim-dot-id={claimId}
      />
    ) : null;
  const body = (
    <>
      {dot}
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

  if (claimId && onSelectClaim) {
    return (
      <button
        type="button"
        className={cls}
        data-claim-id={claimId}
        data-line-anchor={formatLineAnchor(line)}
        {...hunkMarkerProps}
        aria-pressed={isSelected}
        aria-label={`${formatLineAnchor(line)} ${claimId}`}
        onClick={() => onSelectClaim(claimId)}
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

/* ── File section view ──────────────────────────────────────── */

function DiffFileSectionView({
  section,
  index,
  sectionId,
  expanded,
  onToggle,
  onHeaderRef,
  claims,
  selectedClaimId,
  lineMatchesSelectedClaim,
  onSelectClaim,
  t,
}: {
  section: DiffFileSection;
  index: number;
  sectionId: string;
  expanded: boolean;
  onToggle: () => void;
  onHeaderRef: (el: HTMLElement | null) => void;
  claims: ReadonlyArray<DiffClaimAnchor>;
  selectedClaimId: string | null;
  lineMatchesSelectedClaim: (line: DiffLine) => boolean;
  onSelectClaim?: (claimId: string) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const { filePath, oldPath, isRename, stats } = section;
  const displayName = filePath ?? t('Diff.file_unknown');
  const renamedFrom = isRename && oldPath && oldPath !== filePath ? oldPath : null;
  const icon = getFileIcon(filePath);
  const ariaLabel = `${displayName} (+${stats.added} -${stats.removed})`;
  const collapsedClass = expanded ? '' : ' diff-file-section--collapsed';

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
        {section.lines.map((line, i) => (
          <DiffLineRow
            key={`${line.filePath ?? '_'}:${line.type}:${line.oldLineNo ?? '_'}:${line.newLineNo ?? '_'}:${i}`}
            line={line}
            claim={findClaimForLine(line, claims)}
            isSelected={lineMatchesSelectedClaim(line) && selectedClaimId !== null}
            onSelectClaim={onSelectClaim}
            t={t}
          />
        ))}
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
   * highlighted line is reachable. Only applies once per selectedClaimId. */
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
  }, [selectedClaimId, claims, sections, sectionKeyForIndex]);

  /* Track active file in viewport for summary-bar highlight. Uses
   * IntersectionObserver on the sticky headers so we don't re-flow on
   * every scroll event. */
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const headerRefs = useRef<Array<HTMLElement | null>>([]);
  const setHeaderRef = useCallback(
    (index: number) => (el: HTMLElement | null) => {
      headerRefs.current[index] = el;
    },
    [],
  );

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
  }, [sections]);

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
    <div className="diff-view" role="region" aria-label={t('Diff.title')} ref={containerRef}>
      {sections.length > 1 && (
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
              claims={claims}
              selectedClaimId={selectedClaimId}
              lineMatchesSelectedClaim={lineMatchesSelectedClaim}
              onSelectClaim={onSelectClaim}
              t={t}
            />
          );
        })}
      </div>
    </div>
  );
});

export default DiffView;
