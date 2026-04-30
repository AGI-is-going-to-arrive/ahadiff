import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import AppShell from '../components/AppShell';
import CalendarHeatmap, { type HeatmapCell } from '../components/CalendarHeatmap';
import KpiCard from '../components/KpiCard';
import RatchetChart from '../components/RatchetChart';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import { ApiError } from '../api/client';
import { getRatchetHistory } from '../api/runs';
import { useRunsStore } from '../state/runs-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { useLocaleStore } from '../state/locale-store';
import type { RatchetHistoryEntry, Verdict } from '../api/types';
import { safeVerdict } from '../utils/verdict';
import '../components/Dashboard.css';

/**
 * Phase 4E: heatmap source-of-truth derivation.
 *
 * `/api/review/heatmap` (Phase 1E backend) is not consumed yet — the
 * dashboard derives a 30-day proxy from `runs[].created_at` so the widget
 * shows real activity instead of an empty grid. When the dedicated endpoint
 * lands we swap this helper for the API call without touching the
 * `<CalendarHeatmap>` consumer contract.
 */
function deriveHeatmapFromRuns(
  runs: ReadonlyArray<{ created_at: string }>,
): HeatmapCell[] {
  const buckets = new Map<string, number>();
  const today = new Date();
  /* Pre-seed last 30 days so quiet days still get a cell. */
  for (let i = 29; i >= 0; i -= 1) {
    const d = new Date(today);
    d.setUTCDate(today.getUTCDate() - i);
    const iso = d.toISOString().slice(0, 10);
    buckets.set(iso, 0);
  }
  for (const run of runs) {
    const iso = run.created_at.slice(0, 10);
    if (!buckets.has(iso)) continue;
    buckets.set(iso, (buckets.get(iso) ?? 0) + 1);
  }
  return Array.from(buckets, ([iso_date, count]) => ({ iso_date, count }));
}

const VERDICT_FILTERS = ['ALL', 'PASS', 'CAUTION', 'FAIL'] as const;
type VerdictFilter = (typeof VERDICT_FILTERS)[number];

export default function DashboardPage() {
  const { t } = useTranslation();
  const locale = useLocaleStore((s) => s.locale);
  const runs = useRunsStore((s) => s.runs);
  const loadRuns = useRunsStore((s) => s.loadRuns);
  const hasMore = useRunsStore((s) => s.hasMore);
  const loadMoreRuns = useRunsStore((s) => s.loadMoreRuns);
  const loadingMore = useRunsStore((s) => s.loadingMore);

  const [ratchetHistory, setRatchetHistory] = useState<RatchetHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Phase 4E: verdict filter chips above run list. */
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('ALL');
  const abortRef = useRef<AbortController | null>(null);

  const fetchDashboard = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    let failed = false;
    // 401/403 from any apiFetch means the bootstrap token was rejected. Show
    // a single auth-specific message instead of the generic fetch-failed one
    // (G1: distinguishes "serve process gone" from "network error").
    const isAuthErr = (e: unknown): boolean =>
      e instanceof ApiError && (e.status === 401 || e.status === 403);
    try {
      await loadRuns(undefined, { signal: controller.signal });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (isAuthErr(err)) { setError('Error.auth_failed'); failed = true; }
      else if (!controller.signal.aborted) { setError('Nav.dashboard'); failed = true; }
    }
    try {
      const res = await getRatchetHistory({}, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setRatchetHistory(res.history);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!failed && isAuthErr(err)) { setError('Error.auth_failed'); failed = true; }
      else if (!controller.signal.aborted && !failed) setError('Dashboard.ratchet_title');
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
        <div className="dashboard" role="status" aria-live="polite" aria-label={t('A11y.loading')}>
          <div className="dashboard__header">
            <Skeleton variant="text" width="200px" height="1.8em" />
            <Skeleton variant="text-short" width="300px" />
          </div>
          <div className="skeleton-grid">
            <Skeleton variant="card" />
            <Skeleton variant="card" />
            <Skeleton variant="card" />
          </div>
          <Skeleton variant="chart" />
          <SkeletonGroup count={4} variant="row" />
        </div>
      </AppShell>
    );
  }

  // ---- Auth-failed state (401/403 on bootstrap) ----
  // Render this branch even when runs.length > 0, because if auth is broken
  // we cannot trust the cached state to refresh — the user must reload after
  // bringing `ahadiff serve` back up.
  if (error === 'Error.auth_failed') {
    return (
      <AppShell>
        <div className="dashboard">
          <div className="dashboard__header">
            <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
          </div>
          <div role="alert" className="dashboard__error">
            {t('Error.auth_failed')}
            <button type="button" className="retry-btn" onClick={() => void fetchDashboard()}>
              {t('Error.retry')}
            </button>
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

          <RunListTable
            runs={runs}
            t={t}
            locale={locale}
            hasMore={hasMore}
            loadingMore={loadingMore}
            onLoadMore={() => { loadMoreRuns().catch(() => { /* handled by store */ }); }}
          />
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

        {/* Ratchet chart + heatmap row.
         * Phase 4E: 2-col layout pairs the trajectory chart with the new
         * 30-day heatmap so the dashboard shows both quality and tempo at
         * a glance. The heatmap derives counts from `runs.created_at`
         * until `/api/review/heatmap` lands. */}
        <div className="dashboard__chart-row">
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
          <CalendarHeatmap cells={deriveHeatmapFromRuns(runs)} />
        </div>

        {/* Run list */}
        <RunListTable
          runs={runs}
          t={t}
          locale={locale}
          hasMore={hasMore}
          loadingMore={loadingMore}
          verdictFilter={verdictFilter}
          onVerdictFilterChange={setVerdictFilter}
          onLoadMore={() => { loadMoreRuns().catch(() => { /* handled by store */ }); }}
        />
      </div>
    </AppShell>
  );
}

