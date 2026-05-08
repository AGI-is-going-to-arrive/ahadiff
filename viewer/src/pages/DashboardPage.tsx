import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import InfoHint from '../components/InfoHint';
import CalendarHeatmap, { type HeatmapCell } from '../components/CalendarHeatmap';
import KpiCard from '../components/KpiCard';
import RatchetChart from '../components/RatchetChart';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import { ApiError } from '../api/client';
import { getUsage } from '../api/config';
import { getWeakConcepts } from '../api/review';
import { getRatchetHistory } from '../api/runs';
import { fetchLearningEffectiveness, fetchReviewHeatmap, fetchStats } from '../api/stats';
import { useRunsStore } from '../state/runs-store';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { useLocaleStore } from '../state/locale-store';
import type {
  LearningEffectivenessResponse,
  RatchetHistoryEntry,
  StatsResponse,
  Verdict,
  WeakConceptItem,
} from '../api/types';
import type { UsageResponse } from '../api/config';
import { safeVerdict } from '../utils/verdict';
import '../components/Dashboard.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));
const LearnModeDialog = lazy(() => import('../components/LearnModeDialog'));

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

const SOURCE_GROUPS = [
  { key: 'ALL', kinds: null, labelKey: 'Dashboard.source_all' as const },
  { key: 'COMMITS', kinds: ['git_ref', 'git_since'], labelKey: 'Dashboard.source_git_commits' as const },
  { key: 'WORKING', kinds: ['git_staged', 'git_staged_unstaged', 'git_unstaged'], labelKey: 'Dashboard.source_git_working' as const },
  { key: 'PATCH', kinds: ['patch_file', 'patch_stdin'], labelKey: 'Dashboard.source_patch' as const },
  { key: 'COMPARE', kinds: ['file_compare'], labelKey: 'Dashboard.source_file_compare' as const },
] as const;
type SourceFilter = (typeof SOURCE_GROUPS)[number]['key'];

