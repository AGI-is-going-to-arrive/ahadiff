import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useConceptsStore } from '../state/concepts-store';
import { useTranslation } from '../i18n/useTranslation';
import type { ConceptHealthStatus } from '../api/types';
import HealthBadge from './HealthBadge';
import './ConceptLedger.css';

const MAX_CHIPS = 3;

type HealthFilter = 'all' | ConceptHealthStatus;
const HEALTH_FILTER_OPTIONS: HealthFilter[] = [
  'all',
  'healthy',
  'orphan',
  'stale',
  'contradicted',
  'dismissed',
];
const HEALTH_FILTER_LABEL_KEYS: Record<HealthFilter, string> = {
  all: 'Concept.health_filter_all',
  healthy: 'Concept.health_healthy',
  orphan: 'Concept.health_orphan',
  stale: 'Concept.health_stale',
  contradicted: 'Concept.health_contradicted',
  dismissed: 'Concept.health_dismissed',
};

interface ConceptLedgerProps {
  runFilter?: string;
  onRunFilterChange?: (run: string | undefined) => void;
  focusConcept?: string;
  graphifyAvailable?: boolean;
}

function normalizeConceptMatch(value: string | undefined): string {
  return (value ?? '').trim().toLocaleLowerCase();
}

export function conceptMatchesFocus(
  entry: { concept: string; display_name: string; term_key: string },
  focusConcept: string,
): boolean {
  const needle = normalizeConceptMatch(focusConcept);
  if (!needle) return false;
  const candidates = [entry.concept, entry.display_name, entry.term_key]
    .map(normalizeConceptMatch)
    .filter(Boolean);
  if (candidates.some((candidate) => candidate === needle)) return true;
  if (candidates.some((candidate) => candidate.includes(needle))) return true;
  return candidates.some((candidate) => candidate.length >= 2 && needle.includes(candidate));
}

function updateHashRunFilter(run: string | undefined) {
  const [hashPath, rawQuery = ''] = window.location.hash.split('?');
  const params = new URLSearchParams(rawQuery);
  if (run) params.set('run', run);
  else params.delete('run');
  const nextQuery = params.toString();
  const nextHash = `${hashPath || '#/concepts'}${nextQuery ? `?${nextQuery}` : ''}`;
  window.history.replaceState(
    null,
    '',
    `${window.location.pathname}${window.location.search}${nextHash}`,
  );
}

export function fileRefBasename(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '');
  if (!trimmed) return path;
  const slashIndex = trimmed.lastIndexOf('/');
  const backslashIndex = trimmed.lastIndexOf('\\');
  const separatorIndex = Math.max(slashIndex, backslashIndex);
  return separatorIndex >= 0 ? trimmed.slice(separatorIndex + 1) : trimmed;
}

export function shouldUseSmoothScroll(): boolean {
  if (typeof window === 'undefined') return false;
  return !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
}

