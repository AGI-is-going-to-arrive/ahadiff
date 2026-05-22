import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useParams, Link } from 'react-router-dom';
import AppShell from '../components/AppShell';
import ScoreBreakdown from '../components/ScoreBreakdown';
import JudgeReport from '../components/JudgeReport';
import {
  getRun,
  getRunScore,
  getRunConcepts,
  getRunSpecAlignment,
  getRunGraphifySignoff,
  getRunJudgeFailure,
} from '../api/runs';
import { ApiError } from '../api/client';
import { scorePayloadSchema } from '../api/schemas';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import type {
  DegradedFlag,
  GraphifySignoffArtifact,
  JudgeFailure,
  RunDetail,
  ScorePayload,
  SpecAlignmentArtifact,
  SpecSemanticClassification,
  SpecRequirementClassification,
} from '../api/types';
import { formatHardGateName } from '../utils/hard-gates';
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

type SpecAlignmentLoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; artifact: SpecAlignmentArtifact }
  | { status: 'missing' }
  | { status: 'error' };

type GraphifySignoffLoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; artifact: GraphifySignoffArtifact }
  | { status: 'missing' }
  | { status: 'error' };

type JudgeFailureLoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; artifact: JudgeFailure }
  | { status: 'missing' }
  | { status: 'error' };

const SPEC_CLASS_KEYS: Record<SpecRequirementClassification, MessageKey> = {
  implemented: 'RunDetail.spec_class_implemented',
  partial: 'RunDetail.spec_class_partial',
  missing: 'RunDetail.spec_class_missing',
  unknown: 'RunDetail.spec_class_unknown',
};

const SPEC_SEMANTIC_CLASS_KEYS: Record<SpecSemanticClassification, MessageKey> = {
  implemented: 'RunDetail.spec_class_implemented',
  partial: 'RunDetail.spec_class_partial',
  missing: 'RunDetail.spec_class_missing',
  unknown: 'RunDetail.spec_class_unknown',
  violated: 'RunDetail.spec_class_violated',
};

const GRAPHIFY_SIGNOFF_KEYS: Record<GraphifySignoffArtifact['signoff'], MessageKey> = {
  passed: 'RunDetail.graphify_signoff_passed',
  degraded: 'RunDetail.graphify_signoff_degraded',
  unavailable: 'RunDetail.graphify_signoff_unavailable',
};

const GRAPHIFY_FRESHNESS_KEYS: Record<string, MessageKey> = {
  fresh: 'RunDetail.graphify_freshness_fresh',
  stale: 'RunDetail.graphify_freshness_stale',
  unavailable: 'RunDetail.graphify_freshness_unavailable',
  disabled: 'RunDetail.graphify_freshness_disabled',
};

const GRAPHIFY_DEGRADATION_KEYS: Record<string, MessageKey> = {
  graphify_disabled: 'RunDetail.graphify_reason_graphify_disabled',
  source_missing: 'RunDetail.graphify_reason_source_missing',
  imported_artifact_missing: 'RunDetail.graphify_reason_imported_artifact_missing',
  graph_digest_missing: 'RunDetail.graphify_reason_graph_digest_missing',
  graph_digest_invalid: 'RunDetail.graphify_reason_graph_digest_invalid',
  node_count_invalid: 'RunDetail.graphify_reason_node_count_invalid',
  edge_count_invalid: 'RunDetail.graphify_reason_edge_count_invalid',
  freshness_stale: 'RunDetail.graphify_reason_freshness_stale',
  freshness_unavailable: 'RunDetail.graphify_reason_freshness_unavailable',
  freshness_disabled: 'RunDetail.graphify_reason_freshness_disabled',
};

function formatCodeLabel(value: string): string {
  return value.replace(/_/g, ' ');
}

function graphifyFreshnessLabel(t: TranslateFn, value: string | null | undefined): string {
  if (!value) return '-';
  const key = GRAPHIFY_FRESHNESS_KEYS[value];
  return key ? t(key) : formatCodeLabel(value);
}

