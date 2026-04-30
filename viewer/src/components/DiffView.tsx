import { memo, useMemo, useCallback, useEffect } from 'react';
import VirtualList from './VirtualList';
import { useTranslation } from '../i18n/useTranslation';
import './Diff.css';

const VIRTUAL_LIST_STYLE: React.CSSProperties = { height: '100%' };

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

export interface DiffClaimAnchor {
  claim_id: string;
  file: string;
  line_start: number;
  line_end: number;
  source_side?: SourceSide;
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

/* ── Virtual scroll threshold ────────────────────────────────── */

const VIRTUAL_THRESHOLD = 200;
const LINE_HEIGHT = 22;

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

function findClaimIdForLine(
  line: DiffLine,
  claims: ReadonlyArray<DiffClaimAnchor>,
): string | null {
  for (const claim of claims) {
    if (diffLineMatchesClaim(line, claim)) return claim.claim_id;
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
  claimId,
  isSelected,
  onSelectClaim,
}: {
  line: DiffLine;
  claimId: string | null;
  isSelected: boolean;
  onSelectClaim?: (claimId: string) => void;
}) {
  const cls = `diff-line diff-line--${line.type}${claimId ? ' diff-line--claim-linked' : ''}${isSelected ? ' diff-line--claim-selected' : ''}`;
  const body = (
    <>
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
        aria-pressed={isSelected}
        aria-label={`${formatLineAnchor(line)} ${claimId}`}
        onClick={() => onSelectClaim(claimId)}
      >
        {body}
      </button>
    );
  }

  return (
    <div className={cls} data-line-anchor={formatLineAnchor(line)}>
      {body}
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
 * Unified diff viewer.
 *
 * Wrapped with React.memo to prevent re-renders from locale changes
 * in parent components. The `content` string is the sole render dependency;
 * `useMemo` further caches the parsed line array and stats computation.
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

  /* Parse lines — only recomputed when content changes */
  const lines = useMemo(
    () => providedLines ?? parseUnifiedDiff(content),
    [content, providedLines],
  );
  const stats = useMemo(() => computeDiffStats(lines), [lines]);
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

  /* Stable renderItem and key derivation for VirtualList */
  const renderItem = useCallback(
    (line: DiffLine) => {
      const claimId = findClaimIdForLine(line, claims);
      return (
        <DiffLineRow
          line={line}
          claimId={claimId}
          isSelected={lineMatchesSelectedClaim(line)}
          onSelectClaim={onSelectClaim}
        />
      );
    },
    [claims, lineMatchesSelectedClaim, onSelectClaim],
  );
  const getLineKey = useCallback(
    (line: DiffLine, index: number) =>
      `${line.filePath ?? '_'}:${line.type}:${line.oldLineNo ?? '_'}:${line.newLineNo ?? '_'}:${index}`,
    [],
  );

  if (lines.length === 0) {
    return null;
  }

  /* Use virtual scroll for large diffs (>= 200 lines) */
  if (lines.length >= VIRTUAL_THRESHOLD) {
    return (
      <div className="diff-view" role="region" aria-label={t('Diff.title')}>
        <VirtualList
          items={lines}
          itemHeight={LINE_HEIGHT}
          renderItem={renderItem}
          getKey={getLineKey}
          overscan={8}
          style={VIRTUAL_LIST_STYLE}
        />
      </div>
    );
  }

  /* Direct render for small diffs */
  return (
    <div className="diff-view" role="region" aria-label={t('Diff.title')}>
      {lines.map((line, i) => (
        <DiffLineRow
          key={`${line.filePath ?? '_'}:${line.type}:${line.oldLineNo ?? '_'}:${line.newLineNo ?? '_'}:${i}`}
          line={line}
          claimId={findClaimIdForLine(line, claims)}
          isSelected={lineMatchesSelectedClaim(line)}
          onSelectClaim={onSelectClaim}
        />
      ))}
    </div>
  );
});

export default DiffView;
