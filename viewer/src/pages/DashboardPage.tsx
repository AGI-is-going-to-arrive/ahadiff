import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import AppShell from '../components/AppShell';
import KpiCard from '../components/KpiCard';
import RatchetChart from '../components/RatchetChart';
import { getRatchetHistory } from '../api/runs';
import { useRunsStore } from '../state/runs-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { useLocaleStore } from '../state/locale-store';
import type { RatchetHistoryEntry, Verdict } from '../api/types';
import '../components/Dashboard.css';

const VALID_VERDICTS: ReadonlySet<Verdict> = new Set(['PASS', 'CAUTION', 'FAIL']);

function safeVerdict(value: unknown): Verdict {
  return typeof value === 'string' && VALID_VERDICTS.has(value as Verdict)
    ? (value as Verdict)
    : 'CAUTION';
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const locale = useLocaleStore((s) => s.locale);
  const runs = useRunsStore((s) => s.runs);
  const loadRuns = useRunsStore((s) => s.loadRuns);

  const [ratchetHistory, setRatchetHistory] = useState<RatchetHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchDashboard = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    let failed = false;
    try {
      await loadRuns(undefined, { signal: controller.signal });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!controller.signal.aborted) { setError('Nav.dashboard'); failed = true; }
    }
    try {
      const history = await getRatchetHistory({ signal: controller.signal });
      if (!controller.signal.aborted) {
        setRatchetHistory(history);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!controller.signal.aborted && !failed) setError('Dashboard.ratchet_title');
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [loadRuns]);

  useEffect(() => {
    void fetchDashboard();
    return () => abortRef.current?.abort();
  }, [fetchDashboard]);

  // ---- Loading state ----
  if (loading) {
    return (
      <AppShell>
        <div className="dashboard">
          <div className="dashboard__loading" role="status" aria-live="polite">
            <span className="loading-spinner" />{t('Serve.loading')}
          </div>
        </div>
      </AppShell>
    );
  }

  // ---- Error state ----
  if (error && runs.length === 0) {
    return (
      <AppShell>
        <div className="dashboard">
          <div className="dashboard__header">
            <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
          </div>
          <div role="alert" className="dashboard__error">
            {t('Error.fetch_failed', { resource: t(error as MessageKey) })}
            <button type="button" className="retry-btn" onClick={() => void fetchDashboard()}>
              {t('Error.retry')}
            </button>
          </div>
        </div>
      </AppShell>
    );
  }

  // ---- Empty state (0 runs) ----
  if (runs.length === 0) {
    return (
      <AppShell>
        <div className="dashboard">
          <div className="dashboard__header">
            <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
          </div>
          <div className="dashboard__empty">
            <span>{t('Serve.empty')}</span>
            <span className="dashboard__empty-hint">{t('Dashboard.empty_hint')}</span>
          </div>
        </div>
      </AppShell>
    );
  }

  // ---- KPI computation ----
  const totalRuns = runs.length;
  const passCount = runs.filter((r) => r.verdict === 'PASS').length;
  const passRate = totalRuns > 0 ? Math.round((passCount / totalRuns) * 100) : 0;

  // Weakest dimension: mode across all runs
  const dimCounts: Record<string, number> = {};
  for (const r of runs) {
    if (r.weakest_dim) {
      dimCounts[r.weakest_dim] = (dimCounts[r.weakest_dim] ?? 0) + 1;
    }
  }
  const weakestDim = Object.entries(dimCounts).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '-';

  const passRateTone =
    passRate >= 80 ? 'success' as const :
    passRate >= 50 ? 'warning' as const :
    'danger' as const;

  const errorBanner = error ? (
    <div role="alert" className="dashboard__error-banner">
      {t('Error.fetch_failed', { resource: t(error as MessageKey) })}
    </div>
  ) : null;

  // ---- Cold start: single run ----
  if (runs.length === 1) {
    const run = runs[0];
    return (
      <AppShell>
        <div className="dashboard">
          <div className="dashboard__header">
            <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
            <p className="dashboard__subtitle">{t('Dashboard.subtitle')}</p>
          </div>
          {errorBanner}

          <div className="kpi-grid kpi-grid--2col">
            <KpiCard
              label={t('Rubric.overall')}
              value={run.overall}
              tone={run.verdict === 'PASS' ? 'success' : run.verdict === 'CAUTION' ? 'warning' : 'danger'}
            />
            <KpiCard
              label={t('Rubric.weakest_dim')}
              value={run.weakest_dim || '-'}
            />
          </div>

          <div className="ratchet-section">
            <div className="ratchet-section__fallback">
              {t('Dashboard.cold_start_single_run')}
            </div>
          </div>

          <RunListTable runs={runs} t={t} locale={locale} />
        </div>
      </AppShell>
    );
  }

  // ---- Full dashboard (>= 2 runs) ----
  return (
    <AppShell>
      <div className="dashboard">
        <div className="dashboard__header">
          <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
          <p className="dashboard__subtitle">{t('Dashboard.subtitle')}</p>
        </div>
        {errorBanner}

        {/* KPI row */}
        <div className="kpi-grid kpi-grid--3col">
          <KpiCard
            label={t('Dashboard.kpi_total_runs')}
            value={totalRuns}
          />
          <KpiCard
            label={t('Dashboard.kpi_pass_rate')}
            value={`${passRate}%`}
            tone={passRateTone}
          />
          <KpiCard
            label={t('Dashboard.kpi_weakest_dim')}
            value={weakestDim}
            tone="warning"
          />
        </div>

        {/* Ratchet chart */}
        <div className="ratchet-section">
          <div className="ratchet-section__card">
            <div className="ratchet-section__header">
              <h2>{t('Dashboard.ratchet_title')}</h2>
              <span className="ratchet-section__meta">{t('Rubric.overall')}</span>
            </div>
            <div className="ratchet-section__body">
              {ratchetHistory.length >= 2 ? (
                <RatchetChart history={ratchetHistory} />
              ) : (
                <div className="ratchet-section__fallback">
                  {t('Dashboard.ratchet_not_enough')}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Run list */}
        <RunListTable runs={runs} t={t} locale={locale} />
      </div>
    </AppShell>
  );
}

