import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import EvidencePanel from '../components/EvidencePanel';
import ClaimBadge from '../components/ClaimBadge';
import ScaffoldingTabs from '../components/ScaffoldingTabs';
import { useTranslation } from '../i18n/useTranslation';
import { useRunsStore } from '../state/runs-store';
import { getRunLesson, getRunArtifact } from '../api/runs';
import type { RunDetail } from '../api/types';
import type { Claim } from '../components/EvidencePanel';
import type { ScaffoldLevel } from '../components/ScaffoldingTabs';
import '../components/Lesson.css';

const CLAIM_VERDICTS: ReadonlySet<Claim['verdict']> = new Set([
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
      const hunks = Array.isArray(raw.source_hunks) ? raw.source_hunks : [];
      const firstHunk = hunks[0] as Record<string, unknown> | undefined;
      const file = String(firstHunk?.display_path ?? firstHunk?.file ?? raw.file ?? '');
      const lineStart = toFiniteInt(firstHunk?.start ?? raw.line_start, 0);
      const lineEnd = toFiniteInt(firstHunk?.end ?? raw.line_end, lineStart);
      result.push({
        claim_id: claimId,
        verdict,
        file,
        line_start: lineStart,
        line_end: lineEnd,
        statement: String(raw.text ?? raw.statement ?? ''),
        evidence: raw.evidence != null ? String(raw.evidence) : undefined,
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

  return (
    <AppShell>
      <div className="lesson-page">
        <header className="lesson-page__header">
          <h1 className="lesson-page__title">
            {runDetail
              ? t('Lesson.title_with_ref', {
                  title: t('Lesson.title'),
                  ref: runDetail.source_ref,
                })
              : t('Lesson.title')}
          </h1>
          <ScaffoldingTabs level={level} onChange={handleLevelChange} />
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
          <div className="lesson-page__body">
            {/* Main content: lesson markdown */}
            <pre className="lesson-markdown">{lessonContent}</pre>

            {/* Sidebar: evidence + claims */}
            <aside className="lesson-sidebar">
              <EvidencePanel claim={selectedClaim} />

              <section>
                <h2 className="claims-section__title">{t('Lesson.claims_title')}</h2>
                {claims.length === 0 ? (
                  <p className="evidence-panel__empty">{t('Serve.empty')}</p>
                ) : (
                  <ul className="claims-list">
                    {claims.map((claim) => (
                      <li key={claim.claim_id}>
                        <button
                          type="button"
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
                            <code>
                              {claim.file}:{claim.line_start}
                              {claim.line_end !== claim.line_start ? `-${claim.line_end}` : ''}
                            </code>
                          </div>
                        </button>
                      </li>
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