/* ---- Run list sub-component ---- */

interface RunListTableProps {
  runs: ReturnType<typeof useRunsStore.getState>['runs'];
  t: (key: MessageKey, params?: Record<string, string | number>) => string;
  locale: string;
  hasMore?: boolean;
  loadingMore?: boolean;
  verdictFilter?: VerdictFilter;
  onVerdictFilterChange?: (next: VerdictFilter) => void;
  onLoadMore?: () => void;
}

function RunListTable({
  runs,
  t,
  locale,
  hasMore,
  loadingMore,
  verdictFilter = 'ALL',
  onVerdictFilterChange,
  onLoadMore,
}: RunListTableProps) {
  /* Sort descending by created_at, then apply verdict filter. */
  const sorted = useMemo(() => {
    const base = [...runs].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
    if (verdictFilter === 'ALL') return base;
    return base.filter((r) => safeVerdict(r.verdict) === verdictFilter);
  }, [runs, verdictFilter]);

  const counts = useMemo(() => {
    const map: Record<VerdictFilter, number> = { ALL: runs.length, PASS: 0, CAUTION: 0, FAIL: 0 };
    for (const r of runs) {
      const v = safeVerdict(r.verdict);
      if (v === 'PASS' || v === 'CAUTION' || v === 'FAIL') map[v] += 1;
    }
    return map;
  }, [runs]);

  return (
    <div className="run-list-section">
      <div className="run-list-section__head">
        <h2 className="run-list-section__title">{t('Dashboard.run_list_title')}</h2>
        {onVerdictFilterChange ? (
          <div
            className="run-list-section__filters"
            role="tablist"
            aria-label={t('Dashboard.verdict_filter_label')}
          >
            {VERDICT_FILTERS.map((opt) => {
              const isActive = verdictFilter === opt;
              const labelKey = opt === 'ALL' ? 'Dashboard.filter_all' : (`Verdict.${opt}` as const);
              return (
                <button
                  key={opt}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  className={`verdict-chip${isActive ? ' verdict-chip--active' : ''} verdict-chip--${opt}`}
                  onClick={() => onVerdictFilterChange(opt)}
                >
                  <span>{t(labelKey)}</span>
                  <span className="verdict-chip__count">{counts[opt]}</span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
      {sorted.length === 0 ? (
        <p className="u-muted-sm" role="status">
          {t('Dashboard.filter_empty', { filter: t(verdictFilter === 'ALL' ? 'Dashboard.filter_all' : (`Verdict.${verdictFilter}` as const)) })}
        </p>
      ) : (
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
      )}
      {hasMore && (
        <div className="run-list-section__pagination">
          <button
            type="button"
            className="load-more-btn"
            onClick={onLoadMore}
            disabled={loadingMore}
          >
            {loadingMore ? t('Dashboard.loading_more') : t('Dashboard.load_more')}
          </button>
        </div>
      )}
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
