import { useCallback, useEffect, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import RatchetChart from '../components/RatchetChart';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import { getRatchetHistory } from '../api/runs';
import { useTranslation } from '../i18n/useTranslation';
import { useLocaleStore } from '../state/locale-store';
import type { RatchetHistoryEntry } from '../api/types';
import { safeVerdict } from '../utils/verdict';
import '../components/Ratchet.css';

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

export default function RatchetPage() {
  const { t } = useTranslation();
  const locale = useLocaleStore((s) => s.locale);
  const [history, setHistory] = useState<RatchetHistoryEntry[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
    const gen = ++loadMoreRef.current;
    const cursorSnapshot = nextCursor;
    setLoadingMore(true);
    try {
      const res = await getRatchetHistory({ cursor: cursorSnapshot });
      if (loadMoreRef.current !== gen) return;
      setHistory((prev) => [...prev, ...res.history]);
      setNextCursor(res.next_cursor ?? null);
    } catch {
      // silently fail, user can retry
    } finally {
      setLoadingMore(false);
    }
  }, [nextCursor, loadingMore]);

  useEffect(() => {
    void fetchHistory();
    return () => abortRef.current?.abort();
  }, [fetchHistory]);

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
      <div className="ratchet-page">
        {/* Header */}
        <div className="ratchet-page__head">
          <div className="ratchet-page__head-left">
            <div className="review__eyebrow">§ {t('Ratchet.title')}</div>
            <h1 className="ratchet-page__title">{t('Ratchet.title')}</h1>
            <div className="ratchet-page__sub">{t('Ratchet.subtitle')}</div>
          </div>
        </div>

        {/*
         * Phase 4G: Strict-ratchet transparency banner.
         * Mirrors V6 (AhaDiff Warm v6.html L1562 demo-banner +
         * L1967 strict-ratchet pull-quote). Surfaces the rule that lower
         * scores are dropped so users can read the table without thinking
         * the missing entries are bugs. Phase 5C will swap demo copy for
         * real benchmark transparency once metrics ship.
         */}
        <aside className="ratchet-banner" role="note">
          <span className="ratchet-banner__tag">{t('Ratchet.banner_tag')}</span>
          <span className="ratchet-banner__text">{t('Ratchet.banner_text')}</span>
        </aside>

        {/* Chart + Rubric grid */}
        <div className="ratchet-page__grid">
          <div className="ratchet-card">
            <div className="ratchet-card__header">
              <h2>{t('Dashboard.ratchet_title')}</h2>
              <span className="ratchet-card__meta">{t('Rubric.overall')}</span>
            </div>
            <div className="ratchet-card__body">
              {history.length >= 2 ? (
                <RatchetChart history={history} />
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

        {/* Results table */}
        <div className="ratchet-card">
          <div className="ratchet-card__header">
            <h2>{t('Dashboard.run_list_title')}</h2>
            <span className="ratchet-card__meta">{t('Ratchet.meta_entries', { count: history.length })}</span>
          </div>
          <div className="ratchet-card__body ratchet-card__body--table u-p-0">
            <table className="ratchet-table" aria-label={t('Ratchet.title')}>
              <thead>
                <tr>
                  <th scope="col">{t('Dashboard.col_ref')}</th>
                  <th scope="col">{t('Ratchet.col_score')}</th>
                  <th scope="col">{t('Ratchet.col_verdict')}</th>
                  <th scope="col">{t('Ratchet.col_weakest')}</th>
                  <th scope="col">{t('Ratchet.col_date')}</th>
                </tr>
              </thead>
              <tbody>
                {history.map((entry) => (
                  <tr key={`${entry.run_id}-${entry.timestamp}`}>
                    <td className="mono">{entry.source_ref || entry.run_id.slice(0, 8)}</td>
                    <td className="num">{entry.overall}</td>
                    <td>
                      <span className={`verdict-badge verdict-badge--${safeVerdict(entry.verdict)}`}>
                        {safeVerdict(entry.verdict)}
                      </span>
                    </td>
                    <td>{entry.weakest_dim || '-'}</td>
                    <td className="mono">{formatDate(entry.timestamp, locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {nextCursor && (
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
        </div>
      </div>
    </AppShell>
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
          <div>{dim}</div>
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
