import { memo, useMemo, useCallback, useEffect } from 'react';
import VirtualList from './VirtualList';
import { useTranslation } from '../i18n/useTranslation';
import './Diff.css';

const VIRTUAL_LIST_STYLE: React.CSSProperties = { height: '100%' };

/* ── Line model ──────────────────────────────────────────────── */

type LineType = 'add' | 'del' | 'ctx' | 'hunk' | 'meta';

interface DiffLine {
  type: LineType;
  text: string;
  oldLineNo: number | null;
  newLineNo: number | null;
}

/* ── Parser ──────────────────────────────────────────────────── */

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

function parseUnifiedDiff(raw: string): DiffLine[] {
  const src = raw.split('\n');
  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  // Track whether we're inside a hunk so `--- ` / `+++ ` and `\ No newline`
  // markers are interpreted correctly. Inside a hunk, a content line that
  // happens to start with `-- ` or `++ ` (e.g. C++ decrement, comment) is a
  // del/add line, not a file header.
  let inHunk = false;

  for (const line of src) {
    // File-level meta: always resets hunk state.
    if (line.startsWith('diff --git') || line.startsWith('index ')) {
      inHunk = false;
      lines.push({ type: 'meta', text: line, oldLineNo: null, newLineNo: null });
      continue;
    }
    // `--- ` / `+++ ` are file headers only when we're between hunks; once
    // a hunk has begun, the same prefix is content (a `-`/`+` line whose body
    // starts with `- ` / `+ `).
    if (!inHunk && (line.startsWith('--- ') || line.startsWith('+++ '))) {
      lines.push({ type: 'meta', text: line, oldLineNo: null, newLineNo: null });
      continue;
    }

    const hunkMatch = HUNK_RE.exec(line);
    if (hunkMatch) {
      oldNo = Number(hunkMatch[1]);
      newNo = Number(hunkMatch[2]);
      inHunk = true;
      lines.push({ type: 'hunk', text: line, oldLineNo: null, newLineNo: null });
      continue;
    }

    // `\ No newline at end of file` — render but do not advance line numbers.
    if (inHunk && line.startsWith('\\')) {
      lines.push({ type: 'meta', text: line, oldLineNo: null, newLineNo: null });
      continue;
    }

    if (line.startsWith('+')) {
      lines.push({ type: 'add', text: line.slice(1), oldLineNo: null, newLineNo: newNo });
      newNo += 1;
    } else if (line.startsWith('-')) {
      lines.push({ type: 'del', text: line.slice(1), oldLineNo: oldNo, newLineNo: null });
      oldNo += 1;
    } else {
      // Context line (starts with ' ') or empty line within a hunk
      const text = line.length > 0 && line[0] === ' ' ? line.slice(1) : line;
      lines.push({ type: 'ctx', text, oldLineNo: oldNo, newLineNo: newNo });
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

export function computeDiffStats(lines: DiffLine[]): DiffStats {
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

/* ── Single line renderer ────────────────────────────────────── */

function DiffLineRow({ line }: { line: DiffLine }) {
  const cls = `diff-line diff-line--${line.type}`;
  return (
    <div className={cls}>
      <span className="diff-line__lineno" aria-hidden="true">
        {line.oldLineNo ?? ''}
      </span>
      <span className="diff-line__lineno" aria-hidden="true">
        {line.newLineNo ?? ''}
      </span>
      <span className="diff-line__text">
        <code>{line.text}</code>
      </span>
    </div>
  );
}

/* ── DiffView (React.memo) ───────────────────────────────────── */

interface DiffViewProps {
  content: string;
  onStats?: (stats: DiffStats) => void;
}

/**
 * Unified diff viewer.
 *
 * Wrapped with React.memo to prevent re-renders from locale changes
 * in parent components. The `content` string is the sole render dependency;
 * `useMemo` further caches the parsed line array and stats computation.
 */
const DiffView = memo(function DiffView({ content, onStats }: DiffViewProps) {
  const { t } = useTranslation();

  /* Parse lines — only recomputed when content changes */
  const lines = useMemo(() => parseUnifiedDiff(content), [content]);
  const stats = useMemo(() => computeDiffStats(lines), [lines]);

  /* Emit stats to parent (for BottomMiniPanel) — post-render side effect */
  useEffect(() => {
    if (onStats) {
      onStats(stats);
    }
  }, [stats, onStats]);

  /* Stable renderItem and key derivation for VirtualList */
  const renderItem = useCallback(
    (line: DiffLine) => <DiffLineRow line={line} />,
    [],
  );
  const getLineKey = useCallback(
    (line: DiffLine, index: number) =>
      `${line.type}:${line.oldLineNo ?? '_'}:${line.newLineNo ?? '_'}:${index}`,
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
          key={`${line.type}:${line.oldLineNo ?? '_'}:${line.newLineNo ?? '_'}:${i}`}
          line={line}
        />
      ))}
    </div>
  );
});

export default DiffView;
