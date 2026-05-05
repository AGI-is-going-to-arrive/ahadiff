import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import EvidencePanel from '../components/EvidencePanel';
import ClaimBadge from '../components/ClaimBadge';
import FreshnessBadge from '../components/FreshnessBadge';
import ScaffoldingTabs from '../components/ScaffoldingTabs';
import { useTranslation } from '../i18n/useTranslation';
import { useRunsStore } from '../state/runs-store';
import { getRunLesson, getRunArtifact } from '../api/runs';
import { renderMarkdownProse, uniqueSlug } from '../utils/markdown';
import type { RunDetail } from '../api/types';
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

  const [level, setLevel] = useState<ScaffoldLevel>('full');
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [lessonContent, setLessonContent] = useState<string>('');
  const [claims, setClaims] = useState<Claim[]>([]);
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null);
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
    try {
      const [detail, lessonEnv, claimsEnv] = await Promise.all([
        useRunsStore.getState().loadDetail(runId, { signal: controller.signal }),
        getRunLesson(runId, 'full', { signal: controller.signal }),
        getRunArtifact(runId, 'claims', { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setRunDetail(detail);
      setLessonContent(lessonEnv.content);
      setClaims(parseClaims(claimsEnv.content));
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      // Raw flag; i18n string is computed at render time
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
      setLevel(newLevel);
      if (!runId) return;
      levelAbortRef.current?.abort();
      const controller = new AbortController();
      levelAbortRef.current = controller;
      const token = ++levelFetchRef.current;
      try {
        const env = await getRunLesson(runId, newLevel, { signal: controller.signal });
        if (token !== levelFetchRef.current) return;
        setLessonContent(env.content);
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (token !== levelFetchRef.current) return;
        setError('fetch_failed');
      }
    },
    [runId],
  );

  const handleClaimClick = useCallback(
    (claim: Claim) => {
      setSelectedClaim((prev) => (prev?.claim_id === claim.claim_id ? null : claim));
    },
    [],
  );

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

  return (
    <AppShell>
      <div className="lesson-page">
        <header className="lesson-page__header">
          <div className="lesson-page__header-left">
            <div className="lesson-page__eyebrow">
              {t('Lesson.eyebrow', { ref: runDetail?.source_ref?.slice(0, 7) ?? '—' })}
            </div>
            <h1 className="lesson-page__title">
              {runDetail
                ? t('Lesson.title_with_ref', {
                    title: t('Lesson.title'),
                    ref: runDetail.source_ref,
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
            <ScaffoldingTabs level={level} onChange={handleLevelChange} />
          </div>
        </header>

        {loading ? (
          <div className="lesson-page__loading" role="status" aria-live="polite">
            <span className="loading-spinner" /><span>{t('Serve.loading')}</span>
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
                        className="lesson__toc-link"
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
              <article className="lesson__prose">{renderedProse}</article>
            </div>

            <aside className="lesson__rail" aria-label={t('Lesson.rail.title')}>
              <div className="lesson__rail-title">{t('Lesson.rail.title')}</div>
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
                          onClick={() => handleClaimClick(claim)}
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

              <section className="lesson__rail-card" aria-labelledby="lesson-rail-evidence">
                <h2 id="lesson-rail-evidence" className="lesson__rail-card-title">
                  {t('Lesson.rail.selected_evidence')}
                </h2>
                {selectedClaim ? (
                  <EvidencePanel claim={selectedClaim} />
                ) : (
                  <p className="lesson__rail-empty">{t('Lesson.rail.selected_empty')}</p>
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
      </div>
    </AppShell>
  );
}