function graphifyDegradationLabel(t: TranslateFn, value: string): string {
  const key = GRAPHIFY_DEGRADATION_KEYS[value];
  return key ? t(key) : formatCodeLabel(value);
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
  const [specAlignmentState, setSpecAlignmentState] = useState<SpecAlignmentLoadState>({
    status: 'idle',
  });
  const [graphifySignoffState, setGraphifySignoffState] =
    useState<GraphifySignoffLoadState>({ status: 'idle' });
  const [judgeFailureState, setJudgeFailureState] =
    useState<JudgeFailureLoadState>({ status: 'idle' });
  const conceptsAbortRef = useRef<AbortController | null>(null);
  const specAbortRef = useRef<AbortController | null>(null);
  const graphifyAbortRef = useRef<AbortController | null>(null);
  const judgeFailureAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    judgeFailureAbortRef.current?.abort();
    setLoading(true);
    setError(null);
    setRun(null);
    setScore(null);
    setConcepts(null);
    setConceptsLoading(false);
    setConceptsNotFound(false);
    setConceptsError(false);
    setSpecAlignmentState({ status: 'idle' });
    setGraphifySignoffState({ status: 'idle' });
    setJudgeFailureState({ status: 'idle' });

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
    if (activeTab !== 'score' || !runId || !run?.artifacts.includes('spec_alignment.json')) {
      return;
    }
    if (specAlignmentState.status !== 'idle') return;
    specAbortRef.current?.abort();
    const ctrl = new AbortController();
    specAbortRef.current = ctrl;
    setSpecAlignmentState({ status: 'loading' });
    getRunSpecAlignment(runId, { signal: ctrl.signal })
      .then((artifact) => {
        if (ctrl.signal.aborted) return;
        setSpecAlignmentState({ status: 'loaded', artifact });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setSpecAlignmentState({ status: 'missing' });
        } else {
          setSpecAlignmentState({ status: 'error' });
        }
      });
  }, [activeTab, runId, run, specAlignmentState.status]);

  useEffect(() => {
    if (!runId || !run?.artifacts.includes('graphify_signoff.json')) return;
    if (graphifySignoffState.status !== 'idle') return;
    graphifyAbortRef.current?.abort();
    const ctrl = new AbortController();
    graphifyAbortRef.current = ctrl;
    setGraphifySignoffState({ status: 'loading' });
    getRunGraphifySignoff(runId, { signal: ctrl.signal })
      .then((artifact) => {
        if (ctrl.signal.aborted) return;
        setGraphifySignoffState({ status: 'loaded', artifact });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setGraphifySignoffState({ status: 'missing' });
        } else {
          setGraphifySignoffState({ status: 'error' });
        }
      });
  }, [runId, run, graphifySignoffState.status]);

  useEffect(() => {
    if (activeTab !== 'concepts') conceptsAbortRef.current?.abort();
  }, [activeTab]);

  useEffect(() => {
    if (activeTab !== 'score') specAbortRef.current?.abort();
  }, [activeTab]);

  useEffect(() => {
    if (
      activeTab !== 'judge' ||
      !runId ||
      !run ||
      run.artifacts.includes('judge.json') ||
      !run.artifacts.includes('judge_failure.json')
    ) {
      return;
    }
    if (judgeFailureState.status !== 'idle') return;
    judgeFailureAbortRef.current?.abort();
    const ctrl = new AbortController();
    judgeFailureAbortRef.current = ctrl;
    setJudgeFailureState({ status: 'loading' });
    getRunJudgeFailure(runId, { signal: ctrl.signal })
      .then((artifact) => {
        if (ctrl.signal.aborted) return;
        setJudgeFailureState({ status: 'loaded', artifact });
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.status === 404) {
          setJudgeFailureState({ status: 'missing' });
        } else {
          setJudgeFailureState({ status: 'error' });
        }
      });
  }, [activeTab, runId, run, judgeFailureState.status]);

  useEffect(() => {
    if (activeTab !== 'judge') {
      judgeFailureAbortRef.current?.abort();
      setJudgeFailureState({ status: 'idle' });
    }
  }, [activeTab]);

  useEffect(() => () => {
    conceptsAbortRef.current?.abort();
    specAbortRef.current?.abort();
    graphifyAbortRef.current?.abort();
    judgeFailureAbortRef.current?.abort();
  }, []);

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
    return (
      <AppShell>
        <div className="page active run-detail-page" data-page="run-detail">
          <p>{t('Error.not_found')}</p>
        </div>
      </AppShell>
    );
  }

  if (loading) {
    return (
      <AppShell>
        <div className="page active run-detail-page" data-page="run-detail">
          <div role="status" aria-live="polite" className="run-detail__loading">
            <span className="loading-spinner" />
            {t('Serve.loading')}
          </div>
        </div>
      </AppShell>
    );
  }

  if (error || !run) {
    return (
      <AppShell>
        <div className="page active run-detail-page" data-page="run-detail">
          <div role="alert" className="run-detail__error">
            {t('Error.fetch_failed', { resource: t('RunDetail.resource_run') })}
          </div>
        </div>
      </AppShell>
    );
  }

  const hasJudge = run.artifacts.includes('judge.json');
  const hasJudgeFailure = run.artifacts.includes('judge_failure.json');
  const hasScore = score != null;
  const hasConcepts = run.artifacts.includes('concepts.jsonl');
  const hasSpecAlignment = run.artifacts.includes('spec_alignment.json');
  const hasGraphifySignoff = run.artifacts.includes('graphify_signoff.json');
  const visibleTabs = TABS.filter((tab) => tab !== 'concepts' || hasConcepts);
  const links = artifactLinks(run.artifacts, runId, t);
  const degradedFlags = activeDegradedFlags(run.degraded_flags);

  return (
    <AppShell>
      <div className="page active run-detail-page" data-page="run-detail">
        <header className="page-head run-detail__header">
          <div>
            <h1 className="run-detail__title">
              {t('RunDetail.title')}
              <code className="run-detail__run-id">{runId.length > 16 ? `${runId.slice(0, 16)}…` : runId}</code>
            </h1>
          </div>
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
          <>
            <div className="run-detail__summary-card">
              <div className="run-detail__summary-verdict">
                <span className={`verdict-badge verdict-badge--${safeVerdict(run.verdict)} run-detail__summary-badge`}>
                  {run.verdict}
                </span>
                {hasScore && (
                  <span className="run-detail__summary-score">{score.overall.toFixed(1)}</span>
                )}
              </div>
              <div className="run-detail__summary-body">
                <p className="run-detail__summary-text">
                  {run.verdict === 'PASS' && t('RunDetail.overview_summary_pass', { score: hasScore ? score.overall.toFixed(1) : '—' })}
                  {run.verdict === 'FAIL' && t('RunDetail.overview_summary_fail', {
                    reason: score?.hard_gates
                      ? (() => {
                          const failed = Object.entries(score.hard_gates).find(([, g]) => !g.passed);
                          return failed
                            ? t('RunDetail.overview_summary_gate_reason', { gate: formatHardGateName(t, failed[0]) })
                            : t('RunDetail.overview_summary_score_reason', { score: hasScore ? score.overall.toFixed(1) : '—' });
                        })()
                      : t('RunDetail.overview_summary_score_reason', { score: hasScore ? score.overall.toFixed(1) : '—' }),
                  })}
                  {run.verdict === 'CAUTION' && t('RunDetail.overview_summary_caution', { score: hasScore ? score.overall.toFixed(1) : '—' })}
                </p>
                <div className="run-detail__summary-meta">
                  <span>{formatDate(run.created_at, locale)}</span>
                  <span><code>{run.source_ref}</code></span>
                  <span>{run.capability_level}</span>
                </div>
              </div>
              {links.length > 0 && (
                <nav className="run-detail__summary-links" aria-label={t('RunDetail.overview_quick_links')}>
                  {links.map((link) => (
                    <Link key={link.path} to={link.path} className="run-detail__summary-link">
                      {link.label}
                    </Link>
                  ))}
                </nav>
              )}
            </div>

            {degradedFlags.length > 0 && (
              <div className="run-detail__degraded-banner">
                {degradedFlags.map((flag) => (
                  <span key={flag} className="run-detail__degraded-tag" title={flag}>
                    {t(DEGRADED_FLAG_LABEL_KEYS[flag])}
                  </span>
                ))}
              </div>
            )}

            <dl className="run-detail__meta">
              {run.base_ref && (
                <div className="run-detail__meta-row">
                  <dt>{t('RunDetail.base_ref')}</dt>
                  <dd><code>{run.base_ref}</code></dd>
                </div>
              )}
              <div className="run-detail__meta-row">
                <dt>{t('RunDetail.content_lang')}</dt>
                <dd>{run.content_lang}</dd>
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
            </dl>
          </>
        )}
        {activeTab === 'overview' && hasGraphifySignoff && (
          <GraphifySignoffPanel
            t={t}
            state={graphifySignoffState}
            onRetry={() => setGraphifySignoffState({ status: 'idle' })}
          />
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
        {activeTab === 'score' && (score || hasSpecAlignment) && (
          <SpecAlignmentPanel
            t={t}
            hasArtifact={hasSpecAlignment}
            state={specAlignmentState}
            onRetry={() => setSpecAlignmentState({ status: 'idle' })}
          />
        )}
      </section>

      <section
        id={TAB_PANEL_IDS.judge}
        role="tabpanel"
        aria-labelledby={TAB_IDS.judge}
        hidden={activeTab !== 'judge'}
      >
        {activeTab === 'judge' && hasJudge && <JudgeReport runId={runId} />}
        {activeTab === 'judge' && !hasJudge && hasJudgeFailure && (
          <JudgeFailurePanel
            t={t}
            state={judgeFailureState}
            onRetry={() => setJudgeFailureState({ status: 'idle' })}
          />
        )}
        {activeTab === 'judge' && !hasJudge && !hasJudgeFailure && (
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
          <ArtifactsPanel run={run} runId={runId} links={links} t={t} />
        )}
      </section>
      </div>
    </AppShell>
  );
}

