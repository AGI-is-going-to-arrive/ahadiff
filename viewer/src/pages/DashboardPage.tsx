import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import InfoHint from '../components/InfoHint';
import CalendarHeatmap, { type HeatmapCell } from '../components/CalendarHeatmap';
import KpiCard from '../components/KpiCard';
import RatchetChart from '../components/RatchetChart';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import { ApiError } from '../api/client';
import { getRatchetHistory } from '../api/runs';
import { fetchReviewHeatmap, fetchStats } from '../api/stats';
import { useRunsStore } from '../state/runs-store';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { useLocaleStore } from '../state/locale-store';
import type { RatchetHistoryEntry, StatsResponse, Verdict } from '../api/types';
import { safeVerdict } from '../utils/verdict';
import '../components/Dashboard.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));

/**
 * Fallback heatmap for older serve instances where `/api/review/heatmap` is
 * unavailable. Current serve uses the backend route as the source of truth.
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

const DIMENSION_LABEL_KEYS: Record<string, string> = {
  accuracy: 'Ratchet.dim_accuracy_label',
  evidence: 'Ratchet.dim_evidence_label',
  diff_coverage: 'Ratchet.dim_diff_coverage_label',
  learnability: 'Ratchet.dim_learnability_label',
  quiz_transfer: 'Ratchet.dim_quiz_transfer_label',
  spec_alignment: 'Ratchet.dim_spec_alignment_label',
  conciseness: 'Ratchet.dim_conciseness_label',
  safety_privacy: 'Ratchet.dim_safety_privacy_label',
};

function formatDimensionLabel(
  dim: string | null | undefined,
  t: TranslateFn,
): string {
  if (!dim) return '-';
  const labelKey = DIMENSION_LABEL_KEYS[dim];
  if (labelKey) return t(labelKey);
  return dim.replace(/_/g, ' ');
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const locale = useLocaleStore((s) => s.locale);
  const runs = useRunsStore((s) => s.runs);
  const loadRuns = useRunsStore((s) => s.loadRuns);
  const hasMore = useRunsStore((s) => s.hasMore);
  const loadMoreRuns = useRunsStore((s) => s.loadMoreRuns);
  const loadingMore = useRunsStore((s) => s.loadingMore);

  const [ratchetHistory, setRatchetHistory] = useState<RatchetHistoryEntry[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [heatmapCells, setHeatmapCells] = useState<HeatmapCell[] | null>(null);
  const [statsUnavailable, setStatsUnavailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Phase 4E: verdict filter chips above run list. */
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('ALL');
  const abortRef = useRef<AbortController | null>(null);
  const graphifyCard = (
    <Suspense
      fallback={<div className="dashboard-graphify-placeholder" aria-hidden="true" />}
    >
      <GraphifyCard compact />
    </Suspense>
  );

  const fetchDashboard = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    setStatsUnavailable(false);
    setHeatmapCells(null);
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
    }
    try {
      const s = await fetchStats({ signal: controller.signal });
      if (!controller.signal.aborted) {
        setStats(s);
        setStatsUnavailable(false);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!controller.signal.aborted) {
        setStats(null);
        setStatsUnavailable(true);
      }
    }
    try {
      const heatmap = await fetchReviewHeatmap({ signal: controller.signal });
      if (!controller.signal.aborted) {
        setHeatmapCells(
          heatmap.entries.map((entry) => ({
            iso_date: entry.date,
            count: entry.review_count,
          })),
        );
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!failed && isAuthErr(err)) { setError('Error.auth_failed'); failed = true; }
      if (!controller.signal.aborted) {
        setHeatmapCells(null);
      }
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
            <div className="dashboard__empty-icon" aria-hidden="true">Δ</div>
            <h2 className="dashboard__empty-title">{t('Dashboard.empty_title')}</h2>
            <p className="dashboard__empty-hint">{t('Dashboard.empty_hint')}</p>
            <div className="dashboard__empty-actions">
              <a href="#/onboarding" className="dashboard__empty-cta">
                {t('Dashboard.empty_cta')}
              </a>
              <span className="dashboard__empty-or">{t('Dashboard.empty_or')}</span>
              <code className="dashboard__empty-cmd">ahadiff learn HEAD~1..HEAD</code>
            </div>
          </div>
          {graphifyCard}
        </div>
      </AppShell>
    );
  }

  // ---- KPI computation ----
  const loadedRunCount = runs.length;
  const totalRuns = Math.max(stats?.total_runs ?? loadedRunCount, loadedRunCount);
  const passCount = runs.filter((r) => r.verdict === 'PASS').length;
  // Use runs.length (not totalRuns) as denominator — passCount comes from
  // the loaded runs array, so both must share the same source to avoid
  // under-reporting when the run list is paginated (Codex P2 fix).
  const passRate = loadedRunCount > 0 ? Math.round((passCount / loadedRunCount) * 100) : 0;

  const avgScore = stats?.avg_overall_score != null
    ? Math.round(stats.avg_overall_score)
    : null;
  const totalConcepts = stats?.total_concepts ?? 0;
  const statsHint = statsUnavailable ? t('Dashboard.kpi_stats_unavailable_hint') : undefined;

  const passRateTone =
    passRate >= 80 ? 'success' as const :
    passRate >= 50 ? 'warning' as const :
    'danger' as const;

  const scoreTone =
    avgScore == null ? 'default' as const :
    avgScore >= 80 ? 'success' as const :
    avgScore >= 60 ? 'warning' as const :
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
              value={formatDimensionLabel(run.weakest_dim, t)}
            />
          </div>

          <div className="ratchet-section">
            <div className="ratchet-section__fallback">
              {t('Dashboard.cold_start_single_run')}
            </div>
          </div>

          {graphifyCard}

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
      <div className="dashboard" aria-live="polite">
        <div className="dashboard__header">
          <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
          <p className="dashboard__subtitle">{t('Dashboard.subtitle')}</p>
        </div>
        {errorBanner}

        {/* KPI row — 4 cards matching V6 template */}
        <div className="kpi-grid kpi-grid--4col">
          <KpiCard
            label={t('Dashboard.kpi_total_runs')}
            value={totalRuns}
            hint={statsHint}
          />
          <KpiCard
            label={t('Dashboard.kpi_avg_score')}
            value={avgScore != null ? `${avgScore}` : '-'}
            tone={scoreTone}
            hint={statsHint}
          />
          <KpiCard
            label={t('Dashboard.kpi_pass_rate')}
            value={`${passRate}%`}
            tone={passRateTone}
            hint={t('Dashboard.kpi_loaded_runs_hint', { count: loadedRunCount })}
          />
          <KpiCard
            label={t('Dashboard.kpi_total_concepts')}
            value={totalConcepts}
            tone={totalConcepts > 0 ? 'success' : 'default'}
            hint={statsHint}
          />
        </div>

        {/* Ratchet chart + heatmap row. The heatmap prefers the backend
         * review log source and falls back to loaded-run dates when talking
         * to an older serve process. */}
        <div className="dashboard__chart-row">
          <div className="ratchet-section">
            <div className="ratchet-section__card">
              <div className="ratchet-section__header">
                <h2>{t('Dashboard.ratchet_title')} <InfoHint label={t('Dashboard.ratchet_hint')} /></h2>
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
          <CalendarHeatmap cells={heatmapCells ?? deriveHeatmapFromRuns(runs)} />
        </div>

        {/* Graphify status — optional, self-fetching, hidden when disabled */}
        {graphifyCard}

        {/* Weakest dimension chip cloud — V6 alignment */}
        {stats && stats.weakest_dimensions.length > 0 && (
          <div className="dashboard__weak-concepts">
            <h2 className="dashboard__section-title">{t('Dashboard.weakest_dimensions_title')} <InfoHint label={t('Dashboard.weakest_dim_hint')} /></h2>
            <div className="dashboard__chip-cloud">
              {stats.weakest_dimensions.map((dim) => (
                <span key={dim} className="dashboard__weak-chip" title={dim} dir="auto">
                  {formatDimensionLabel(dim, t)}
                </span>
              ))}
            </div>
          </div>
        )}

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
  t: TranslateFn;
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
            role="group"
            aria-label={t('Dashboard.verdict_filter_label')}
          >
            {VERDICT_FILTERS.map((opt) => {
              const isActive = verdictFilter === opt;
              const labelKey = opt === 'ALL' ? 'Dashboard.filter_all' : (`Verdict.${opt}` as const);
              return (
                <button
                  key={opt}
                  type="button"
                  aria-pressed={isActive}
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
                <a className="run-list__link mono" href={`#/run/${encodeURIComponent(run.run_id)}/lesson`}>
                  {run.source_ref || run.run_id.slice(0, 8)}
                </a>
              </td>
              <td>
                <VerdictBadge verdict={safeVerdict(run.verdict)} t={t} />
              </td>
              <td className="num">{run.overall}</td>
              <td>{formatDimensionLabel(run.weakest_dim, t)}</td>
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

function VerdictBadge({ verdict, t }: { verdict: Verdict; t: TranslateFn }) {
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
