import { useCallback, useEffect } from 'react';
import { useConceptsStore } from '../state/concepts-store';
import { useTranslation } from '../i18n/useTranslation';
import './ConceptLedger.css';

const MAX_CHIPS = 3;

interface ConceptLedgerProps {
  runFilter?: string;
}

export default function ConceptLedger({ runFilter }: ConceptLedgerProps) {
  const { t } = useTranslation();
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

  useEffect(() => {
    void loadLedger(runFilter);
  }, [loadLedger, runFilter]);

  const handleClearFilter = useCallback(() => {
    setRunFilter(undefined);
  }, [setRunFilter]);

  const handleRunClick = useCallback(
    (run: string) => {
      setRunFilter(run);
    },
    [setRunFilter],
  );

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
          {entries.map((entry) => (
            <tr key={entry.term_key}>
              <td>
                <div className="concept-ledger__name">{entry.display_name || entry.concept}</div>
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
                        {f.split('/').pop() ?? f}
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
        {entries.length} / {totalCount}
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