function GraphifySignoffPanel({
  t,
  state,
  onRetry,
}: {
  t: TranslateFn;
  state: GraphifySignoffLoadState;
  onRetry: () => void;
}) {
  if (state.status === 'idle' || state.status === 'loading') {
    return (
      <section className="run-detail__graphify-signoff" aria-labelledby="run-detail-graphify-title">
        <h2 id="run-detail-graphify-title" className="run-detail__spec-title">
          {t('RunDetail.graphify_signoff_title')}
        </h2>
        <div role="status" aria-live="polite" className="run-detail__loading">
          <span className="loading-spinner" />
          {t('RunDetail.graphify_signoff_loading')}
        </div>
      </section>
    );
  }
  if (state.status === 'missing') {
    return (
      <section className="run-detail__graphify-signoff" aria-labelledby="run-detail-graphify-title">
        <h2 id="run-detail-graphify-title" className="run-detail__spec-title">
          {t('RunDetail.graphify_signoff_title')}
        </h2>
        <p className="run-detail__empty">{t('RunDetail.graphify_signoff_missing')}</p>
      </section>
    );
  }
  if (state.status === 'error') {
    return (
      <section className="run-detail__graphify-signoff" aria-labelledby="run-detail-graphify-title">
        <h2 id="run-detail-graphify-title" className="run-detail__spec-title">
          {t('RunDetail.graphify_signoff_title')}
        </h2>
        <div role="alert" className="run-detail__error">
          {t('RunDetail.graphify_signoff_load_failed')}
          <button type="button" className="retry-btn" onClick={onRetry}>
            {t('Error.retry')}
          </button>
        </div>
      </section>
    );
  }
  const artifact = state.artifact;
  return (
    <section className="run-detail__graphify-signoff" aria-labelledby="run-detail-graphify-title">
      <h2 id="run-detail-graphify-title" className="run-detail__spec-title">
        {t('RunDetail.graphify_signoff_title')}
      </h2>
      <dl className="run-detail__spec-summary">
        <div>
          <dt>{t('RunDetail.graphify_signoff_status')}</dt>
          <dd>{t(GRAPHIFY_SIGNOFF_KEYS[artifact.signoff])}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.graphify_freshness')}</dt>
          <dd>{graphifyFreshnessLabel(t, artifact.freshness)}</dd>
        </div>
        <div>
          <dt>{t('Graph.node_count', { count: artifact.node_count })}</dt>
          <dd>{artifact.node_count}</dd>
        </div>
        <div>
          <dt>{t('Graph.edge_count', { count: artifact.edge_count })}</dt>
          <dd>{artifact.edge_count}</dd>
        </div>
      </dl>
      {artifact.graph_sha256 && (
        <p className="run-detail__spec-source">
          {t('RunDetail.graphify_digest')} <code>{artifact.graph_sha256.slice(0, 12)}…</code>
        </p>
      )}
      {artifact.degradation_reasons.length > 0 && (
        <p className="run-detail__spec-reason">
          {t('RunDetail.graphify_degraded_reasons')}:{' '}
          {artifact.degradation_reasons
            .map((reason) => graphifyDegradationLabel(t, reason))
            .join(', ')}
        </p>
      )}
    </section>
  );
}