function sourceGroupLabel(sourceKind: string): string {
  for (const g of SOURCE_GROUPS) {
    if (g.kinds?.includes(sourceKind as never)) return g.key;
  }
  return 'ALL';
}

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
  const [learning, setLearning] = useState<LearningEffectivenessResponse | null>(null);
  const [heatmapCells, setHeatmapCells] = useState<HeatmapCell[] | null>(null);
  const [statsUnavailable, setStatsUnavailable] = useState(false);
  const [usageUnavailable, setUsageUnavailable] = useState(false);
  const [weakConcepts, setWeakConcepts] = useState<WeakConceptItem[]>([]);
  const [usage, setUsage] = useState<UsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLearnDialogOpen, setIsLearnDialogOpen] = useState(false);
  /** Phase 4E: verdict filter chips above run list. */
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>('ALL');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('ALL');
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
    setUsageUnavailable(false);
    setHeatmapCells(null);
    setLearning(null);
    setWeakConcepts([]);
    setUsage(null);
    let failed = false;
    // 401/403 from any apiFetch means the bootstrap token was rejected. Show
    // a single auth-specific message instead of the generic fetch-failed one
    // (G1: distinguishes "serve process gone" from "network error").
    const isAuthErr = (e: unknown): boolean =>
      e instanceof ApiError && (e.status === 401 || e.status === 403);

    const [
      runsResult,
      ratchetResult,
      statsResult,
      heatmapResult,
      learningResult,
      weakResult,
      usageResult,
    ] =
      await Promise.allSettled([
        loadRuns(undefined, { signal: controller.signal }),
        getRatchetHistory({}, { signal: controller.signal }),
        fetchStats({ signal: controller.signal }),
        fetchReviewHeatmap({ signal: controller.signal }),
        fetchLearningEffectiveness({ signal: controller.signal }),
        getWeakConcepts({ signal: controller.signal }),
        getUsage({ signal: controller.signal }),
      ]);

    if (controller.signal.aborted) return;

    if (runsResult.status === 'rejected') {
      if (isAuthErr(runsResult.reason)) { setError('Error.auth_failed'); failed = true; }
      else { setError('Nav.dashboard'); failed = true; }
    }

    if (ratchetResult.status === 'fulfilled') {
      setRatchetHistory(ratchetResult.value.history);
    } else if (!failed && isAuthErr(ratchetResult.reason)) {
      setError('Error.auth_failed');
      failed = true;
    } else if (!failed) {
      setError('Dashboard.ratchet_title');
    }

    if (statsResult.status === 'fulfilled') {
      setStats(statsResult.value);
      setStatsUnavailable(false);
    } else {
      setStats(null);
      setStatsUnavailable(true);
    }

    if (heatmapResult.status === 'fulfilled') {
      setHeatmapCells(
        heatmapResult.value.entries.map((entry) => ({
          iso_date: entry.date,
          count: entry.review_count,
        })),
      );
    } else {
      if (!failed && isAuthErr(heatmapResult.reason)) {
        setError('Error.auth_failed');
        failed = true;
      }
      setHeatmapCells(null);
    }

    setLearning(learningResult.status === 'fulfilled' ? learningResult.value : null);
    setWeakConcepts(
      weakResult.status === 'fulfilled' ? weakResult.value.concepts : [],
    );
    if (usageResult.status === 'fulfilled') {
      setUsage(usageResult.value);
      setUsageUnavailable(false);
    } else {
      setUsage(null);
      setUsageUnavailable(true);
    }
    setLoading(false);
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
      <AppShell globalShortcutsDisabled={isLearnDialogOpen}>
        <div className="dashboard">
          <div className="dashboard__header">
            <h1 className="dashboard__title">{t('Dashboard.title')}</h1>
          </div>

          <div className="dashboard__empty">
            <div className="dashboard__empty-icon" aria-hidden="true">Δ</div>
            <h2 className="dashboard__empty-title">{t('Dashboard.empty_title')}</h2>
            <p className="dashboard__empty-hint">{t('Dashboard.empty_hint')}</p>
            <div className="dashboard__empty-actions">
              <button
                type="button"
                className="dashboard__empty-cta dashboard__empty-cta--primary"
                aria-label={t('Dashboard.empty_first_run_aria')}
                onClick={() => setIsLearnDialogOpen(true)}
              >
                {t('Dashboard.empty_first_run')}
              </button>
              <a href="#/onboarding" className="dashboard__empty-cta dashboard__empty-cta--secondary">
                {t('Dashboard.empty_cta')}
              </a>
              <span className="dashboard__empty-or">{t('Dashboard.empty_or')}</span>
              <code className="dashboard__empty-cmd">ahadiff learn HEAD~1..HEAD</code>
            </div>
          </div>
          {isLearnDialogOpen ? (
            <Suspense fallback={null}>
              <LearnModeDialog open={isLearnDialogOpen} onClose={() => setIsLearnDialogOpen(false)} />
            </Suspense>
          ) : null}
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
  const totalLlmCalls: string | number = usage ? usage.total_calls : '-';
  const usageHint = usageUnavailable ? t('Dashboard.kpi_usage_unavailable_hint') : undefined;

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


          <div className="kpi-grid kpi-grid--3col">
            <KpiCard
              label={t('Rubric.overall')}
              value={run.overall}
              tone={run.verdict === 'PASS' ? 'success' : run.verdict === 'CAUTION' ? 'warning' : 'danger'}
            />
            <KpiCard
              label={t('Rubric.weakest_dim')}
              value={formatDimensionLabel(run.weakest_dim, t)}
            />
            <KpiCard
              label={t('Dashboard.kpi_llm_calls')}
              value={totalLlmCalls}
              hint={usageHint}
            />
          </div>

          <div className="ratchet-section">
            <div className="ratchet-section__fallback">
              {t('Dashboard.cold_start_single_run')}
            </div>
          </div>

          {graphifyCard}

          {/* Weak concepts section also surfaces in the single-run path so
           * users see learning gaps even on cold start. */}
          {weakConcepts.length > 0 && (
            <div className="dashboard__weak-list-section">
              <h2 className="dashboard__section-title">
                {t('Dashboard.weak_concepts_title')}
              </h2>
              <ul className="dashboard__weak-list">
                {weakConcepts.slice(0, 8).map((wc) => {
                  const mastery = Math.max(
                    0,
                    Math.min(100, Math.round((wc.stability / 30) * 100)),
                  );
                  return (
                    <li key={wc.card_id} className="dashboard__weak-list-item">
                      <span className="dashboard__weak-list-name" title={wc.concept}>
                        {wc.concept}
                      </span>
                      <div
                        className="dashboard__weak-list-bar"
                        role="progressbar"
                        aria-label={t('Dashboard.weak_concepts_mastery_label', {
                          concept: wc.concept,
                        })}
                        aria-valuenow={mastery}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuetext={`${mastery}%`}
                      >
                        <div
                          className="dashboard__weak-list-bar-fill"
                          style={{ width: `${mastery}%` }}
                        />
                      </div>
                      <span className="dashboard__weak-list-pct mono">{mastery}%</span>
                    </li>
                  );
                })}
              </ul>
              <a className="dashboard__weak-list-link" href="#/concepts">
                {t('Dashboard.weak_concepts_view_all')}
              </a>
            </div>
          )}

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

        {/* KPI row — 5 cards (V6 4-card row + LLM Calls). Uses --5col grid
         * variant; collapses to 2-col then 1-col responsively. */}
        <div className="kpi-grid kpi-grid--5col">
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
          <KpiCard
            label={t('Dashboard.kpi_llm_calls')}
            value={totalLlmCalls}
            hint={usageHint}
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

        {/* Learning effectiveness summary — surfaces /api/stats/learning so
         * users can see whether SRS reviews are converting into transfer. */}
        {learning && (
          <div className="dashboard__learning">
            <h2 className="dashboard__section-title">
              {t('Dashboard.learning_effectiveness_title')}
            </h2>
            <div className="kpi-grid kpi-grid--3col">
              <KpiCard
                label={t('Dashboard.learning_transfer_rate')}
                value={`${Math.round(learning.transfer_rate * 100)}%`}
                tone={
                  learning.transfer_rate >= 0.6
                    ? 'success'
                    : learning.transfer_rate >= 0.3
                      ? 'warning'
                      : 'default'
                }
              />
              <KpiCard
                label={t('Dashboard.concepts_improving')}
                value={learning.concepts_improving}
                tone={learning.concepts_improving > 0 ? 'success' : 'default'}
              />
              <KpiCard
                label={t('Dashboard.concepts_declining')}
                value={learning.concepts_declining}
                tone={learning.concepts_declining > 0 ? 'warning' : 'default'}
              />
            </div>
          </div>
        )}

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

        {/* Weak concepts list — sourced from /api/concepts/weak. Mastery
         * % bar is a 0-100 proxy from FSRS stability, capped at ~30 day
         * retention. */}
        {weakConcepts.length > 0 && (
          <div className="dashboard__weak-list-section">
            <h2 className="dashboard__section-title">
              {t('Dashboard.weak_concepts_title')}
            </h2>
            <ul className="dashboard__weak-list">
              {weakConcepts.slice(0, 8).map((wc) => {
                const mastery = Math.max(
                  0,
                  Math.min(100, Math.round((wc.stability / 30) * 100)),
                );
                return (
                  <li key={wc.card_id} className="dashboard__weak-list-item">
                    <span className="dashboard__weak-list-name" title={wc.concept}>
                      {wc.concept}
                    </span>
                    <div
                      className="dashboard__weak-list-bar"
                      role="progressbar"
                      aria-label={t('Dashboard.weak_concepts_mastery_label', {
                        concept: wc.concept,
                      })}
                      aria-valuenow={mastery}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuetext={`${mastery}%`}
                    >
                      <div
                        className="dashboard__weak-list-bar-fill"
                        style={{ width: `${mastery}%` }}
                      />
                    </div>
                    <span className="dashboard__weak-list-pct mono">{mastery}%</span>
                  </li>
                );
              })}
            </ul>
            <a className="dashboard__weak-list-link" href="#/concepts">
              {t('Dashboard.weak_concepts_view_all')}
            </a>
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
          sourceFilter={sourceFilter}
          onSourceFilterChange={setSourceFilter}
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
  sourceFilter?: SourceFilter;
  onSourceFilterChange?: (next: SourceFilter) => void;
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
  sourceFilter = 'ALL',
  onSourceFilterChange,
  onLoadMore,
}: RunListTableProps) {
  /* Sort descending by created_at, then apply verdict + source filters. */
  const sorted = useMemo(() => {
    const base = [...runs].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
    let result = base;
    if (verdictFilter !== 'ALL') {
      result = result.filter((r) => safeVerdict(r.verdict) === verdictFilter);
    }
    if (sourceFilter !== 'ALL') {
      const group = SOURCE_GROUPS.find((g) => g.key === sourceFilter);
      if (group?.kinds) {
        result = result.filter((r) => (group.kinds as readonly string[]).includes(r.source_kind));
      }
    }
    return result;
  }, [runs, verdictFilter, sourceFilter]);

  const counts = useMemo(() => {
    const map: Record<VerdictFilter, number> = { ALL: runs.length, PASS: 0, CAUTION: 0, FAIL: 0 };
    for (const r of runs) {
      const v = safeVerdict(r.verdict);
      if (v === 'PASS' || v === 'CAUTION' || v === 'FAIL') map[v] += 1;
    }
    return map;
  }, [runs]);

  const sourceCounts = useMemo(() => {
    const map: Record<string, number> = { ALL: runs.length };
    for (const g of SOURCE_GROUPS) {
      if (g.key !== 'ALL') map[g.key] = 0;
    }
    for (const r of runs) {
      const gk = sourceGroupLabel(r.source_kind);
      if (gk !== 'ALL' && map[gk] != null) map[gk] += 1;
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
      {onSourceFilterChange ? (
        <div
          className="run-list-section__source-filters"
          role="group"
          aria-label={t('Dashboard.source_filter_label')}
        >
          {SOURCE_GROUPS.map((g) => {
            const isActive = sourceFilter === g.key;
            const count = sourceCounts[g.key] ?? 0;
            if (g.key !== 'ALL' && !isActive && count === 0 && !hasMore) return null;
            return (
              <button
                key={g.key}
                type="button"
                aria-pressed={isActive}
                className={`source-chip${isActive ? ' source-chip--active' : ''}`}
                onClick={() => onSourceFilterChange(g.key)}
              >
                <span>{t(g.labelKey)}</span>
                <span className="source-chip__count">{count}</span>
              </button>
            );
          })}
        </div>
      ) : null}
      {sorted.length === 0 ? (
        <p className="u-muted-sm" role="status">
          {sourceFilter !== 'ALL'
            ? t(hasMore ? 'Dashboard.filter_empty_with_source_has_more' : 'Dashboard.filter_empty_with_source', {
                verdict: t(verdictFilter === 'ALL' ? 'Dashboard.filter_all' : (`Verdict.${verdictFilter}` as const)),
                source: t(SOURCE_GROUPS.find((g) => g.key === sourceFilter)?.labelKey ?? 'Dashboard.source_all'),
              })
            : t('Dashboard.filter_empty', { filter: t(verdictFilter === 'ALL' ? 'Dashboard.filter_all' : (`Verdict.${verdictFilter}` as const)) })}
        </p>
      ) : (
      <table className="run-list" aria-label={t('Dashboard.run_list_title')}>
        <thead>
          <tr>
            <th scope="col">{t('Dashboard.col_ref')}</th>
            <th scope="col">{t('Dashboard.col_source')}</th>
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
                <SourceBadge sourceKind={run.source_kind} t={t} />
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

/* ---- Source badge ---- */

const SOURCE_KIND_I18N_KEYS: Record<string, string> = {
  git_ref: 'Dashboard.source_badge_git_ref',
  git_since: 'Dashboard.source_badge_git_since',
  git_staged: 'Dashboard.source_badge_git_staged',
  git_staged_unstaged: 'Dashboard.source_badge_git_staged_unstaged',
  git_unstaged: 'Dashboard.source_badge_git_unstaged',
  patch_file: 'Dashboard.source_badge_patch_file',
  patch_stdin: 'Dashboard.source_badge_patch_stdin',
  file_compare: 'Dashboard.source_badge_file_compare',
};

function SourceBadge({ sourceKind, t }: { sourceKind: string; t: TranslateFn }) {
  const i18nKey = SOURCE_KIND_I18N_KEYS[sourceKind];
  const label = i18nKey ? t(i18nKey) : sourceKind;
  const group = sourceGroupLabel(sourceKind);
  return (
    <span className={`source-badge source-badge--${group}`} title={sourceKind} aria-label={label}>
      {label}
    </span>
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
