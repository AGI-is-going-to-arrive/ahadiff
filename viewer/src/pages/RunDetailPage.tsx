import { useCallback, useEffect, useState, type KeyboardEvent } from 'react';
import { useParams, Link } from 'react-router-dom';
import AppShell from '../components/AppShell';
import ScoreBreakdown from '../components/ScoreBreakdown';
import JudgeReport from '../components/JudgeReport';
import { getRun, getRunScore } from '../api/runs';
import { scorePayloadSchema } from '../api/schemas';
import { useTranslation, type TranslateFn } from '../i18n/useTranslation';
import type { RunDetail, ScorePayload } from '../api/types';
import { safeVerdict } from '../utils/verdict';
import './RunDetailPage.css';

type DetailTab = 'overview' | 'score' | 'judge' | 'artifacts';
const TABS: DetailTab[] = ['overview', 'score', 'judge', 'artifacts'];
const TAB_KEYS: Record<DetailTab, string> = {
  overview: 'RunDetail.tab_overview',
  score: 'RunDetail.tab_score',
  judge: 'RunDetail.tab_judge',
  artifacts: 'RunDetail.tab_artifacts',
};
const TAB_IDS: Record<DetailTab, string> = {
  overview: 'rd-tab-overview',
  score: 'rd-tab-score',
  judge: 'rd-tab-judge',
  artifacts: 'rd-tab-artifacts',
};
const TAB_PANEL_IDS: Record<DetailTab, string> = {
  overview: 'rd-panel-overview',
  score: 'rd-panel-score',
  judge: 'rd-panel-judge',
  artifacts: 'rd-panel-artifacts',
};

function parseTabParam(): DetailTab {
  const query = window.location.hash.split('?')[1] ?? '';
  const tab = new URLSearchParams(query).get('tab');
  if (tab && TABS.includes(tab as DetailTab)) return tab as DetailTab;
  return 'overview';
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

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t, locale } = useTranslation();
  const [activeTab, setActiveTab] = useState<DetailTab>(parseTabParam);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [score, setScore] = useState<ScorePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

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
        setScore(null);
      }
      if (scoreResult.status === 'fulfilled') {
        setScore(scoreResult.value);
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [runId]);

  const handleTabKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>) => {
      const idx = TABS.indexOf(activeTab);
      let next = idx;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        next = (idx + 1) % TABS.length;
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        next = (idx - 1 + TABS.length) % TABS.length;
      } else if (e.key === 'Home') {
        next = 0;
      } else if (e.key === 'End') {
        next = TABS.length - 1;
      } else {
        return;
      }
      e.preventDefault();
      setActiveTab(TABS[next]);
      document.getElementById(TAB_IDS[TABS[next]])?.focus();
    },
    [activeTab],
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
          {t('Error.fetch_failed', { resource: 'run' })}
        </div>
      </AppShell>
    );
  }

  const hasJudge = run.artifacts.includes('judge.json');
  const hasScore = score != null;
  const links = artifactLinks(run.artifacts, runId, t);

  return (
    <AppShell>
      <header className="run-detail__header">
        <h1 className="run-detail__title">
          {t('RunDetail.title')}
          <code className="run-detail__run-id">{runId.length > 16 ? `${runId.slice(0, 16)}…` : runId}</code>
        </h1>
      </header>

      <div className="run-detail__tabs" role="tablist" aria-label={t('RunDetail.title')}>
        {TABS.map((tab) => {
          const disabled =
            (tab === 'judge' && !hasJudge) ||
            (tab === 'score' && !hasScore);
          return (
            <button
              key={tab}
              id={TAB_IDS[tab]}
              role="tab"
              type="button"
              className={`run-detail__tab${activeTab === tab ? ' run-detail__tab--active' : ''}${disabled ? ' run-detail__tab--disabled' : ''}`}
              aria-selected={activeTab === tab}
              aria-controls={TAB_PANEL_IDS[tab]}
              aria-disabled={disabled || undefined}
              tabIndex={activeTab === tab ? 0 : -1}
              onClick={() => !disabled && setActiveTab(tab)}
              onKeyDown={handleTabKeyDown}
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
