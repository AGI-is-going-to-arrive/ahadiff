import { useEffect } from 'react';
import { useGraphStore } from '../state/graph-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import type { FreshnessProjection } from '../api/types';
import './GraphifyCard.css';

const FRESHNESS_TONE: Record<FreshnessProjection, string> = {
  fresh: 'success',
  stale: 'warning',
  unavailable: 'muted',
  disabled: 'muted',
};

const FRESHNESS_LABEL_KEY: Record<FreshnessProjection, MessageKey> = {
  fresh: 'Graph.freshness_fresh',
  stale: 'Graph.freshness_stale',
  unavailable: 'Graph.freshness_unavailable',
  disabled: 'Graph.freshness_disabled',
};

export default function GraphifyCard({ compact }: { compact?: boolean }) {
  const { t } = useTranslation();
  const status = useGraphStore((s) => s.status);
  const loading = useGraphStore((s) => s.loading);
  const error = useGraphStore((s) => s.error);
  const fetchStatus = useGraphStore((s) => s.fetch);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  if (!status) {
    if (error) return null;
    if (loading) {
      const placeholderClassName = [
        'graphify-card',
        compact ? 'graphify-card--compact' : '',
        'graphify-card--placeholder',
      ].filter(Boolean).join(' ');
      return <div className={placeholderClassName} aria-hidden="true" />;
    }
    return null;
  }

  if (!status.enabled) return null;

  const freshness = status.freshness ?? 'unavailable';
  const tone = FRESHNESS_TONE[freshness] ?? 'muted';
  const freshnessKey = FRESHNESS_LABEL_KEY[freshness] ?? 'Graph.freshness_unavailable';
  const nodeCount = t('Graph.node_count', { count: status.node_count });
  const edgeCount = t('Graph.edge_count', { count: status.edge_count });

  if (compact) {
    return (
      <div className="graphify-card graphify-card--compact">
        <span className="graphify-card__label">{t('Graph.source_title')}</span>
        <span className={`graphify-badge graphify-badge--${tone}`}>
          {t(freshnessKey)}
        </span>
        {status.has_graph && (
          <span className="graphify-card__counts mono">
            {nodeCount}{t('Graph.sep')}{edgeCount}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="graphify-card" role="region" aria-label={t('Graph.source_title')}>
      <div className="graphify-card__header">
        <h3 className="graphify-card__title">{t('Graph.source_title')}</h3>
        <span className={`graphify-badge graphify-badge--${tone}`}>
          {t(freshnessKey)}
        </span>
      </div>
      {status.has_graph ? (
        <div className="graphify-card__body">
          <div className="graphify-card__stats mono">
            <span>{nodeCount}</span>
            <span>{edgeCount}</span>
          </div>
          {status.source_path && (
            <p className="graphify-card__source mono">{status.source_path}</p>
          )}
        </div>
      ) : (
        <p className="graphify-card__empty">
          {t(status.source_exists ? 'Graph.empty_graph' : 'Graph.empty_source_missing')}
        </p>
      )}
    </div>
  );
}
