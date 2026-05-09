import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useParams, Link } from 'react-router-dom';
import AppShell from '../components/AppShell';
import ScoreBreakdown from '../components/ScoreBreakdown';
import JudgeReport from '../components/JudgeReport';
import { getRun, getRunScore, getRunConcepts } from '../api/runs';
import { ApiError } from '../api/client';
import { scorePayloadSchema } from '../api/schemas';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import type { DegradedFlag, RunDetail, ScorePayload } from '../api/types';
import { safeVerdict } from '../utils/verdict';
import './RunDetailPage.css';

type DetailTab = 'overview' | 'score' | 'judge' | 'concepts' | 'artifacts';
const TABS: DetailTab[] = ['overview', 'score', 'judge', 'concepts', 'artifacts'];
const TAB_KEYS: Record<DetailTab, string> = {
  overview: 'RunDetail.tab_overview',
  score: 'RunDetail.tab_score',
  judge: 'RunDetail.tab_judge',
  concepts: 'RunDetail.tab_concepts',
  artifacts: 'RunDetail.tab_artifacts',
};
const TAB_IDS: Record<DetailTab, string> = {
  overview: 'rd-tab-overview',
  score: 'rd-tab-score',
  judge: 'rd-tab-judge',
  concepts: 'rd-tab-concepts',
  artifacts: 'rd-tab-artifacts',
};
const TAB_PANEL_IDS: Record<DetailTab, string> = {
  overview: 'rd-panel-overview',
  score: 'rd-panel-score',
  judge: 'rd-panel-judge',
  concepts: 'rd-panel-concepts',
  artifacts: 'rd-panel-artifacts',
};

const DEGRADED_FLAG_LABEL_KEYS: Record<DegradedFlag, MessageKey> = {
  diff_clipped: 'RunDetail.degraded_flag_diff_clipped',
  binary_only: 'RunDetail.degraded_flag_binary_only',
  file_count_exceeded: 'RunDetail.degraded_flag_file_count_exceeded',
  token_exceeded: 'RunDetail.degraded_flag_token_exceeded',
};

interface RunConceptRow {
  term_key: string;
  display_name: string;
  file_refs: string[];
  related_claims: string[];
}

function parseConceptsJsonl(text: string): RunConceptRow[] {
  const rows: RunConceptRow[] = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let raw: unknown;
    try {
      raw = JSON.parse(trimmed);
    } catch {
      continue;
    }
    if (!raw || typeof raw !== 'object') continue;
    const obj = raw as Record<string, unknown>;
    const termKey = typeof obj.term_key === 'string' ? obj.term_key : '';
    const displayName =
      typeof obj.display_name === 'string' && obj.display_name
        ? obj.display_name
        : typeof obj.concept === 'string'
          ? obj.concept
          : termKey;
    const fileRefs = Array.isArray(obj.file_refs)
      ? obj.file_refs.filter((f): f is string => typeof f === 'string')
      : [];
    const relatedClaims = Array.isArray(obj.related_claims)
      ? obj.related_claims.filter((c): c is string => typeof c === 'string')
      : [];
    if (!termKey && !displayName) continue;
    rows.push({
      term_key: termKey,
      display_name: displayName,
      file_refs: fileRefs,
      related_claims: relatedClaims,
    });
  }
  return rows;
}

function parseTabParam(): DetailTab {
  const query = window.location.hash.split('?')[1] ?? '';
  const tab = new URLSearchParams(query).get('tab');
  if (tab && TABS.includes(tab as DetailTab)) return tab as DetailTab;
  return 'overview';
}