/* ---- Run list sub-component ---- */

interface RunListTableProps {
  runs: ReturnType<typeof useRunsStore.getState>['runs'];
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
  locale: string;
}

function RunListTable({ runs, t, locale }: RunListTableProps) {
  // Sort descending by created_at
  const sorted = [...runs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );

  return (
    <div className="run-list-section">
      <h2 className="run-list-section__title">{t('Dashboard.run_list_title')}</h2>
      <table className="run-list" aria-label={t('Dashboard.run_list_title')}>
        <thead>
          <tr>
            <th scope="col">{t('Dashboard.col_ref')}</th>
            <th scope="col">{t('Dashboard.col_verdict')}</th>
            <th scope="col">{t('Rubric.overall')}</th>
            <th scope="col">{t('Rubric.weakest_dim')}</th>
            <th scope="col">{t('Dashboard.col_date')}</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((run) => (
            <tr key={run.run_id}>
              <td>
                <Link className="run-list__link mono" to={`/run/${run.run_id}/lesson`}>
                  {run.source_ref || run.run_id.slice(0, 8)}
                </Link>
              </td>
              <td>
                <VerdictBadge verdict={safeVerdict(run.verdict)} t={t} />
              </td>
              <td className="mono">{run.overall}</td>
              <td>{run.weakest_dim || '-'}</td>
              <td className="mono">
                {formatDate(run.created_at, locale)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---- Verdict badge ---- */

function VerdictBadge({ verdict, t }: { verdict: Verdict; t: (k: MessageKey) => string }) {
  const label = t(`Verdict.${verdict}`) || verdict;
  return (
    <span className={`verdict-badge verdict-badge--${verdict}`}>
      {label}
    </span>
  );
}

/* ---- Date formatting ---- */

function formatDate(iso: string, locale: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}