function JudgeFailurePanel({
  t,
  state,
  onRetry,
}: {
  t: TranslateFn;
  state: JudgeFailureLoadState;
  onRetry: () => void;
}) {
  if (state.status === 'idle' || state.status === 'loading') {
    return (
      <section
        className="run-detail__judge-failure"
        aria-labelledby="run-detail-judge-failure-title"
      >
        <h2
          id="run-detail-judge-failure-title"
          className="run-detail__judge-failure-title"
        >
          {t('RunDetail.judge_failure_title')}
        </h2>
        <div role="status" aria-live="polite" className="run-detail__loading">
          <span className="loading-spinner" />
          {t('RunDetail.judge_loading')}
        </div>
      </section>
    );
  }
  if (state.status === 'missing') {
    return (
      <p className="run-detail__empty">{t('RunDetail.judge_unavailable')}</p>
    );
  }
  if (state.status === 'error') {
    return (
      <section
        className="run-detail__judge-failure"
        aria-labelledby="run-detail-judge-failure-title"
      >
        <h2
          id="run-detail-judge-failure-title"
          className="run-detail__judge-failure-title"
        >
          {t('RunDetail.judge_failure_title')}
        </h2>
        <div role="alert" className="run-detail__error">
          {t('RunDetail.judge_load_failed')}
          <button type="button" className="retry-btn" onClick={onRetry}>
            {t('Error.retry')}
          </button>
        </div>
      </section>
    );
  }
  const artifact = state.artifact;
  return (
    <section
      className="run-detail__judge-failure"
      aria-labelledby="run-detail-judge-failure-title"
    >
      <div className="run-detail__judge-failure-head">
        <span
          className="run-detail__judge-failure-icon"
          aria-hidden="true"
        >
          !
        </span>
        <h2
          id="run-detail-judge-failure-title"
          className="run-detail__judge-failure-title"
        >
          {t('RunDetail.judge_failure_title')}
        </h2>
      </div>
      <ul className="run-detail__judge-failure-meta">
        {artifact.provider_class && (
          <li className="run-detail__judge-failure-row">
            {t('RunDetail.judge_failure_provider', {
              provider: artifact.provider_class,
            })}
          </li>
        )}
        {artifact.model_name && (
          <li className="run-detail__judge-failure-row">
            {t('RunDetail.judge_failure_model', { model: artifact.model_name })}
          </li>
        )}
        {artifact.error_type && (
          <li className="run-detail__judge-failure-row">
            {t('RunDetail.judge_failure_error', { error: artifact.error_type })}
          </li>
        )}
      </ul>
      {artifact.message && (
        <p className="run-detail__judge-failure-message">{artifact.message}</p>
      )}
      <p className="run-detail__judge-failure-note">
        {t('RunDetail.judge_failure_note')}
      </p>
    </section>
  );
}

