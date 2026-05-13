import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import EvidencePanel from '../components/EvidencePanel';
import ClaimBadge from '../components/ClaimBadge';
import FreshnessBadge from '../components/FreshnessBadge';
import ScaffoldingTabs from '../components/ScaffoldingTabs';
import { useTranslation } from '../i18n/useTranslation';
import { useRunsStore } from '../state/runs-store';
import { getRunLesson, getRunArtifact } from '../api/runs';
import { getWeakConcepts } from '../api/review';
import { ApiError } from '../api/client';
import { helpfulness } from '../api/signals';
import { renderMarkdownProse, uniqueSlug } from '../utils/markdown';
import { createIdempotencyKey } from '../utils/idempotency';
import type { RunDetail, WeakConceptsResponse } from '../api/types';
import type { Claim, ClaimSourceHunk } from '../components/EvidencePanel';
import type { ScaffoldLevel } from '../components/ScaffoldingTabs';
import '../components/Lesson.css';

interface TocEntry {
  id: string;
  label: string;
  level: number;
}


function extractTocEntries(content: string): TocEntry[] {
  const entries: TocEntry[] = [];
  const seen = new Set<string>();
  let inCodeFence = false;
  for (const line of content.split('\n')) {
    if (line.trim().startsWith('```')) {
      inCodeFence = !inCodeFence;
      continue;
    }
    if (inCodeFence) continue;
    const match = /^(#{1,3})\s+(.+)$/.exec(line);
    if (!match) continue;
    const label = match[2].trim();
    entries.push({ id: uniqueSlug(label, seen), label, level: match[1].length });
  }
  const minLevel = entries.length > 0 ? Math.min(...entries.map(e => e.level)) : 1;
  if (minLevel > 1) {
    for (const e of entries) e.level -= minLevel - 1;
  }
  return entries;
}

const CLAIM_VERDICT_ORDER: readonly Claim['verdict'][] = [
  'verified',
  'weak',
  'not_proven',
  'contradicted',
  'rejected',
];

const CLAIM_VERDICTS: ReadonlySet<Claim['verdict']> = new Set(CLAIM_VERDICT_ORDER);

interface ClaimSummary {
  total: number;
  counts: Record<Claim['verdict'], number>;
}

function toFiniteInt(value: unknown, fallback: number): number {
  const n = Number(value);
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

function toSourceSide(value: unknown): ClaimSourceHunk['side'] {
  return value === 'old' || value === 'new' || value === 'either' ? value : 'either';
}

function parseSourceHunks(raw: Record<string, unknown>): ClaimSourceHunk[] {
  const rawHunks = Array.isArray(raw.source_hunks) ? raw.source_hunks : [];
  const hunks = rawHunks
    .map((entry): ClaimSourceHunk | null => {
      if (!entry || typeof entry !== 'object') return null;
      const hunk = entry as Record<string, unknown>;
      const file = String(hunk.file ?? hunk.display_path ?? '');
      const start = toFiniteInt(hunk.start ?? hunk.line_start, 0);
      const end = toFiniteInt(hunk.end ?? hunk.line_end, start);
      if (!file || start <= 0) return null;
      return {
        file,
        display_path: hunk.display_path != null ? String(hunk.display_path) : undefined,
        start,
        end,
        side: toSourceSide(hunk.side),
      };
    })
    .filter((hunk): hunk is ClaimSourceHunk => hunk !== null);

  if (hunks.length > 0) return hunks;
  const file = String(raw.file ?? '');
  const start = toFiniteInt(raw.line_start, 0);
  const end = toFiniteInt(raw.line_end, start);
  return file && start > 0 ? [{ file, start, end, side: toSourceSide(raw.side) }] : [];
}

function summarizeClaims(claims: Claim[]): ClaimSummary {
  const counts = Object.fromEntries(CLAIM_VERDICT_ORDER.map((verdict) => [verdict, 0])) as Record<
    Claim['verdict'],
    number
  >;
  for (const claim of claims) counts[claim.verdict] += 1;
  return { total: claims.length, counts };
}

function formatClaimLocation(claim: Claim): string {
  const line =
    claim.line_start > 0
      ? claim.line_end !== claim.line_start
        ? `${claim.line_start}-${claim.line_end}`
        : String(claim.line_start)
      : '';
  if (claim.file && line) return `${claim.file}:${line}`;
  if (claim.file) return claim.file;
  return line || claim.claim_id;
}

// Determine recommended scaffolding level from weak concepts.
// Backend pre-computes per-concept scaffolding_level using FSRS stability:
//   full     -- Learning/Relearning, or stability < 3 days
//   hint     -- Review state, 3d <= stability < 14d
//   compact  -- stability >= 14d AND 2+ recent successes
// Page-level recommendation = max-scaffolding across concepts (worst weakness wins).
export function recommendScaffoldLevel(weak: WeakConceptsResponse | null): ScaffoldLevel {
  if (!weak) return 'compact';
  const all = [...weak.concepts, ...weak.new_concepts];
  if (all.length === 0) return 'compact';
  if (all.some((c) => c.scaffolding_level === 'full')) return 'full';
  if (all.some((c) => c.scaffolding_level === 'hint')) return 'hint';
  return 'compact';
}

function parseClaims(content: string): Claim[] {
  const result: Claim[] = [];
  const lines = content.split('\n').filter(Boolean);
  for (const line of lines) {
    try {
      const raw = JSON.parse(line) as Record<string, unknown>;
      const claimId = String(raw.claim_id ?? '');
      if (!claimId) continue;
      const rawVerdict = raw.status ?? raw.verdict;
      const verdict: Claim['verdict'] = CLAIM_VERDICTS.has(rawVerdict as Claim['verdict'])
        ? (rawVerdict as Claim['verdict'])
        : 'not_proven';
      const sourceHunks = parseSourceHunks(raw);
      const firstHunk = sourceHunks[0];
      const file = firstHunk?.display_path ?? firstHunk?.file ?? '';
      const lineStart = firstHunk?.start ?? 0;
      const lineEnd = firstHunk?.end ?? lineStart;
      result.push({
        claim_id: claimId,
        verdict,
        file,
        line_start: lineStart,
        line_end: lineEnd,
        statement: String(raw.text ?? raw.statement ?? ''),
        evidence: raw.evidence != null ? String(raw.evidence) : undefined,
        source_hunks: sourceHunks,
      });
    } catch {
      // Skip malformed JSONL lines
    }
  }
  return result;
}

export default function LessonPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useTranslation();

  const [level, setLevel] = useState<ScaffoldLevel>('compact');
  // Tracks whether `level` is currently the auto-recommended value (i.e. the
  // user has not manually overridden via tab click). Used to render a small
  // hint badge near the tabs.
  const [autoSelected, setAutoSelected] = useState<boolean>(false);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [lessonContent, setLessonContent] = useState<string>('');
  const [claims, setClaims] = useState<Claim[]>([]);
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null);
  const [popoverPos, setPopoverPos] = useState<{ top: number; right: number } | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Monotonic token for level-change fetches; losers are ignored
  const levelFetchRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const fetchAll = useCallback(async () => {
    if (!runId) return;
    abortRef.current?.abort();
    levelAbortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setRunDetail(null);
    setLessonContent('');
    setClaims([]);
    setSelectedClaim(null);
    setPopoverPos(null);
    try {
      let recommended: ScaffoldLevel = 'compact';
      try {
        const weak = await getWeakConcepts({ signal: controller.signal });
        if (controller.signal.aborted) return;
        recommended = recommendScaffoldLevel(weak);
      } catch (weakErr) {
        if (weakErr instanceof DOMException && weakErr.name === 'AbortError') return;
        if (controller.signal.aborted) return;
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn('[LessonPage] weak concepts fetch failed, defaulting to compact:', weakErr);
        }
      }
      setLevel(recommended);
      setAutoSelected(true);

      let detail: RunDetail | null = null;
      try {
        detail = await useRunsStore.getState().loadDetail(runId, { signal: controller.signal });
      } catch (detailErr) {
        if (detailErr instanceof DOMException && detailErr.name === 'AbortError') return;
        if (controller.signal.aborted) return;
        if (detailErr instanceof ApiError && detailErr.status === 404) {
          setError('fetch_failed');
          return;
        }
        throw detailErr;
      }
      if (controller.signal.aborted) return;
      setRunDetail(detail);

      const [lessonEnv, claimsEnv] = await Promise.all([
        getRunLesson(runId, recommended, { signal: controller.signal }).catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 404) return null;
          throw err;
        }),
        getRunArtifact(runId, 'claims', { signal: controller.signal }).catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 404) return null;
          throw err;
        }),
      ]);
      if (controller.signal.aborted) return;

      if (lessonEnv) {
        setLessonContent(lessonEnv.content);
      } else {
        setLessonContent('');
        setError('lesson_skipped');
      }
      if (claimsEnv) {
        setClaims(parseClaims(claimsEnv.content));
      } else {
        setClaims([]);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      setError('fetch_failed');
      // eslint-disable-next-line no-console
      if (import.meta.env.DEV) console.error('[LessonPage] fetch error:', err);
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [runId]);

  // Re-fetch lesson when level changes. AbortController cancels the previous
  // in-flight request; monotonic token is kept as a secondary stale guard.
  const levelAbortRef = useRef<AbortController | null>(null);

  // Initial parallel fetch: detail + lesson + claims
  useEffect(() => {
    void fetchAll();
    return () => {
      abortRef.current?.abort();
      levelAbortRef.current?.abort();
    };
  }, [fetchAll]);
  const handleLevelChange = useCallback(
    async (newLevel: ScaffoldLevel) => {
      const previousLevel = level;
      setLevel(newLevel);
      // Manual override -- clear the auto-selected hint.
      setAutoSelected(false);
      if (!runId) return;
      void helpfulness({
        idempotency_key: createIdempotencyKey(),
        target_kind: 'section',
        target_id: `${runId}:scaffolding`,
        payload: { helpful: true, level: newLevel, previous_level: previousLevel },
      }).catch(() => {});
      levelAbortRef.current?.abort();
      const controller = new AbortController();
      levelAbortRef.current = controller;
      const token = ++levelFetchRef.current;
      try {
        const env = await getRunLesson(runId, newLevel, { signal: controller.signal });
        if (token !== levelFetchRef.current) return;
        setLessonContent(env.content);
        setError(null);
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (token !== levelFetchRef.current) return;
        if (err instanceof ApiError && err.status === 404) {
          setLessonContent('');
          setError('lesson_skipped');
          return;
        }
        setError('fetch_failed');
      }
    },
    [runId, level],
  );

  const handleClaimClick = useCallback(
    (claim: Claim, e: React.MouseEvent<HTMLButtonElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      setSelectedClaim((prev) => {
        if (prev?.claim_id === claim.claim_id) {
          setPopoverPos(null);
          return null;
        }
        const maxTop = window.innerHeight - 320;
        const top = Math.min(Math.max(72, rect.top), maxTop);
        const right = window.innerWidth - rect.left + 12;
        setPopoverPos({ top, right });
        return claim;
      });
    },
    [],
  );

  // Close popover on Escape or click outside
  useEffect(() => {
    if (!selectedClaim) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setSelectedClaim(null); setPopoverPos(null); }
    };
    const onClick = (e: MouseEvent) => {
      const popover = popoverRef.current;
      if (!popover) return;
      const target = e.target as Node;
      if (!popover.contains(target) && !(target as Element).closest?.('.claim-card')) {
        setSelectedClaim(null);
        setPopoverPos(null);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onClick);
    };
  }, [selectedClaim]);

  const tocEntries = useMemo(() => extractTocEntries(lessonContent), [lessonContent]);
  const claimSummary = useMemo(() => summarizeClaims(claims), [claims]);
  const learningNotes = useMemo(() => {
    const notes: string[] = [];
    if (runDetail?.weakest_dim) {
      notes.push(t('Lesson.rail.weakest_dimension', { dim: runDetail.weakest_dim }));
    }
    for (const note of runDetail?.graphify_notes ?? []) {
      const trimmed = note.trim();
      if (trimmed) notes.push(trimmed);
    }
    return notes;
  }, [runDetail, t]);

  const renderedProse = useMemo(() => renderMarkdownProse(lessonContent), [lessonContent]);
  const scaffoldingPanelId = 'lesson-scaffolding-panel';
  const scaffoldingTabIdBase = 'lesson-scaffolding-tab';

  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  useEffect(() => {
    if (tocEntries.length === 0) {
      setActiveHeadingId(null);
      return;
    }
    setActiveHeadingId((current) =>
      current && tocEntries.some((entry) => entry.id === current)
        ? current
        : tocEntries[0]?.id ?? null,
    );
    if (typeof IntersectionObserver === 'undefined') return;
    const ids = tocEntries.map((e) => e.id);
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveHeadingId(entry.target.id);
            break;
          }
        }
      },
      { rootMargin: '-72px 0px -60% 0px', threshold: 0 },
    );
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [tocEntries]);

  return (
    <AppShell>
      <div className="lesson-page" data-page="lesson">
        <header className="lesson-page__header">
          <div className="lesson-page__header-left">
            <div className="lesson-page__eyebrow">
              {t('Lesson.eyebrow', { ref: runDetail?.source_ref?.slice(0, 7) ?? '—' })}
            </div>
            <h1 className="lesson-page__title">
              {runDetail
                ? t('Lesson.title_with_ref', {
                    title: t('Lesson.title'),
                    ref: runDetail.source_ref.slice(0, 7),
                  })
                : t('Lesson.title')}
            </h1>
            {runDetail && (
              <div className="lesson-page__sub">
                {[
                  runDetail.content_lang,
                  runDetail.artifacts ? `${runDetail.artifacts.length} ${t('Lesson.rail.artifacts').toLowerCase()}` : null,
                ].filter(Boolean).join(' · ')}
              </div>
            )}
          </div>
          <div className="lesson-page__header-right">
            <ScaffoldingTabs
              level={level}
              onChange={handleLevelChange}
              idBase={scaffoldingTabIdBase}
              panelId={scaffoldingPanelId}
            />
            {autoSelected && (
              <p className="scaffolding-auto-hint" aria-live="polite">
                {t('Lesson.scaffolding_auto_hint')}
              </p>
            )}
          </div>
        </header>

        <section
          id={scaffoldingPanelId}
          className="lesson-scaffolding-panel"
          role="tabpanel"
          aria-labelledby={`${scaffoldingTabIdBase}-${level}`}
          tabIndex={0}
        >
          {loading ? (
            <div className="lesson-page__loading" role="status" aria-live="polite">
              <span className="loading-spinner" /><span>{t('Serve.loading')}</span>
            </div>
          ) : error === 'lesson_skipped' ? (
            <div className="lesson-page__skipped" role="status">
              <div className="lesson-page__skipped-icon" aria-hidden="true">
                <svg width="56" height="56" viewBox="0 0 56 56" fill="none"><circle cx="28" cy="28" r="27" stroke="var(--muted)" strokeWidth="2" opacity=".35"/><path d="M20 28h16M28 20v16" stroke="var(--muted)" strokeWidth="2" strokeLinecap="round" opacity=".3"/></svg>
              </div>
              <h2 className="lesson-page__skipped-title">{t('Lesson.skipped_title')}</h2>
              <p className="lesson-page__skipped-reason">
                {runDetail?.learnability?.reasons?.includes('empty_diff')
                  ? t('Lesson.skipped_reason_empty_diff')
                  : runDetail?.learnability?.skip_lesson_quiz
                    ? t('Lesson.skipped_reason_low_score', {
                        score: String(Math.round((runDetail.learnability.score ?? 0) * 100)),
                        threshold: String(Math.round((runDetail.learnability.threshold ?? 0) * 100)),
                      })
                    : t('Lesson.skipped_reason_generic')}
              </p>
              <p className="lesson-page__skipped-hint">{t('Lesson.skipped_hint')}</p>
              <code className="lesson-page__skipped-example">ahadiff learn HEAD~1..HEAD</code>
            </div>
          ) : error ? (
            <div className="lesson-page__error" role="alert">
              <span>{t('Error.fetch_failed', { resource: t('Nav.lesson') })}</span>
              <button type="button" className="retry-btn" onClick={() => void fetchAll()}>
                {t('Error.retry')}
              </button>
            </div>
          ) : (
            <div className="lesson__layout">
            <aside className="lesson__toc" aria-label={t('Lesson.toc.title')}>
              <div className="lesson__toc-title">{t('Lesson.toc.title')}</div>
              {tocEntries.length === 0 ? (
                <div className="lesson__toc-empty">{t('Lesson.toc.empty')}</div>
              ) : (
                <ol className="lesson__toc-list">
                  {tocEntries.map((e) => (
                    <li key={e.id} className={e.level > 1 ? `lesson__toc-item--l${e.level}` : undefined}>
                      <a
                        href={`#${e.id}`}
                        className={`lesson__toc-link${activeHeadingId === e.id ? ' lesson__toc-link--active' : ''}`}
                        aria-current={activeHeadingId === e.id ? 'location' : undefined}
                        onClick={(ev) => {
                          ev.preventDefault();
                          const el = document.getElementById(e.id);
                          if (!el) return;
                          const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                          el.focus({ preventScroll: true });
                          el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
                        }}
                      >
                        {e.label}
                      </a>
                    </li>
                  ))}
                </ol>
              )}
            </aside>

            <div className="lesson__center">
              <article className="lesson__prose">
                {renderedProse}
              </article>
            </div>

            <aside className="lesson__rail" aria-label={t('Lesson.rail.title')}>
              <section className="lesson__rail-card" aria-labelledby="lesson-rail-claims">
                <h2 id="lesson-rail-claims" className="lesson__rail-card-title">
                  {t('Lesson.rail.claims_summary')}
                </h2>
                <div className="lesson__claim-total">
                  <span className="lesson__claim-total-number">{claimSummary.total}</span>
                  <span className="lesson__claim-total-label">{t('Lesson.rail.total_claims')}</span>
                </div>
                <dl className="lesson__status-grid">
                  {CLAIM_VERDICT_ORDER.map((verdict) => (
                    <div key={verdict} className={`lesson__status-row lesson__status-row--${verdict}`}>
                      <dt>{t(`Claim.${verdict}`)}</dt>
                      <dd>{claimSummary.counts[verdict]}</dd>
                    </div>
                  ))}
                </dl>
              </section>

              <section className="lesson__rail-card" aria-labelledby="lesson-rail-claims-list">
                <h2 id="lesson-rail-claims-list" className="lesson__rail-card-title">
                  {t('Lesson.claims_title')}
                </h2>
                {claims.length === 0 ? (
                  <p className="lesson__rail-empty">{t('Serve.empty')}</p>
                ) : (
                  <ul className="claims-list">
                    {claims.map((claim) => (
                      <li key={claim.claim_id}>
                        <button
                          type="button"
                          id={`claim-${claim.claim_id}`}
                          className={`claim-card${
                            selectedClaim?.claim_id === claim.claim_id ? ' claim-card--selected' : ''
                          }`}
                          onClick={(e) => handleClaimClick(claim, e)}
                          aria-pressed={selectedClaim?.claim_id === claim.claim_id}
                        >
                          <div className="claim-card__row">
                            <span className="claim-card__id">{claim.claim_id}</span>
                            <ClaimBadge verdict={claim.verdict} />
                          </div>
                          <p className="claim-card__statement">{claim.statement}</p>
                          <div className="claim-card__location">
                            <code>{formatClaimLocation(claim)}</code>
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="lesson__rail-card" aria-labelledby="lesson-rail-sources">
                <h2 id="lesson-rail-sources" className="lesson__rail-card-title">
                  {t('Lesson.rail.sources_title')}
                </h2>
                <dl className="lesson__source-list">
                  <div className="lesson__source-row">
                    <dt>{t('Lesson.rail.source_ref')}</dt>
                    <dd>
                      <code>{runDetail?.source_ref ?? '—'}</code>
                    </dd>
                  </div>
                  <div className="lesson__source-row">
                    <dt>{t('Lesson.rail.base_ref')}</dt>
                    <dd>
                      <code>{runDetail?.base_ref ?? '—'}</code>
                    </dd>
                  </div>
                  <div className="lesson__source-row">
                    <dt>{t('Lesson.rail.language')}</dt>
                    <dd>{runDetail?.content_lang ?? '—'}</dd>
                  </div>
                  <div className="lesson__source-row">
                    <dt>{t('Lesson.rail.artifacts')}</dt>
                    <dd>{runDetail?.artifacts?.join(', ') || '—'}</dd>
                  </div>
                  {runDetail?.graphify_status && ['fresh', 'stale', 'unavailable', 'disabled'].includes(runDetail.graphify_status) && (
                    <div className="lesson__source-row">
                      <dt>{t('Graph.freshness')}</dt>
                      <dd><FreshnessBadge value={runDetail.graphify_status} /></dd>
                    </div>
                  )}
                </dl>
              </section>

              <section className="lesson__rail-card" aria-labelledby="lesson-rail-notes">
                <h2 id="lesson-rail-notes" className="lesson__rail-card-title">
                  {t('Lesson.rail.learning_notes')}
                </h2>
                {learningNotes.length === 0 ? (
                  <p className="lesson__rail-empty">{t('Lesson.rail.notes_empty')}</p>
                ) : (
                  <ul className="lesson__notes-list">
                    {learningNotes.map((note, index) => (
                      <li key={`${note}-${index}`}>{note}</li>
                    ))}
                  </ul>
                )}
              </section>
            </aside>
            </div>
          )}
        </section>
      </div>
      {selectedClaim && popoverPos && createPortal(
        <div
          ref={popoverRef}
          className="claim-popover"
          style={{ top: popoverPos.top, right: popoverPos.right }}
          role="dialog"
          aria-label={t('Lesson.rail.selected_evidence')}
        >
          <button
            type="button"
            className="claim-popover__close"
            aria-label={t('A11y.close')}
            onClick={() => { setSelectedClaim(null); setPopoverPos(null); }}
          >
            ×
          </button>
          <EvidencePanel claim={selectedClaim} />
        </div>,
        document.body,
      )}
    </AppShell>
  );
}
