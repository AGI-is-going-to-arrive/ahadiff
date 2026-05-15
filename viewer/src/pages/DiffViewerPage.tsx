import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import DiffView, {
  type DiffClaimAnchor,
  getClaimSourceLines,
  parseDiffFileSections,
  parseUnifiedDiff,
  type DiffFocusTarget,
  type DiffSourceLine,
  type DiffStats,
  type DiffViewMode,
} from '../components/DiffView';
import BottomMiniPanel, { type MiniPanelItem } from '../components/BottomMiniPanel';
import ClaimInspector, { type ClaimInspectorClaim, type ClaimSourceLineGroup } from '../components/ClaimInspector';
import type { ClaimSourceHunk } from '../components/EvidencePanel';
import type { ClaimVerdict } from '../components/ClaimBadge';
import { useTranslation } from '../i18n/useTranslation';
import { copyToClipboard } from '../utils/clipboard';
import { getRunArtifact } from '../api/runs';
import { ApiError } from '../api/client';
import '../components/Diff.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));

type Phase = 'loading' | 'error' | 'empty' | 'ready';
type SourceHunkSide = 'old' | 'new' | 'either';
type DiffPageClaim = ClaimInspectorClaim & {
  source_anchors: DiffClaimAnchor[];
};
type ClaimsLoadResult = {
  content: string;
  unavailable: boolean;
};
interface FocusTarget {
  file: string;
  line: number;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

const CLAIM_VERDICTS: ReadonlySet<ClaimVerdict> = new Set([
  'verified',
  'weak',
  'not_proven',
  'contradicted',
  'rejected',
]);

function toFiniteInt(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

function toSourceHunkSide(value: unknown): SourceHunkSide {
  return value === 'old' || value === 'new' || value === 'either' ? value : 'either';
}

function parseConfidence(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1) {
    return value;
  }
  if (value === 'high') return 0.9;
  if (value === 'medium') return 0.6;
  if (value === 'low') return 0.3;
  return undefined;
}

function parseConcepts(raw: Record<string, unknown>): string[] | undefined {
  const source = Array.isArray(raw.concepts)
    ? raw.concepts
    : Array.isArray(raw.symbols)
      ? raw.symbols
      : undefined;
  if (!source) return undefined;

  const seen = new Set<string>();
  const concepts: string[] = [];
  for (const item of source) {
    if (typeof item !== 'string') continue;
    const label = item.trim();
    if (!label) continue;
    const key = label.normalize('NFC');
    if (seen.has(key)) continue;
    seen.add(key);
    concepts.push(label);
  }
  return concepts.length > 0 ? concepts : undefined;
}

function parseSourceHunks(
  raw: Record<string, unknown>,
  claimId: string,
): { anchors: DiffClaimAnchor[]; hunks: ClaimSourceHunk[] } {
  const rawHunks = Array.isArray(raw.source_hunks) ? raw.source_hunks : [];
  const parsed = rawHunks
    .map((entry): { anchor: DiffClaimAnchor; hunk: ClaimSourceHunk } | null => {
      if (!entry || typeof entry !== 'object') return null;
      const hunk = entry as Record<string, unknown>;
      const file = String(hunk.display_path ?? hunk.file ?? '');
      const start = toFiniteInt(hunk.start ?? hunk.line_start, 0);
      const end = toFiniteInt(hunk.end ?? hunk.line_end, start);
      if (!file || start <= 0) return null;
      const side = toSourceHunkSide(hunk.side);
      return {
        anchor: {
          claim_id: claimId,
          file,
          line_start: start,
          line_end: end,
          source_side: side,
        },
        hunk: {
          file: String(hunk.file ?? file),
          display_path: hunk.display_path != null ? String(hunk.display_path) : undefined,
          start,
          end,
          side,
        },
      };
    })
    .filter((entry): entry is { anchor: DiffClaimAnchor; hunk: ClaimSourceHunk } => entry !== null);

  if (parsed.length > 0) {
    return {
      anchors: parsed.map((entry) => entry.anchor),
      hunks: parsed.map((entry) => entry.hunk),
    };
  }

  const file = String(raw.file ?? '');
  const start = toFiniteInt(raw.line_start, 0);
  const end = toFiniteInt(raw.line_end, start);
  if (!file || start <= 0) return { anchors: [], hunks: [] };
  const side = toSourceHunkSide(raw.side);
  return {
    anchors: [{ claim_id: claimId, file, line_start: start, line_end: end, source_side: side }],
    hunks: [{ file, start, end, side }],
  };
}

function formatSourceGroupRef(group: ClaimSourceLineGroup): string {
  const range =
    group.line_end !== group.line_start && group.line_end > 0 ? `-${group.line_end}` : '';
  return `${group.file}:${group.line_start}${range}`;
}

function formatClaimRef(claim: ClaimInspectorClaim): string {
  if (!claim.file || claim.line_start <= 0) return '';
  const range =
    claim.line_end !== claim.line_start && claim.line_end > 0 ? `-${claim.line_end}` : '';
  return `${claim.file}:${claim.line_start}${range}`;
}

function formatSourceLine(line: DiffSourceLine): string {
  const marker = line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' ';
  return `${marker}${String(line.line_no).padStart(4, ' ')} ${line.text}`;
}

function parseClaims(content: string): DiffPageClaim[] {
  const result: DiffPageClaim[] = [];
  for (const line of content.split('\n')) {
    if (!line) continue;
    try {
      const raw = JSON.parse(line) as Record<string, unknown>;
      const claimId = String(raw.claim_id ?? '');
      if (!claimId) continue;
      const rawVerdict = raw.status ?? raw.verdict;
      const verdict: ClaimVerdict = CLAIM_VERDICTS.has(rawVerdict as ClaimVerdict)
        ? (rawVerdict as ClaimVerdict)
        : 'not_proven';
      const { anchors: rawAnchors, hunks } = parseSourceHunks(raw, claimId);
      // Stamp the claim verdict onto every anchor so DiffView can color the
      // gutter dot without a separate lookup table.
      const anchors: DiffClaimAnchor[] = rawAnchors.map((anchor) => ({
        ...anchor,
        verdict,
      }));
      const firstAnchor = anchors[0];
      const confidence = parseConfidence(raw.confidence);
      const concepts = parseConcepts(raw);
      result.push({
        claim_id: claimId,
        verdict,
        file: firstAnchor?.file ?? '',
        line_start: firstAnchor?.line_start ?? 0,
        line_end: firstAnchor?.line_end ?? 0,
        source_anchors: anchors,
        source_hunks: hunks,
        statement: String(raw.text ?? raw.statement ?? ''),
        evidence: raw.evidence != null ? String(raw.evidence) : undefined,
        confidence,
        concepts,
      });
    } catch {
      // Skip malformed JSONL lines
    }
  }
  return result;
}

export default function DiffViewerPage() {
  const { runId } = useParams<{ runId: string }>();
  const { search } = useLocation();
  const { t } = useTranslation();

  const [phase, setPhase] = useState<Phase>('loading');
  const [content, setContent] = useState('');
  const [stats, setStats] = useState<DiffStats | null>(null);
  const [claims, setClaims] = useState<DiffPageClaim[]>([]);
  const [claimsUnavailable, setClaimsUnavailable] = useState(false);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [headerFileIndex, setHeaderFileIndex] = useState(0);
  const [diffViewMode, setDiffViewMode] = useState<DiffViewMode>('unified');
  const abortRef = useRef<AbortController | null>(null);

  const fetchAll = useCallback(() => {
    if (!runId) {
      setClaims([]);
      setClaimsUnavailable(false);
      setPhase('empty');
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase('loading');
    setContent('');
    setStats(null);
    setClaims([]);
    setSelectedClaimId(null);
    setClaimsUnavailable(false);

    Promise.all([
      getRunArtifact(runId, 'diff', { signal: controller.signal }),
      getRunArtifact(runId, 'claims', { signal: controller.signal })
        .then((envelope): ClaimsLoadResult => ({
          content: envelope.content ?? '',
          unavailable: false,
        }))
        .catch((err: unknown): ClaimsLoadResult => {
          if (err instanceof DOMException && err.name === 'AbortError') throw err;
          if (!(err instanceof ApiError && err.status === 404)) throw err;
          if (import.meta.env.DEV) console.warn('DiffViewerPage claims artifact unavailable:', err);
          return {
            content: '',
            unavailable: true,
          };
        }),
    ])
      .then(([diffEnv, claimsEnv]) => {
        if (controller.signal.aborted) return;
        const text = diffEnv.content ?? '';
        setClaimsUnavailable(claimsEnv.unavailable);
        setClaims(parseClaims(claimsEnv.content));
        if (text.trim().length === 0) {
          setPhase('empty');
        } else {
          setContent(text);
          setPhase('ready');
        }
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) console.error('DiffViewerPage fetch error:', err);
        setPhase('error');
      });
  }, [runId]);

  useEffect(() => {
    fetchAll();
    return () => abortRef.current?.abort();
  }, [fetchAll]);

  const handleStats = useCallback((s: DiffStats) => {
    setStats(s);
  }, []);

  const handleCopyAnchor = useCallback((claimId: string) => {
    void copyToClipboard(`#claim-${claimId}`);
  }, []);

  /**
   * Scroll the diff view to the line corresponding to a claim's source hunk.
   * The claim card is only shown in the inspector once a claim is selected,
   * which already auto-expands the host file section in DiffView (see its
   * `useEffect` keyed on `selectedClaimId`). We defer the scroll to the next
   * animation frame so the freshly-expanded section is laid out first.
   *
   * Falls back to the file header when no exact line anchor is found (e.g.
   * the line is outside the visible diff range — common for large diffs).
   */
  const handleJumpToCode = useCallback((file: string, line: number, side?: SourceHunkSide) => {
    const tryScroll = (attempt = 0) => {
      const root = document.querySelector<HTMLElement>('.diff-view');
      if (!root) return false;
      const sideSelector =
        side === 'old' || side === 'new' ? `[data-line-side="${side}"]` : '';
      const exactTarget =
        root.querySelector<HTMLElement>(
          `[data-line-anchor="${CSS.escape(`${file}:${line}`)}"]${sideSelector}`,
        );
      const target =
        exactTarget ??
        root.querySelector<HTMLElement>(`[data-line-anchor="${CSS.escape(`${file}:${line}`)}"]`);
      if (!target && attempt < 8) {
        requestAnimationFrame(() => tryScroll(attempt + 1));
        return false;
      }
      const fallbackTarget =
        target ??
        root.querySelector<HTMLElement>(
          `[data-file-path="${CSS.escape(file)}"] .diff-file-header`,
        );
      if (!fallbackTarget) return false;
      fallbackTarget.scrollIntoView({
        behavior: prefersReducedMotion() ? 'auto' : 'smooth',
        block: 'center',
      });
      return true;
    };
    // Two RAFs: first lets React commit any pending state (e.g. expand the
    // host section), second lets the browser lay out the new DOM.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        tryScroll();
      });
    });
  }, []);

  const focusTarget = useMemo<FocusTarget | null>(() => {
    const raw = new URLSearchParams(search).get('focus')?.trim();
    if (!raw) return null;
    const sep = raw.lastIndexOf(':');
    if (sep <= 0) return null;
    const line = Number(raw.slice(sep + 1));
    if (!Number.isInteger(line) || line <= 0) return null;
    const file = raw.slice(0, sep);
    return file ? { file, line } : null;
  }, [search]);
  const diffFocusTarget = useMemo<DiffFocusTarget | null>(
    () => focusTarget ? { file: focusTarget.file, line: focusTarget.line } : null,
    [focusTarget],
  );

  useEffect(() => {
    if (phase !== 'ready' || !focusTarget) return;
    handleJumpToCode(focusTarget.file, focusTarget.line);
  }, [focusTarget, handleJumpToCode, phase]);

  const diffLines = useMemo(() => parseUnifiedDiff(content), [content]);
  const diffSections = useMemo(() => parseDiffFileSections(diffLines), [diffLines]);
  const headerFile = diffSections[headerFileIndex] ?? diffSections[0] ?? null;
  const headerFileName = headerFile?.filePath?.split('/').pop() ?? t('Diff.title');

  useEffect(() => {
    setHeaderFileIndex(0);
  }, [diffSections.length]);

  const claimsWithSource = useMemo(
    () =>
      claims.map((claim) => {
        const groups: ClaimSourceLineGroup[] = claim.source_anchors
          .map((anchor) => ({
            file: anchor.file,
            line_start: anchor.line_start,
            line_end: anchor.line_end,
            side: anchor.source_side,
            lines: getClaimSourceLines(diffLines, anchor),
          }))
          .filter((group) => group.lines.length > 0);
        return {
          ...claim,
          source_line_groups: groups,
          source_lines: groups.flatMap((group) => group.lines) as DiffSourceLine[],
        };
      }),
    [claims, diffLines],
  );
  const claimAnchors = useMemo(
    () => claims.flatMap((claim) => claim.source_anchors),
    [claims],
  );
  const selectedClaim = useMemo(
    () =>
      selectedClaimId
        ? claimsWithSource.find((claim) => claim.claim_id === selectedClaimId) ?? null
        : null,
    [claimsWithSource, selectedClaimId],
  );
  const selectedSourceGroup = selectedClaim?.source_line_groups?.[0];
  const selectedSourceLines = selectedSourceGroup?.lines ?? selectedClaim?.source_lines ?? [];
  const selectedSourceRef = selectedSourceGroup
    ? formatSourceGroupRef(selectedSourceGroup)
    : selectedClaim
      ? formatClaimRef(selectedClaim)
      : '';

  const handleActiveFileChange = useCallback((index: number | null) => {
    if (index != null) setHeaderFileIndex(index);
  }, []);

  const handleSelect = useCallback((claimId: string) => {
    setSelectedClaimId((prev) => (prev === claimId ? null : claimId));
  }, []);

  useEffect(() => {
    if (!selectedClaimId || phase !== 'ready') return;
    const sel = claimsWithSource.find((c) => c.claim_id === selectedClaimId);
    const group = sel?.source_line_groups?.[0];
    if (group?.file && group.line_start != null) {
      const file = group.file;
      const line = group.line_start;
      const side = group.side ?? undefined;
      requestAnimationFrame(() => handleJumpToCode(file, line, side));
    }
  }, [selectedClaimId]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Build mini-panel items from stats */
  const panelItems: MiniPanelItem[] = stats
    ? [
        { label: t('Diff.stats_files'), value: String(stats.files) },
        { label: t('Diff.stats_additions'), value: `+${stats.additions}` },
        { label: t('Diff.stats_deletions'), value: `-${stats.deletions}` },
      ]
    : [];

  return (
    <AppShell>
      <div className="page active diff-page" data-page="diff">
        <div className="page-head diff-page__header">
          <div>
            <div className="eyebrow">
              {t('Diff.header_eyebrow', { run: runId ?? 'run' })}
            </div>
            <h1>
              {t('Diff.title')} ·{' '}
              {headerFileName}
              {headerFile && (
                <span className="diff-page__header-stats">
                  · +{headerFile.stats.added} −{headerFile.stats.removed}
                </span>
              )}
            </h1>
            <p className="sub">{t('Diff.header_subtitle')}</p>
          </div>
          <div className="right">
            <button
              type="button"
              className={`chip diff-page__view-chip${diffViewMode === 'unified' ? ' on' : ''}`}
              aria-pressed={diffViewMode === 'unified'}
              onClick={() => setDiffViewMode('unified')}
            >
              {t('Diff.view_unified')}
            </button>
            <button
              type="button"
              className={`chip diff-page__view-chip${diffViewMode === 'split' ? ' on' : ''}`}
              aria-pressed={diffViewMode === 'split'}
              onClick={() => setDiffViewMode('split')}
            >
              {t('Diff.view_split')}
            </button>
            {runId && (
              <Link className="btn primary" to={`/run/${encodeURIComponent(runId)}/lesson`}>
                {t('Diff.open_lesson')} →
              </Link>
            )}
            <Suspense fallback={null}>
              <GraphifyCard compact />
            </Suspense>
          </div>
        </div>

        <div className="diff-page__split">
          <div className="diff-page__body">
            {phase === 'loading' && (
              <div className="diff-page__loading" role="status" aria-live="polite">
                <span className="loading-spinner" />{t('Serve.loading')}
              </div>
            )}

            {phase === 'error' && (
              <div className="diff-page__error" role="alert">
                {t('Error.fetch_failed', { resource: t('Diff.title') })}
                <button type="button" className="retry-btn" onClick={fetchAll}>
                  {t('Error.retry')}
                </button>
              </div>
            )}

            {phase === 'empty' && (
              <div className="diff-page__empty">{t('Diff.empty')}</div>
            )}

            {phase === 'ready' && (
              <>
                {claimsUnavailable && (
                  <div
                    className="diff-page__claims-warning"
                    role="status"
                    aria-live="polite"
                  >
                    <strong>{t('Diff.claims_unavailable_title')}</strong>
                    <span>{t('Diff.claims_unavailable_body')}</span>
                  </div>
                )}
                <DiffView
                  lines={diffLines}
                  claims={claimAnchors}
                  selectedClaimId={selectedClaimId}
                  onSelectClaim={handleSelect}
                  onStats={handleStats}
                  onActiveFileChange={handleActiveFileChange}
                  mode={diffViewMode}
                  focusTarget={diffFocusTarget}
                />
              </>
            )}

            {phase === 'ready' && selectedClaim && (
              <section
                className={`diff-page__selected-hunk diff-page__selected-hunk--${selectedClaim.verdict}`}
                aria-label={t('Diff.selected_source_hunk_title')}
              >
                <div className="diff-page__selected-hunk-header">
                  <h2>{t('Diff.selected_source_hunk_title')}</h2>
                  <div className="diff-page__selected-hunk-meta">
                    {selectedClaim.claim_id}
                    {selectedSourceRef ? ` · ${selectedSourceRef}` : ''}
                  </div>
                </div>
                <blockquote className="diff-page__selected-hunk-claim">
                  {selectedClaim.statement}
                </blockquote>
                {selectedSourceLines.length > 0 ? (
                  <pre className="diff-page__selected-hunk-code">
                    <code>{selectedSourceLines.map(formatSourceLine).join('\n')}</code>
                  </pre>
                ) : (
                  <p className="diff-page__selected-hunk-empty">
                    {t('Claim_inspector.source_unavailable')}
                  </p>
                )}
              </section>
            )}
          </div>

          <ClaimInspector
            claims={claimsWithSource}
            selectedClaimId={selectedClaimId}
            onSelect={handleSelect}
            onCopyAnchor={handleCopyAnchor}
            onJumpToCode={handleJumpToCode}
          />
        </div>

        {phase === 'ready' && <BottomMiniPanel items={panelItems} />}
      </div>
    </AppShell>
  );
}