function SpecAlignmentPanel({
  t,
  hasArtifact,
  state,
  onRetry,
}: {
  t: TranslateFn;
  hasArtifact: boolean;
  state: SpecAlignmentLoadState;
  onRetry: () => void;
}) {
  if (!hasArtifact) {
    return (
      <section className="run-detail__spec-panel" aria-labelledby="run-detail-spec-title">
        <h2 id="run-detail-spec-title" className="run-detail__spec-title">
          {t('RunDetail.spec_alignment_title')}
        </h2>
        <p className="run-detail__empty">{t('RunDetail.spec_alignment_missing')}</p>
      </section>
    );
  }
  if (state.status === 'idle' || state.status === 'loading') {
    return (
      <section className="run-detail__spec-panel" aria-labelledby="run-detail-spec-title">
        <h2 id="run-detail-spec-title" className="run-detail__spec-title">
          {t('RunDetail.spec_alignment_title')}
        </h2>
        <div role="status" aria-live="polite" className="run-detail__loading">
          <span className="loading-spinner" />
          {t('RunDetail.spec_alignment_loading')}
        </div>
      </section>
    );
  }
  if (state.status === 'missing') {
    return (
      <section className="run-detail__spec-panel" aria-labelledby="run-detail-spec-title">
        <h2 id="run-detail-spec-title" className="run-detail__spec-title">
          {t('RunDetail.spec_alignment_title')}
        </h2>
        <p className="run-detail__empty">{t('RunDetail.spec_alignment_missing')}</p>
      </section>
    );
  }
  if (state.status === 'error') {
    return (
      <section className="run-detail__spec-panel" aria-labelledby="run-detail-spec-title">
        <h2 id="run-detail-spec-title" className="run-detail__spec-title">
          {t('RunDetail.spec_alignment_title')}
        </h2>
        <div role="alert" className="run-detail__error">
          {t('RunDetail.spec_alignment_load_failed')}
          <button type="button" className="retry-btn" onClick={onRetry}>
            {t('Error.retry')}
          </button>
        </div>
      </section>
    );
  }

  const artifact = state.artifact;
  return (
    <section className="run-detail__spec-panel" aria-labelledby="run-detail-spec-title">
      <div className="run-detail__spec-head">
        <div>
          <h2 id="run-detail-spec-title" className="run-detail__spec-title">
            {t('RunDetail.spec_alignment_title')}
          </h2>
          <p className="run-detail__spec-source">
            {artifact.spec_source?.path ?? t('RunDetail.spec_alignment_source_unknown')}
          </p>
        </div>
        <div className="run-detail__spec-score">
          {artifact.score.toFixed(1)}/{artifact.max_score.toFixed(0)}
        </div>
      </div>
      <dl className="run-detail__spec-summary">
        <div>
          <dt>{t('RunDetail.spec_class_implemented')}</dt>
          <dd>{artifact.summary.implemented}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.spec_class_partial')}</dt>
          <dd>{artifact.summary.partial}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.spec_class_missing')}</dt>
          <dd>{artifact.summary.missing}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.spec_class_unknown')}</dt>
          <dd>{artifact.summary.unknown}</dd>
        </div>
      </dl>
      {artifact.semantic_review && (
        <SpecSemanticReviewPanel t={t} artifact={artifact} />
      )}
      {artifact.requirements.length === 0 ? (
        <p className="run-detail__empty">{t('RunDetail.spec_alignment_no_requirements')}</p>
      ) : (
        <ul className="run-detail__spec-requirements">
          {artifact.requirements.map((requirement) => (
            <li
              key={requirement.id}
              className={`run-detail__spec-req run-detail__spec-req--${requirement.classification}`}
            >
              <div className="run-detail__spec-req-head">
                <code>{requirement.id}</code>
                <span>{t(SPEC_CLASS_KEYS[requirement.classification])}</span>
              </div>
              <p>{requirement.text}</p>
              <p className="run-detail__spec-reason">{requirement.reason}</p>
              {requirement.evidence_refs.length > 0 && (
                <ul className="run-detail__spec-evidence">
                  {requirement.evidence_refs.map((ref, index) => (
                    <li key={`${requirement.id}-${index}`}>
                      <code>
                        {ref.file ?? ref.claim_id ?? ref.type}
                        {typeof ref.start === 'number' ? `:${ref.start}` : ''}
                      </code>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {artifact.known_limitations.length > 0 && (
        <p className="run-detail__spec-limitations">
          {t('RunDetail.spec_alignment_limitations', {
            count: String(artifact.known_limitations.length),
          })}
        </p>
      )}
    </section>
  );
}

function SpecSemanticReviewPanel({
  t,
  artifact,
}: {
  t: TranslateFn;
  artifact: SpecAlignmentArtifact;
}) {
  const review = artifact.semantic_review;
  if (!review) return null;
  const adjustment = artifact.semantic_adjustment;
  return (
    <section className="run-detail__semantic-panel" aria-labelledby="run-detail-semantic-title">
      <div className="run-detail__semantic-head">
        <div>
          <h3 id="run-detail-semantic-title">{t('RunDetail.spec_semantic_title')}</h3>
          <p className="run-detail__spec-source">
            {review.provider}/{review.model}
          </p>
        </div>
        <span className={`run-detail__semantic-status ${review.degraded ? 'is-degraded' : 'is-ok'}`}>
          {review.degraded
            ? t('RunDetail.spec_semantic_degraded')
            : t('RunDetail.spec_semantic_available')}
        </span>
      </div>
      {review.degraded && review.degradation_reason && (
        <p className="run-detail__spec-reason">{review.degradation_reason}</p>
      )}
      <dl className="run-detail__spec-summary run-detail__semantic-summary">
        <div>
          <dt>{t('RunDetail.spec_class_implemented')}</dt>
          <dd>{review.aggregate.implemented}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.spec_class_partial')}</dt>
          <dd>{review.aggregate.partial}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.spec_class_missing')}</dt>
          <dd>{review.aggregate.missing}</dd>
        </div>
        <div>
          <dt>{t('RunDetail.spec_class_violated')}</dt>
          <dd>{review.aggregate.violated}</dd>
        </div>
      </dl>
      {adjustment && (
        <p className="run-detail__spec-limitations">
          {t('RunDetail.spec_semantic_adjustment', {
            score: adjustment.score.toFixed(1),
            delta: adjustment.delta.toFixed(1),
          })}
        </p>
      )}
      {review.requirements.length === 0 ? (
        <p className="run-detail__empty">{t('RunDetail.spec_semantic_empty')}</p>
      ) : (
        <ul className="run-detail__spec-requirements run-detail__semantic-requirements">
          {review.requirements.map((requirement) => (
            <li
              key={`semantic-${requirement.id}`}
              className={`run-detail__spec-req run-detail__spec-req--${requirement.classification === 'violated' ? 'missing' : requirement.classification}`}
            >
              <div className="run-detail__spec-req-head">
                <code>{requirement.id}</code>
                <span>{t(SPEC_SEMANTIC_CLASS_KEYS[requirement.classification])}</span>
              </div>
              <p className="run-detail__spec-reason">{requirement.rationale}</p>
              {requirement.disagreement_with_deterministic && (
                <p className="run-detail__semantic-disagreement">
                  {t('RunDetail.spec_semantic_disagreement')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {review.limitations.length > 0 && (
        <p className="run-detail__spec-limitations">
          {t('RunDetail.spec_semantic_limitations', {
            count: String(review.limitations.length),
          })}
        </p>
      )}
    </section>
  );
}

const ARTIFACT_GROUPS: { key: string; patterns: string[] }[] = [
  { key: 'learning', patterns: ['lesson', 'walkthrough', 'quiz', 'misconception'] },
  { key: 'eval', patterns: ['score', 'judge', 'claims', 'eval', 'spec_alignment'] },
  { key: 'graph', patterns: ['concepts', 'graphify', 'graph'] },
];

function classifyArtifact(name: string): string {
  for (const group of ARTIFACT_GROUPS) {
    if (group.patterns.some((p) => name.includes(p))) return group.key;
  }
  return 'other';
}

function ArtifactsPanel({
  run,
  runId,
  links,
  t,
}: {
  run: RunDetail;
  runId: string;
  links: { name: string; path: string; label: string }[];
  t: TranslateFn;
}) {
  const grouped = new Map<string, string[]>();
  for (const a of run.artifacts) {
    const group = classifyArtifact(a);
    const list = grouped.get(group) ?? [];
    list.push(a);
    grouped.set(group, list);
  }

  const groupOrder = ['learning', 'eval', 'graph', 'other'] as const;
  const groupLabelKeys: Record<string, string> = {
    learning: 'RunDetail.artifacts_group_learning',
    eval: 'RunDetail.artifacts_group_eval',
    graph: 'RunDetail.artifacts_group_graph',
    other: 'RunDetail.artifacts_group_other',
  };

  return (
    <div className="run-detail__artifacts">
      {links.length > 0 && (
        <nav className="run-detail__artifact-links" aria-label={t('RunDetail.overview_quick_links')}>
          {links.map((link) => (
            <Link key={link.path} to={link.path} className="run-detail__artifact-link">
              {link.label}
            </Link>
          ))}
          <Link to={`/concepts?run=${runId}`} className="run-detail__artifact-link">
            {t('RunDetail.link_concepts')}
          </Link>
        </nav>
      )}

      <div className="run-detail__artifact-groups">
        {groupOrder.map((groupKey) => {
          const items = grouped.get(groupKey);
          if (!items || items.length === 0) return null;
          return (
            <div key={groupKey} className="run-detail__artifact-section">
              <h3 className="run-detail__artifact-section-title">{t(groupLabelKeys[groupKey])}</h3>
              <ul className="run-detail__artifact-list">
                {items.map((a) => (
                  <li key={a} className="run-detail__artifact-item">
                    <code>{a}</code>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