export default function ConceptLedger({
  runFilter,
  onRunFilterChange,
  focusConcept,
  graphifyAvailable = false,
}: ConceptLedgerProps) {
  const { t } = useTranslation();
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  const entries = useConceptsStore((s) => s.entries);
  const loading = useConceptsStore((s) => s.loading);
  const loadingMore = useConceptsStore((s) => s.loadingMore);
  const error = useConceptsStore((s) => s.error);
  const hasMore = useConceptsStore((s) => s.hasMore);
  const totalCount = useConceptsStore((s) => s.totalCount);
  const activeFilter = useConceptsStore((s) => s.runFilter);
  const loadLedger = useConceptsStore((s) => s.loadLedger);
  const loadMoreLedger = useConceptsStore((s) => s.loadMoreLedger);
  const setRunFilter = useConceptsStore((s) => s.setRunFilter);

  const [healthFilter, setHealthFilter] = useState<HealthFilter>('all');
  const [focusedTermKey, setFocusedTermKey] = useState<string | null>(null);

  useEffect(() => {
    void loadLedger(runFilter);
  }, [loadLedger, runFilter]);

  const filteredEntries = useMemo(() => {
    if (healthFilter === 'all') return entries;
    return entries.filter((entry) => entry.health_status === healthFilter);
  }, [entries, healthFilter]);

  const healthSummary = useMemo(() => {
    const counts: Record<ConceptHealthStatus, number> = {
      healthy: 0,
      orphan: 0,
      stale: 0,
      contradicted: 0,
      dismissed: 0,
    };
    for (const entry of entries) {
      if (entry.health_status) counts[entry.health_status] += 1;
    }
    return counts;
  }, [entries]);

  const hasAnyHealth = useMemo(
    () => entries.some((entry) => Boolean(entry.health_status)),
    [entries],
  );

  const handleClearFilter = useCallback(() => {
    if (onRunFilterChange) {
      onRunFilterChange(undefined);
      return;
    }
    setRunFilter(undefined);
    updateHashRunFilter(undefined);
  }, [onRunFilterChange, setRunFilter]);

  const handleRunClick = useCallback(
    (run: string) => {
      if (onRunFilterChange) {
        onRunFilterChange(run);
        return;
      }
      setRunFilter(run);
      updateHashRunFilter(run);
    },
    [onRunFilterChange, setRunFilter],
  );

  useEffect(() => {
    if (!focusConcept || loading || error || filteredEntries.length === 0) return undefined;
    const match = filteredEntries.find((entry) => conceptMatchesFocus(entry, focusConcept));
    if (!match) return undefined;
    const row = rowRefs.current.get(match.term_key);
    if (!row) return undefined;

    let clearTimer: number | undefined;
    let applyFrame: number | undefined;
    const frame = window.requestAnimationFrame(() => {
      row.scrollIntoView({
        behavior: shouldUseSmoothScroll() ? 'smooth' : 'auto',
        block: 'center',
      });
      setFocusedTermKey(match.term_key);
      applyFrame = window.requestAnimationFrame(() => row.focus({ preventScroll: true }));
      clearTimer = window.setTimeout(() => {
        setFocusedTermKey((current) => (current === match.term_key ? null : current));
      }, 1800);
    });

    return () => {
      window.cancelAnimationFrame(frame);
      if (applyFrame != null) window.cancelAnimationFrame(applyFrame);
      if (clearTimer != null) window.clearTimeout(clearTimer);
    };
  }, [error, filteredEntries, focusConcept, loading]);

  if (loading) {
    return (
      <div role="status" aria-live="polite" className="concepts-page__loading">
        <span className="loading-spinner" />
        {t('Serve.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="concepts-page__error">
        {t('Error.fetch_failed', { resource: t('Concept.ledger_title') })}
        <button
          type="button"
          className="retry-btn"
          onClick={() => void loadLedger(activeFilter)}
        >
          {t('Error.retry')}
        </button>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="concept-ledger__empty">
        <p className="concept-ledger__empty-title">{t('Concept.ledger_empty')}</p>
        <p>{t('Concept.empty')}</p>
      </div>
    );
  }

  return (
    <div className="concept-ledger">
      {activeFilter && (
        <div className="concept-ledger__filter-bar">
          <span className="concept-ledger__filter-pill">
            {t('Concept.ledger_filter_run')}: {activeFilter}
            <button
              type="button"
              className="concept-ledger__filter-clear"
              onClick={handleClearFilter}
              aria-label={t('Concept.ledger_clear_filter')}
            >
              ×
            </button>
          </span>
        </div>
      )}

      {hasAnyHealth && (
        <div
          className="concept-ledger__health-filter"
          role="group"
          aria-label={t('Concept.health_filter_label')}
        >
          <span className="concept-ledger__health-filter-label">
            {t('Concept.health_filter_label')}
          </span>
          <div className="concept-ledger__health-filter-chips">
            {HEALTH_FILTER_OPTIONS.map((option) => {
              const isActive = healthFilter === option;
              const count =
                option === 'all' ? entries.length : healthSummary[option];
              return (
                <button
                  key={option}
                  type="button"
                  className={`concept-ledger__health-chip${
                    isActive ? ' concept-ledger__health-chip--active' : ''
                  }`}
                  onClick={() => setHealthFilter(option)}
                  aria-pressed={isActive}
                >
                  {t(HEALTH_FILTER_LABEL_KEYS[option])}
                  <span className="concept-ledger__health-chip-count">{count}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <table className="concept-ledger__table">
        <thead>
          <tr>
            <th scope="col">{t('Concept.ledger_col_concept')}</th>
            <th scope="col">{t('Concept.ledger_col_runs')}</th>
            <th scope="col">{t('Concept.ledger_col_files')}</th>
            <th scope="col" className="concept-ledger__count">
              {t('Concept.ledger_col_claims')}
            </th>
          </tr>
        </thead>
        <tbody>
          {filteredEntries.map((entry) => (
            <tr
              key={entry.term_key}
              ref={(node) => {
                if (node) rowRefs.current.set(entry.term_key, node);
                else rowRefs.current.delete(entry.term_key);
              }}
              className={
                focusedTermKey === entry.term_key
                  ? 'concept-ledger__row--focused'
                  : undefined
              }
              tabIndex={focusedTermKey === entry.term_key ? -1 : undefined}
              aria-current={focusedTermKey === entry.term_key ? 'true' : undefined}
              data-concept-term-key={entry.term_key}
            >
              <td>
                <div className="concept-ledger__name">
                  <span>{entry.display_name || entry.concept}</span>
                  <HealthBadge status={entry.health_status} />
                  {graphifyAvailable && (
                    <a
                      className="concept-ledger__graph-link"
                      href={`#/concepts?tab=graph&focus=${encodeURIComponent(entry.term_key)}`}
                    >
                      {t('Concept.ledger_view_in_graph')}
                    </a>
                  )}
                </div>
                {entry.display_name && entry.display_name !== entry.concept && (
                  <div className="concept-ledger__term-key">{entry.concept}</div>
                )}
              </td>
              <td>
                <ul className="concept-ledger__chip-list">
                  {entry.updated_by_runs.slice(0, MAX_CHIPS).map((run) => (
                    <li key={run}>
                      <button
                        type="button"
                        className="concept-ledger__chip concept-ledger__chip--run"
                        onClick={() => handleRunClick(run)}
                        title={run}
                      >
                        {run.length > 12 ? `${run.slice(0, 12)}…` : run}
                      </button>
                    </li>
                  ))}
                  {entry.updated_by_runs.length > MAX_CHIPS && (
                    <li>
                      <span className="concept-ledger__chip concept-ledger__chip--more">
                        +{entry.updated_by_runs.length - MAX_CHIPS}
                      </span>
                    </li>
                  )}
                </ul>
              </td>
              <td>
                <ul className="concept-ledger__chip-list">
                  {entry.file_refs.slice(0, MAX_CHIPS).map((f) => (
                    <li key={f}>
                      <span className="concept-ledger__chip" title={f}>
                        {fileRefBasename(f)}
                      </span>
                    </li>
                  ))}
                  {entry.file_refs.length > MAX_CHIPS && (
                    <li>
                      <span className="concept-ledger__chip concept-ledger__chip--more">
                        +{entry.file_refs.length - MAX_CHIPS}
                      </span>
                    </li>
                  )}
                </ul>
              </td>
              <td className="concept-ledger__count">{entry.related_claims.length}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="concept-ledger__total">
        {filteredEntries.length} / {totalCount}
      </div>

      {hasMore && (
        <button
          type="button"
          className="concept-ledger__load-more"
          onClick={() => void loadMoreLedger()}
          disabled={loadingMore}
        >
          {loadingMore ? t('Serve.loading') : t('Concept.ledger_load_more')}
        </button>
      )}
    </div>
  );
}
