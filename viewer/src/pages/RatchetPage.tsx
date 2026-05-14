import { lazy, Suspense, useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import AppShell from '../components/AppShell';
import ExportModal from '../components/ExportModal';
import InfoHint from '../components/InfoHint';
import RatchetChart from '../components/RatchetChart';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import {
  getRatchetHistory,
  getRatchetTransparency,
  getRunScore,
} from '../api/runs';
import { scorePayloadSchema } from '../api/schemas';
import { fetchSpecAlignment } from '../api/stats';
import { useTranslation, type TranslateFn } from '../i18n/useTranslation';
import { useLocaleStore } from '../state/locale-store';
import type {
  RatchetHistoryEntry,
  RatchetResultRow,
  RatchetTransparencyResponse,
  ScorePayload,
  SpecAlignmentResponse,
} from '../api/types';
import { safeVerdict } from '../utils/verdict';
import '../components/Ratchet.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));
const ImprovePreview = lazy(() => import('../components/ImprovePreview'));

type RatchetTab = 'results' | 'rubric' | 'benchmark' | 'judge' | 'improve';
const RATCHET_TABS: RatchetTab[] = ['results', 'rubric', 'benchmark', 'judge', 'improve'];
const TAB_LABEL_KEYS: Record<RatchetTab, string> = {
  results: 'Ratchet.tab_results',
  rubric: 'Ratchet.tab_rubric',
  benchmark: 'Ratchet.tab_benchmark',
  judge: 'Ratchet.tab_judge',
  improve: 'Improve.tab_preview',
};
const TAB_IDS: Record<RatchetTab, string> = {
  results: 'ratchet-tab-results',
  rubric: 'ratchet-tab-rubric',
  benchmark: 'ratchet-tab-benchmark',
  judge: 'ratchet-tab-judge',
  improve: 'ratchet-tab-improve',
};
const TAB_PANEL_IDS: Record<RatchetTab, string> = {
  results: 'ratchet-panel-results',
  rubric: 'ratchet-panel-rubric',
  benchmark: 'ratchet-panel-benchmark',
  judge: 'ratchet-panel-judge',
  improve: 'ratchet-panel-improve',
};

interface RatchetNote {
  runId: string;
  phase25?: boolean;
  phase25Note?: string;
  triggerReason?: string;
  targetDimension?: string;
  targetedPassed?: boolean;
  targetedBaselineScore?: number;
  targetedCandidateScore?: number;
}

interface RatchetNoteSource {
  run_id: string;
  note_json: string | null;
}

const KEPT_STATUSES = new Set(['baseline', 'keep', 'keep_final']);

function formatDate(iso: string, locale: string): string {
  try {
    return new Date(iso).toLocaleDateString(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return iso;
  }
}

function formatScore(value: number, locale: string, fractionDigits = 1): string {
  try {
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  } catch {
    return value.toFixed(fractionDigits);
  }
}

function readStringField(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key];
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function readNumberField(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function parseRatchetNote(entry: RatchetNoteSource): RatchetNote | null {
  if (!entry.note_json) return null;
  try {
    const parsed = JSON.parse(entry.note_json) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const record = parsed as Record<string, unknown>;
    return {
      runId: entry.run_id,
      phase25: record.phase25 === true,
      phase25Note: readStringField(record, 'phase25_note'),
      triggerReason: readStringField(record, 'trigger_reason'),
      targetDimension: readStringField(record, 'target_dimension'),
      targetedPassed: typeof record.targeted_passed === 'boolean' ? record.targeted_passed : undefined,
      targetedBaselineScore: readNumberField(record, 'targeted_baseline_score'),
      targetedCandidateScore: readNumberField(record, 'targeted_candidate_score'),
    };
  } catch {
    return null;
  }
}

function parseScorePayload(content: string): ScorePayload | null {
  try {
    const parsed = JSON.parse(content) as unknown;
    return scorePayloadSchema.parse(parsed);
  } catch {
    return null;
  }
}

function historyEntryToResultRow(entry: RatchetHistoryEntry): RatchetResultRow {
  return {
    run_id: entry.run_id,
    source_ref: entry.source_ref,
    base_ref: null,
    prompt_version: '-',
    eval_bundle_version: entry.eval_bundle_version,
    rubric_version: null,
    overall: entry.overall,
    verdict: entry.verdict,
    status: entry.status,
    timestamp: entry.timestamp,
    weakest_dim: entry.weakest_dim,
    note_json: entry.note_json,
  };
}

function statusTone(status: string): 'kept' | 'discarded' | 'other' {
  if (KEPT_STATUSES.has(status)) return 'kept';
  if (status === 'discard' || status === 'crash') return 'discarded';
  return 'other';
}

function statusLabel(status: string, t: TranslateFn): string {
  switch (status) {
    case 'baseline':
      return t('Ratchet.status_baseline');
    case 'keep':
      return t('Ratchet.status_keep');
    case 'keep_final':
      return t('Ratchet.status_keep_final');
    case 'discard':
      return t('Ratchet.status_discard');
    case 'crash':
      return t('Ratchet.status_crash');
    case 'targeted_verify':
      return t('Ratchet.status_targeted_verify');
    case 'phase25_rewrite':
      return t('Ratchet.status_phase25_rewrite');
    case 'non_ratcheted':
      return t('Ratchet.status_non_ratcheted');
    default:
      return status.replace(/_/g, ' ');
  }
}

function noteSummary(row: RatchetResultRow, t: TranslateFn): string {
  if (!row.note_json) return t('Ratchet.note_row_empty');
  try {
    const parsed = JSON.parse(row.note_json) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return t('Ratchet.note_row_available');
    }
    const record = parsed as Record<string, unknown>;
    const phase25Note = readStringField(record, 'phase25_note');
    if (phase25Note) return phase25Note;
    const targetedReason = readStringField(record, 'targeted_reason');
    if (targetedReason) return targetedReason;
    const triggerReason = readStringField(record, 'trigger_reason');
    if (triggerReason) return triggerReason;
    const baseline = readNumberField(record, 'baseline_overall');
    if (baseline != null) return t('Ratchet.note_row_baseline', { score: baseline });
    return t('Ratchet.note_row_available');
  } catch {
    return t('Ratchet.note_row_available');
  }
}

const DIM_HINT_KEYS: Record<string, string> = {
  accuracy: 'Ratchet.dim_accuracy_hint',
  evidence: 'Ratchet.dim_evidence_hint',
  diff_coverage: 'Ratchet.dim_diff_coverage_hint',
  learnability: 'Ratchet.dim_learnability_hint',
  quiz_transfer: 'Ratchet.dim_quiz_transfer_hint',
  spec_alignment: 'Ratchet.dim_spec_alignment_hint',
  conciseness: 'Ratchet.dim_conciseness_hint',
  safety_privacy: 'Ratchet.dim_safety_privacy_hint',
};

const DIM_LABEL_KEYS: Record<string, string> = {
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
  const labelKey = DIM_LABEL_KEYS[dim];
  if (labelKey) return t(labelKey);
  return dim.replace(/_/g, ' ');
}

export default function RatchetPage() {
  const { t } = useTranslation();
  const locale = useLocaleStore((s) => s.locale);
  const [history, setHistory] = useState<RatchetHistoryEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<RatchetTab>('results');
  const [scoreData, setScoreData] = useState<ScorePayload | null>(null);
  const [scoreRunId, setScoreRunId] = useState<string | null>(null);
  const [scoreLoading, setScoreLoading] = useState(false);
  const [specAlignment, setSpecAlignment] = useState<SpecAlignmentResponse | null>(null);
  const [transparency, setTransparency] = useState<RatchetTransparencyResponse | null>(null);
  const [transparencyLoading, setTransparencyLoading] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const loadMoreAbortRef = useRef<AbortController | null>(null);
  const transparencyAbortRef = useRef<AbortController | null>(null);
  const resultRows = transparency?.results.length
    ? transparency.results
    : history.map(historyEntryToResultRow);
  const latestRunId = resultRows[0]?.run_id ?? null;
  const activeScoreData = scoreRunId === latestRunId ? scoreData : null;
  const latestNote = resultRows.map(parseRatchetNote).find((item): item is RatchetNote => item !== null) ?? null;

  const focusTab = useCallback((tab: RatchetTab) => {
    window.requestAnimationFrame(() => {
      document.getElementById(TAB_IDS[tab])?.focus();
    });
  }, []);

  const activateTab = useCallback((tab: RatchetTab) => {
    setActiveTab(tab);
    focusTab(tab);
  }, [focusTab]);

  const handleTabKeyDown = useCallback((
    event: KeyboardEvent<HTMLButtonElement>,
    tab: RatchetTab,
  ) => {
    const currentIndex = RATCHET_TABS.indexOf(tab);
    let nextTab: RatchetTab | null = null;

    if (event.key === 'ArrowRight') {
      nextTab = RATCHET_TABS[(currentIndex + 1) % RATCHET_TABS.length];
    } else if (event.key === 'ArrowLeft') {
      nextTab = RATCHET_TABS[
        (currentIndex - 1 + RATCHET_TABS.length) % RATCHET_TABS.length
      ];
    } else if (event.key === 'Home') {
      nextTab = RATCHET_TABS[0];
    } else if (event.key === 'End') {
      nextTab = RATCHET_TABS[RATCHET_TABS.length - 1];
    }

    if (nextTab) {
      event.preventDefault();
      activateTab(nextTab);
    }
  }, [activateTab]);

  const fetchHistory = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const res = await getRatchetHistory({}, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setHistory(res.history);
      setNextCursor(res.next_cursor ?? null);
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(t('Ratchet.title'));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [t]);

  const loadMoreRef = useRef(0);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loadingMore) return;
    loadMoreAbortRef.current?.abort();
    const controller = new AbortController();
    loadMoreAbortRef.current = controller;
    const gen = ++loadMoreRef.current;
    const cursorSnapshot = nextCursor;
    setLoadingMore(true);
    try {
      const res = await getRatchetHistory({ cursor: cursorSnapshot }, { signal: controller.signal });
      if (controller.signal.aborted || loadMoreRef.current !== gen) return;
      setHistory((prev) => [...prev, ...res.history]);
      setNextCursor(res.next_cursor ?? null);
    } catch {
      // silently fail, user can retry
    } finally {
      if (!controller.signal.aborted && loadMoreRef.current === gen) setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  useEffect(() => {
    void fetchHistory();
    return () => {
      abortRef.current?.abort();
      loadMoreAbortRef.current?.abort();
      transparencyAbortRef.current?.abort();
      loadMoreRef.current += 1;
    };
  }, [fetchHistory]);

  useEffect(() => {
    transparencyAbortRef.current?.abort();
    const controller = new AbortController();
    transparencyAbortRef.current = controller;
    setTransparencyLoading(true);
    getRatchetTransparency({ signal: controller.signal })
      .then((payload) => {
        if (!controller.signal.aborted) setTransparency(payload);
      })
      .catch(() => {
        if (!controller.signal.aborted) setTransparency(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setTransparencyLoading(false);
      });
    return () => controller.abort();
  }, []);

  // Spec alignment summary — surfaced near the page header so users see
  // overall rubric drift without paging through individual run scores.
  useEffect(() => {
    const controller = new AbortController();
    fetchSpecAlignment({ signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setSpecAlignment(data);
      })
      .catch(() => {
        // best-effort metric; leave card hidden on failure
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (activeTab !== 'judge' || !latestRunId || activeScoreData) return;
    const controller = new AbortController();
    const runId = latestRunId;
    setScoreLoading(true);
    getRunScore(runId, { signal: controller.signal })
      .then((envelope) => {
        if (controller.signal.aborted) return;
        setScoreRunId(runId);
        setScoreData(parseScorePayload(envelope.content));
      })
      .catch(() => {})
      .finally(() => {
        if (!controller.signal.aborted) setScoreLoading(false);
      });
    return () => controller.abort();
  }, [activeTab, activeScoreData, latestRunId]);

  if (loading) {
    return (
      <AppShell>
        <div className="ratchet-page" role="status" aria-label={t('A11y.loading')}>
          <div className="ratchet-page__head">
            <div className="ratchet-page__head-left">
              <Skeleton variant="text" width="250px" height="2em" />
              <Skeleton variant="text-short" width="350px" />
            </div>
          </div>
          <Skeleton variant="chart" />
          <SkeletonGroup count={5} variant="row" />
        </div>
      </AppShell>
    );
  }

  if (error) {
    return (
      <AppShell>
        <div className="ratchet-page">
          <div className="ratchet-page__head">
            <div className="ratchet-page__head-left">
              <h1 className="ratchet-page__title">{t('Ratchet.title')}</h1>
            </div>
          </div>
          <div role="alert" className="dashboard__error">
            {t('Error.fetch_failed', { resource: t('Ratchet.title') })}
            <button type="button" className="retry-btn" onClick={() => void fetchHistory()}>
              {t('Error.retry')}
            </button>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="ratchet-page" aria-live="polite">
        {/* Header */}
        <div className="ratchet-page__head">
          <div className="ratchet-page__head-left">
            <div className="review__eyebrow">§ {t('Ratchet.title')}</div>
            <h1 className="ratchet-page__title">{t('Ratchet.title')}</h1>
            <div className="ratchet-page__sub">{t('Ratchet.subtitle')}</div>
          </div>
          <div className="ratchet-page__head-right">
            {specAlignment && (
              <div
                className="ratchet-page__spec-summary"
                aria-label={t('Ratchet.spec_alignment')}
              >
                <span className="ratchet-page__spec-label">
                  {t('Ratchet.spec_alignment')}
                </span>
                <span className="ratchet-page__spec-score">
                  {t('Ratchet.alignment_score')}:{' '}
                  <span className="num">
                    {specAlignment.alignment_score != null
                      ? `${formatScore(specAlignment.alignment_score, locale)}/10`
                      : '-'}
                  </span>
                </span>
                <span className="ratchet-page__spec-trend">
                  {t('Ratchet.recent_trend')}:{' '}
                  {specAlignment.recent_trend
                    ? t(`Ratchet.trend_${specAlignment.recent_trend}`)
                    : '-'}
                </span>
              </div>
            )}
            <button
              type="button"
              className="load-more-btn"
              onClick={() => setExportOpen(true)}
            >
              {t('Export.button')}
            </button>
          </div>
        </div>

        {/*
         * Phase 4G: strict-ratchet transparency plus the latest restricted
         * note_json payload exposed by /api/ratchet/history.
         */}
        <aside className="ratchet-banner" role="note">
          <span className="ratchet-banner__tag">{t('Ratchet.banner_tag')}</span>
          <span className="ratchet-banner__text">{t('Ratchet.banner_text')}</span>
        </aside>

        <RatchetNoteCard entries={resultRows} locale={locale} t={t} />
        {latestNote?.phase25 && <Phase25Readout note={latestNote} locale={locale} t={t} />}

        {/* Chart + Rubric grid — always visible above tabs */}
        <div className="ratchet-page__grid">
          <div className="ratchet-card">
            <div className="ratchet-card__header">
              <h2>{t('Dashboard.ratchet_title')}</h2>
              <span className="ratchet-card__meta">{t('Rubric.overall')}</span>
            </div>
            <div className="ratchet-card__body">
              {resultRows.length >= 2 ? (
                <RatchetChart history={resultRows} />
              ) : (
                <div className="u-muted-sm">
                  {t('Dashboard.ratchet_not_enough')}
                </div>
              )}
            </div>
          </div>

          <div className="ratchet-card">
            <div className="ratchet-card__header">
              <h2>{t('Rubric.weakest_dim')}</h2>
              <span className="ratchet-card__meta">{t('Ratchet.meta_runs', { count: history.length })}</span>
            </div>
            <div className="ratchet-card__body">
              <WeakestDimSummary history={history} t={t} />
            </div>
          </div>
        </div>

        {/* Tab bar — V6 Results/Rubric/Benchmark/Judge */}
        <div
          className="ratchet-tabs"
          role="tablist"
          aria-label={t('Ratchet.title')}
        >
          {RATCHET_TABS.map((tab) => (
            <button
              key={tab}
              id={TAB_IDS[tab]}
              type="button"
              role="tab"
              aria-selected={activeTab === tab}
              aria-controls={TAB_PANEL_IDS[tab]}
              tabIndex={activeTab === tab ? 0 : -1}
              className={`ratchet-tabs__tab${activeTab === tab ? ' ratchet-tabs__tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
              onKeyDown={(event) => handleTabKeyDown(event, tab)}
            >
              {t(TAB_LABEL_KEYS[tab])}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div
          id={TAB_PANEL_IDS.results}
          className="ratchet-card"
          role="tabpanel"
          aria-labelledby={TAB_IDS.results}
          tabIndex={0}
          hidden={activeTab !== 'results'}
        >
          {activeTab === 'results' && (
            <>
            <div className="ratchet-card__header">
              <h2 id="ratchet-run-list-heading">results.tsv</h2>
              <span className="ratchet-card__meta">{t('Ratchet.meta_entries', { count: resultRows.length })}</span>
            </div>
            <div className="ratchet-card__body ratchet-card__body--table u-p-0" tabIndex={0} role="region" aria-labelledby="ratchet-run-list-heading">
              <table className="ratchet-table" aria-label={t('Ratchet.table_label')}>
                <thead>
                  <tr>
                    <th scope="col">{t('Ratchet.col_time')}</th>
                    <th scope="col">{t('Dashboard.col_ref')}</th>
                    <th scope="col">{t('Ratchet.col_score')}</th>
                    <th scope="col">{t('Ratchet.col_verdict')}</th>
                    <th scope="col">{t('Ratchet.col_status')}</th>
                    <th scope="col">{t('Ratchet.col_weakest')}</th>
                    <th scope="col">{t('Ratchet.col_note')}</th>
                  </tr>
                </thead>
                <tbody>
                  {resultRows.length === 0 && (
                    <tr>
                      <td colSpan={7} className="ratchet-table__empty">
                        {t('Ratchet.no_results')}
                      </td>
                    </tr>
                  )}
                  {resultRows.map((entry) => (
                    <tr key={`${entry.run_id}-${entry.timestamp}-${entry.status}`}>
                      <td className="mono">{formatDate(entry.timestamp, locale)}</td>
                      <td className="mono">{entry.source_ref || entry.run_id.slice(0, 8)}</td>
                      <td className="num">{formatScore(entry.overall, locale)}</td>
                      <td>
                        <span className={`verdict-badge verdict-badge--${safeVerdict(entry.verdict)}`}>
                          {safeVerdict(entry.verdict)}
                        </span>
                      </td>
                      <td>
                        <span className={`ratchet-status ratchet-status--${statusTone(entry.status)}`}>
                          {statusLabel(entry.status, t)}
                        </span>
                      </td>
                      <td>{formatDimensionLabel(entry.weakest_dim, t)}</td>
                      <td className="ratchet-note-summary">{noteSummary(entry, t)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!transparency?.results.length && nextCursor && (
              <div className="u-center-action-row">
                <button
                  type="button"
                  className="load-more-btn"
                  onClick={() => { loadMore().catch(() => {}); }}
                  disabled={loadingMore}
                >
                  {loadingMore ? t('Dashboard.loading_more') : t('Ratchet.load_more')}
                </button>
              </div>
            )}
            </>
          )}
        </div>

        <div
          id={TAB_PANEL_IDS.rubric}
          className="ratchet-card"
          role="tabpanel"
          aria-labelledby={TAB_IDS.rubric}
          tabIndex={0}
          hidden={activeTab !== 'rubric'}
        >
          {activeTab === 'rubric' && (
            <>
            <div className="ratchet-card__header">
              <h2>{t('Rubric.weakest_dim')}</h2>
              <span className="ratchet-card__meta">{t('Ratchet.meta_runs', { count: history.length })}</span>
            </div>
            <div className="ratchet-card__body">
              <WeakestDimSummary history={history} t={t} />
            </div>
            </>
          )}
        </div>

        <div
          id={TAB_PANEL_IDS.benchmark}
          className="ratchet-card"
          role="tabpanel"
          aria-labelledby={TAB_IDS.benchmark}
          tabIndex={0}
          hidden={activeTab !== 'benchmark'}
        >
          {activeTab === 'benchmark' && (
            transparencyLoading ? (
              <div className="ratchet-card__body">
                <Skeleton height="200px" />
              </div>
            ) : transparency?.benchmark ? (
              <BenchmarkTransparencyPanel
                benchmark={transparency.benchmark}
                locale={locale}
                t={t}
              />
            ) : (
              <div className="ratchet-card__body">
                <p className="u-muted-sm">{t('Ratchet.tab_benchmark_empty')}</p>
              </div>
            )
          )}
        </div>

        <div
          id={TAB_PANEL_IDS.judge}
          className="ratchet-card"
          role="tabpanel"
          aria-labelledby={TAB_IDS.judge}
          tabIndex={0}
          hidden={activeTab !== 'judge'}
        >
          {activeTab === 'judge' && (
            scoreLoading ? (
              <div className="ratchet-card__body">
                <Skeleton height="200px" />
              </div>
            ) : activeScoreData ? (
              <div className="ratchet-card__body">
                <div className="judge-notes">
                  {activeScoreData.notes.length > 0 && (
                    <div className="judge-note-card">
                      <h3 className="judge-note-card__title">{t('Ratchet.judge_notes_title')}</h3>
                      <ul className="judge-note-card__list">
                        {activeScoreData.notes.map((note, i) => (
                          <li key={i}>{note}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {Object.entries(activeScoreData.dimensions).map(([dim, d]) =>
                    d.reason ? (
                      <div key={dim} className="judge-note-card">
                        <div className="judge-note-card__meta">
                          <span className="judge-note-card__dim">{formatDimensionLabel(dim, t)}</span>
                          <span className="judge-note-card__score">
                            {formatScore(d.score, locale)}/{formatScore(d.max_score, locale)}
                          </span>
                        </div>
                        <p className="judge-note-card__reason">{d.reason}</p>
                      </div>
                    ) : null
                  )}
                </div>
              </div>
            ) : (
              <div className="ratchet-card__body">
                <p className="u-muted-sm">{t('Ratchet.tab_judge_empty')}</p>
              </div>
            )
          )}
        </div>

        <div
          id={TAB_PANEL_IDS.improve}
          className="ratchet-card"
          role="tabpanel"
          aria-labelledby={TAB_IDS.improve}
          tabIndex={0}
          hidden={activeTab !== 'improve'}
        >
          {activeTab === 'improve' && (
            <Suspense fallback={<div className="ratchet-card__body"><Skeleton height="200px" /></div>}>
              <ImprovePreview />
            </Suspense>
          )}
        </div>

        <Suspense fallback={null}>
          <GraphifyCard compact />
        </Suspense>
      </div>
      <ExportModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        runId={latestRunId ?? undefined}
      />
    </AppShell>
  );
}

function RatchetNoteCard({
  entries,
  locale,
  t,
}: {
  entries: RatchetNoteSource[];
  locale: string;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const note = entries.map(parseRatchetNote).find((item): item is RatchetNote => item !== null);
  if (!note) {
    return (
      <section className="ratchet-note-card" aria-label={t('Ratchet.note_title')}>
        <div>
          <span className="ratchet-note-card__tag">{t('Ratchet.note_empty_tag')}</span>
          <h2>{t('Ratchet.note_title')}</h2>
          <p>{t('Ratchet.note_empty')}</p>
        </div>
      </section>
    );
  }

  const scoreDelta =
    note.targetedBaselineScore != null && note.targetedCandidateScore != null
      ? note.targetedCandidateScore - note.targetedBaselineScore
      : null;

  return (
    <section className="ratchet-note-card" aria-label={t('Ratchet.note_title')}>
      <div>
        <span className="ratchet-note-card__tag">
          {note.phase25 ? t('Ratchet.note_phase25_tag') : t('Ratchet.note_payload_tag')}
        </span>
        <h2>{t('Ratchet.note_title')}</h2>
        <p>{note.phase25Note ?? note.triggerReason ?? t('Ratchet.note_payload_available')}</p>
      </div>
      <dl className="ratchet-note-card__facts">
        <div>
          <dt>{t('Ratchet.note_run')}</dt>
          <dd className="mono">{note.runId.slice(0, 8)}</dd>
        </div>
        {note.targetDimension && (
          <div>
            <dt>{t('Ratchet.note_target')}</dt>
            <dd>{note.targetDimension}</dd>
          </div>
        )}
        {scoreDelta != null && (
          <div>
            <dt>{t('Ratchet.note_delta')}</dt>
            <dd className="num">
              {scoreDelta >= 0 ? '+' : ''}{formatScore(scoreDelta, locale)}
            </dd>
          </div>
        )}
        {note.targetedPassed != null && (
          <div>
            <dt>{t('Ratchet.note_targeted')}</dt>
            <dd>{note.targetedPassed ? t('Ratchet.note_passed') : t('Ratchet.note_failed')}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}

function Phase25Readout({
  note,
  locale,
  t,
}: {
  note: RatchetNote;
  locale: string;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const scoreDelta =
    note.targetedBaselineScore != null && note.targetedCandidateScore != null
      ? note.targetedCandidateScore - note.targetedBaselineScore
      : null;
  return (
    <section className="phase25-readout">
      <div className="ratchet-card__header">
        <h2>{t('Ratchet.phase25_title')}</h2>
        <span className="ratchet-card__meta">
          {note.triggerReason ?? t('Ratchet.phase25_reason_unknown')}
        </span>
      </div>
      <div className="ratchet-card__body phase25-readout__body">
        <pre className="code-block phase25-readout__code">
{`PHASE25: ${note.triggerReason ?? 'available'}
target_dimension=${note.targetDimension ?? '-'}
targeted_gate=${note.targetedPassed == null ? '-' : note.targetedPassed ? 'passed' : 'failed'}
score_delta=${scoreDelta == null ? '-' : `${scoreDelta >= 0 ? '+' : ''}${formatScore(scoreDelta, locale)}`}`}
        </pre>
        <dl className="phase25-readout__facts">
          <div>
            <dt>{t('Ratchet.phase25_target')}</dt>
            <dd>{note.targetDimension ?? '-'}</dd>
          </div>
          <div>
            <dt>{t('Ratchet.note_targeted')}</dt>
            <dd>{note.targetedPassed == null ? '-' : note.targetedPassed ? t('Ratchet.note_passed') : t('Ratchet.note_failed')}</dd>
          </div>
          <div>
            <dt>{t('Ratchet.note_delta')}</dt>
            <dd className="num">
              {scoreDelta == null
                ? '-'
                : `${scoreDelta >= 0 ? '+' : ''}${formatScore(scoreDelta, locale)}`}
            </dd>
          </div>
        </dl>
      </div>
    </section>
  );
}

function BenchmarkTransparencyPanel({
  benchmark,
  locale,
  t,
}: {
  benchmark: RatchetTransparencyResponse['benchmark'];
  locale: string;
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const manifest = benchmark.manifest;
  const report = benchmark.report;
  const warningText = benchmark.warnings
    .map((warning) => t(`Ratchet.${warning}`))
    .join(' · ');
  return (
    <div className="ratchet-card__body benchmark-transparency">
      {warningText && (
        <div className="demo-banner benchmark-transparency__warning">
          <span className="demo-tag">{t('Ratchet.benchmark_warning_tag')}</span>
          <span>{warningText}</span>
        </div>
      )}

      <div className="benchmark-grid">
        <BenchmarkMetric
          label={t('Ratchet.benchmark_suite')}
          value={manifest?.suite_id ?? report?.suite_id ?? '-'}
          detail={manifest?.visibility ? t('Ratchet.benchmark_visibility', { visibility: manifest.visibility }) : undefined}
        />
        <BenchmarkMetric
          label={t('Ratchet.benchmark_entries')}
          value={manifest ? String(manifest.eval_entry_count) : '-'}
          detail={manifest ? t('Ratchet.benchmark_entries_detail', {
            integration: manifest.integration_entry_count,
            degraded: manifest.degraded_entry_count,
          }) : undefined}
        />
        <BenchmarkMetric
          label={t('Ratchet.benchmark_languages')}
          value={manifest ? String(manifest.language_count) : '-'}
          detail={manifest ? t('Ratchet.benchmark_groups', { count: manifest.group_count }) : undefined}
        />
        <BenchmarkMetric
          label={t('Ratchet.benchmark_mean_score')}
          value={report?.mean_score != null ? formatScore(report.mean_score, locale) : '-'}
          detail={report?.comparable_entry_count != null ? t('Ratchet.benchmark_comparable', {
            comparable: report.comparable_entry_count,
            excluded: report.excluded_degraded_count ?? 0,
          }) : undefined}
        />
        <BenchmarkMetric
          label={t('Ratchet.benchmark_claim_rate')}
          value={report?.claim_verification_rate != null
            ? `${formatScore(report.claim_verification_rate * 100, locale, 1)}%`
            : '-'}
          detail={report?.eval_bundle_version ?? undefined}
        />
        <BenchmarkMetric
          label={t('Ratchet.benchmark_digest')}
          value={(report?.suite_digest ?? manifest?.suite_digest ?? '-').slice(0, 12)}
          detail={t('Ratchet.benchmark_digest_detail')}
        />
      </div>

      {report?.entries.length ? (
        <>
          <hr className="rule" />
          <div className="benchmark-entry-list" aria-label={t('Ratchet.benchmark_entries_label')}>
            {report.entries.map((entry) => (
              <div key={`${entry.id ?? 'entry'}-${entry.group ?? ''}`} className="benchmark-entry-list__row">
                <span className="mono">{entry.id ?? '-'}</span>
                <span>{entry.language ?? '-'}</span>
                <span className={`ratchet-status ratchet-status--${entry.degraded ? 'other' : 'kept'}`}>
                  {entry.degraded ? t('Ratchet.benchmark_degraded') : t('Ratchet.benchmark_comparable_short')}
                </span>
                <span className="num">
                  {entry.overall != null ? formatScore(entry.overall, locale) : '-'}
                </span>
                <span>{entry.weakest_dim ? formatDimensionLabel(entry.weakest_dim, t) : '-'}</span>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

function BenchmarkMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="benchmark-card">
      <div className="eyebrow">{label}</div>
      <div className="benchmark-card__value">{value}</div>
      {detail && <div className="benchmark-card__delta">{detail}</div>}
    </div>
  );
}

function WeakestDimSummary({ history, t }: { history: RatchetHistoryEntry[]; t: (key: string, params?: Record<string, string | number>) => string }) {
  const counts: Record<string, number> = {};
  for (const e of history) {
    if (e.weakest_dim) counts[e.weakest_dim] = (counts[e.weakest_dim] ?? 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = sorted[0]?.[1] ?? 1;

  if (sorted.length === 0) {
    return <div className="u-muted-sm">{t('Ratchet.no_dimension_data')}</div>;
  }

  return (
    <div className="mastery-grid">
      {sorted.slice(0, 8).map(([dim, count]) => (
        <div key={dim} className="u-display-contents">
          <div>
            {formatDimensionLabel(dim, t)}
            {DIM_HINT_KEYS[dim] && <InfoHint label={t(DIM_HINT_KEYS[dim])} />}
          </div>
          <div className="mastery-bar">
            <span
              className="mastery-bar__fill"
              style={{
                width: `${(count / max) * 100}%`,
                background: count === max ? 'var(--danger)' : count > max * 0.5 ? 'var(--warning)' : 'var(--accent)',
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