function writeTabParam(tab: DetailTab) {
  const [hashPath, rawQuery = ''] = window.location.hash.split('?');
  const params = new URLSearchParams(rawQuery);
  params.set('tab', tab);
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}${window.location.search}${hashPath}?${params.toString()}`,
  );
}

function formatDate(iso: string, locale: string): string {
  try {
    return new Date(iso).toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function artifactLinks(artifacts: string[], runId: string, t: TranslateFn) {
  const routes: { name: string; path: string; label: string }[] = [
    { name: 'lesson', path: `/run/${runId}/lesson`, label: t('RunDetail.link_lesson') },
    { name: 'patch.diff', path: `/run/${runId}/diff`, label: t('RunDetail.link_diff') },
    { name: 'quiz', path: `/run/${runId}/quiz`, label: t('RunDetail.link_quiz') },
  ];
  return routes.filter((r) =>
    artifacts.some((a) => a.includes(r.name)),
  );
}

function activeDegradedFlags(flags: RunDetail['degraded_flags']): DegradedFlag[] {
  return (Object.entries(flags) as Array<[DegradedFlag, boolean | undefined]>)
    .filter(([, enabled]) => enabled)
    .map(([flag]) => flag);
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t, locale } = useTranslation();
  const [activeTab, setActiveTab] = useState<DetailTab>(parseTabParam);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [score, setScore] = useState<ScorePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [concepts, setConcepts] = useState<RunConceptRow[] | null>(null);
  const [conceptsLoading, setConceptsLoading] = useState(false);
  const [conceptsNotFound, setConceptsNotFound] = useState(false);
  const [conceptsError, setConceptsError] = useState(false);
  const conceptsAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setRun(null);
    setScore(null);
    setConcepts(null);
    setConceptsLoading(false);
    setConceptsNotFound(false);
    setConceptsError(false);

    Promise.allSettled([
      getRun(runId),
      getRunScore(runId).then((env) => {
        const parsed = scorePayloadSchema.safeParse(JSON.parse(env.content));
        return parsed.success ? parsed.data as ScorePayload : null;
      }),
    ]).then(([runResult, scoreResult]) => {
      if (cancelled) return;
      if (runResult.status === 'fulfilled') {
        setRun(runResult.value);
      } else {
        setError(runResult.reason instanceof Error ? runResult.reason.message : 'fetch_failed');
        setRun(null);
        setScore(null);
      }
      if (scoreResult.status === 'fulfilled') {
        setScore(scoreResult.value);
      } else {
        setScore(null);
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [runId]);

  useEffect(() => {
    const syncTab = () => setActiveTab(parseTabParam());
    window.addEventListener('hashchange', syncTab);
    return () => window.removeEventListener('hashchange', syncTab);
  }, []);

  const fetchConcepts = useCallback(
    () => {
      if (!runId) return;
      conceptsAbortRef.current?.abort();
      const ctrl = new AbortController();
      conceptsAbortRef.current = ctrl;
      const signal = ctrl.signal;
      setConceptsLoading(true);
      setConceptsError(false);
      setConceptsNotFound(false);
      getRunConcepts(runId, { signal })
        .then((text) => {
          if (signal.aborted) return;
          setConcepts(parseConceptsJsonl(text));
        })
        .catch((err: unknown) => {
          if (signal.aborted) return;
          if (err instanceof ApiError && err.status === 404) {
            setConceptsNotFound(true);
            setConcepts([]);
          } else {
            setConceptsError(true);
            setConcepts(null);
          }
        })
        .finally(() => {
          if (signal.aborted) return;
          setConceptsLoading(false);
        });
    },
    [runId],
  );

  useEffect(() => {
    if (activeTab !== 'concepts' || !runId) return;
    if (concepts !== null) return;
    fetchConcepts();
  }, [activeTab, runId, concepts, fetchConcepts]);

  useEffect(() => {
    if (activeTab !== 'concepts') conceptsAbortRef.current?.abort();
  }, [activeTab]);

  useEffect(() => () => conceptsAbortRef.current?.abort(), []);

  useEffect(() => {
    if (loading || !run || activeTab !== 'concepts') return;
    if (run.artifacts.includes('concepts.jsonl')) return;
    setActiveTab('overview');
    writeTabParam('overview');
  }, [activeTab, loading, run]);

  const activateTab = useCallback((tab: DetailTab) => {
    setActiveTab(tab);
    writeTabParam(tab);
  }, []);

  const handleTabKeyDown = useCallback(
    (tabs: DetailTab[]) => (e: KeyboardEvent<HTMLButtonElement>) => {
      if (tabs.length === 0) return;
      const idx = Math.max(0, tabs.indexOf(activeTab));
      let next = idx;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        next = (idx + 1) % tabs.length;
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        next = (idx - 1 + tabs.length) % tabs.length;
      } else if (e.key === 'Home') {
        next = 0;
      } else if (e.key === 'End') {
        next = tabs.length - 1;
      } else {
        return;
      }
      e.preventDefault();
      activateTab(tabs[next]);
      document.getElementById(TAB_IDS[tabs[next]])?.focus();
    },
    [activeTab, activateTab],
  );

  if (!runId) {
    return <AppShell><p>{t('Error.not_found')}</p></AppShell>;
  }

  if (loading) {
    return (
      <AppShell>
        <div role="status" aria-live="polite" className="run-detail__loading">
          <span className="loading-spinner" />
          {t('Serve.loading')}
        </div>
      </AppShell>
    );
  }

  if (error || !run) {
    return (
      <AppShell>
        <div role="alert" className="run-detail__error">
          {t('Error.fetch_failed', { resource: t('RunDetail.resource_run') })}
        </div>
      </AppShell>
    );
  }

  const hasJudge = run.artifacts.includes('judge.json');
  const hasScore = score != null;
  const hasConcepts = run.artifacts.includes('concepts.jsonl');
  const visibleTabs = TABS.filter((tab) => tab !== 'concepts' || hasConcepts);
  const links = artifactLinks(run.artifacts, runId, t);
  const degradedFlags = activeDegradedFlags(run.degraded_flags);

  return (
    <AppShell>
      <header className="run-detail__header">
        <h1 className="run-detail__title">
          {t('RunDetail.title')}
          <code className="run-detail__run-id">{runId.length > 16 ? `${runId.slice(0, 16)}…` : runId}</code>
        </h1>
      </header>

      <div className="run-detail__tabs" role="tablist" aria-label={t('RunDetail.title')}>
        {visibleTabs.map((tab) => {
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              id={TAB_IDS[tab]}
              role="tab"
              type="button"
              className={`run-detail__tab${isActive ? ' run-detail__tab--active' : ''}`}
              aria-selected={isActive}
              aria-controls={TAB_PANEL_IDS[tab]}
              tabIndex={isActive ? 0 : -1}
              onClick={() => activateTab(tab)}
              onKeyDown={handleTabKeyDown(visibleTabs)}
            >
              {t(TAB_KEYS[tab])}
            </button>
          );
        })}
      </div>

      <section
        id={TAB_PANEL_IDS.overview}
        role="tabpanel"
        aria-labelledby={TAB_IDS.overview}
        hidden={activeTab !== 'overview'}
      >
        {activeTab === 'overview' && (
          <dl className="run-detail__meta">
            <div className="run-detail__meta-row">
              <dt>{t('RunDetail.source_ref')}</dt>
              <dd><code>{run.source_ref}</code></dd>
            </div>
            {run.base_ref && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.base_ref')}</dt>
                <dd><code>{run.base_ref}</code></dd>
              </div>
            )}
            <div className="run-detail__meta-row">
              <dt>{t('RunDetail.verdict')}</dt>
              <dd>
                <span className={`verdict-badge verdict-badge--${safeVerdict(run.verdict)}`}>
                  {run.verdict}
                </span>
              </dd>
            </div>
            {hasScore && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.overall_score')}</dt>
                <dd>{score.overall.toFixed(1)}</dd>
              </div>
            )}
            <div className="run-detail__meta-row">
              <dt>{t('RunDetail.capability_level')}</dt>
              <dd>{run.capability_level}</dd>
            </div>
            <div className="run-detail__meta-row">
              <dt>{t('RunDetail.content_lang')}</dt>
              <dd>{run.content_lang}</dd>
            </div>
            <div className="run-detail__meta-row">
              <dt>{t('RunDetail.created_at')}</dt>
              <dd>{formatDate(run.created_at, locale)}</dd>
            </div>
            <div className="run-detail__meta-row">
              <dt>{t('RunDetail.source_kind')}</dt>
              <dd>{run.source_kind}</dd>
            </div>
            {run.prompt_version && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.prompt_version')}</dt>
                <dd><code>{run.prompt_version}</code></dd>
              </div>
            )}
            {run.eval_bundle_version && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.eval_bundle_version')}</dt>
                <dd><code>{run.eval_bundle_version}</code></dd>
              </div>
            )}
            {run.graphify_mode && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.graphify_mode')}</dt>
                <dd>{run.graphify_mode}</dd>
              </div>
            )}
            {run.graphify_status && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.graphify_status')}</dt>
                <dd>{run.graphify_status}</dd>
              </div>
            )}
            {degradedFlags.length > 0 && (
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.degraded_flags')}</dt>
                <dd>
                  <ul className="run-detail__degraded-list">
                    {degradedFlags.map((flag) => (
                      <li key={flag} title={flag}>
                        {t(DEGRADED_FLAG_LABEL_KEYS[flag])}
                      </li>
                    ))}
                  </ul>
                </dd>
              </div>
            )}
          </dl>
        )}
      </section>

      <section
        id={TAB_PANEL_IDS.score}
        role="tabpanel"
        aria-labelledby={TAB_IDS.score}
        hidden={activeTab !== 'score'}
      >
        {activeTab === 'score' && score && <ScoreBreakdown payload={score} />}
        {activeTab === 'score' && !score && (
          <p className="run-detail__empty">{t('RunDetail.score_unavailable')}</p>
        )}
      </section>

      <section
        id={TAB_PANEL_IDS.judge}
        role="tabpanel"
        aria-labelledby={TAB_IDS.judge}
        hidden={activeTab !== 'judge'}
      >
        {activeTab === 'judge' && hasJudge && <JudgeReport runId={runId} />}
        {activeTab === 'judge' && !hasJudge && (
          <p className="run-detail__empty">{t('RunDetail.judge_unavailable')}</p>
        )}
      </section>

      <section
        id={TAB_PANEL_IDS.concepts}
        role="tabpanel"
        aria-labelledby={TAB_IDS.concepts}
        hidden={activeTab !== 'concepts'}
      >
        {activeTab === 'concepts' && hasConcepts && conceptsLoading && (
          <div role="status" aria-live="polite" className="run-detail__loading">
            <span className="loading-spinner" />
            {t('RunDetail.concepts_loading')}
          </div>
        )}
        {activeTab === 'concepts' && hasConcepts && !conceptsLoading && conceptsError && (
          <div role="alert" className="run-detail__error">
            {t('RunDetail.concepts_load_failed')}
            <button
              type="button"
              className="retry-btn"
              onClick={() => fetchConcepts()}
            >
              {t('Error.retry')}
            </button>
          </div>
        )}
        {activeTab === 'concepts' &&
          hasConcepts &&
          !conceptsLoading &&
          !conceptsError &&
          (conceptsNotFound || (concepts !== null && concepts.length === 0)) && (
            <p className="run-detail__empty">{t('RunDetail.concepts_unavailable')}</p>
          )}
        {activeTab === 'concepts' &&
          hasConcepts &&
          !conceptsLoading &&
          !conceptsError &&
          !conceptsNotFound &&
          concepts !== null &&
          concepts.length > 0 && (
            <table className="run-detail__concepts-table">
              <thead>
                <tr>
                  <th scope="col">{t('RunDetail.concepts_col_name')}</th>
                  <th scope="col">{t('RunDetail.concepts_col_id')}</th>
                  <th scope="col">{t('RunDetail.concepts_col_files')}</th>
                  <th scope="col" className="run-detail__concepts-count">
                    {t('RunDetail.concepts_col_claims')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {concepts.map((row) => (
                  <tr key={row.term_key || row.display_name}>
                    <td>{row.display_name}</td>
                    <td>
                      <code>{row.term_key}</code>
                    </td>
                    <td>
                      {row.file_refs.length === 0 ? (
                        '—'
                      ) : (
                        <ul className="run-detail__concepts-files">
                          {row.file_refs.map((f) => (
                            <li key={f} title={f}>
                              <code>{f.split('/').pop() || f}</code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td className="run-detail__concepts-count">
                      {row.related_claims.length}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </section>

      <section
        id={TAB_PANEL_IDS.artifacts}
        role="tabpanel"
        aria-labelledby={TAB_IDS.artifacts}
        hidden={activeTab !== 'artifacts'}
      >
        {activeTab === 'artifacts' && (
          <div className="run-detail__artifacts">
            <h2 className="run-detail__artifacts-title">{t('RunDetail.tab_artifacts')}</h2>
            <nav className="run-detail__artifact-links" aria-label={t('RunDetail.tab_artifacts')}>
              {links.map((link) => (
                <Link key={link.path} to={link.path} className="run-detail__artifact-link">
                  {link.label}
                </Link>
              ))}
              <Link to={`/concepts?run=${runId}`} className="run-detail__artifact-link">
                {t('RunDetail.link_concepts')}
              </Link>
            </nav>
            <div className="run-detail__artifact-files">
              <h3 className="run-detail__artifact-files-title">{t('RunDetail.available_artifacts')}</h3>
              <ul className="run-detail__artifact-list">
                {run.artifacts.map((a) => (
                  <li key={a} className="run-detail__artifact-item">
                    <code>{a}</code>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </section>
    </AppShell>
  );
}
