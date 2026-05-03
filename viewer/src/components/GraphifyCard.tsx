import { useEffect } from 'react';
import { useGraphStore } from '../state/graph-store';
import { useTranslation } from '../i18n/useTranslation';
import { FRESHNESS_TONE, FRESHNESS_LABEL_KEY } from './freshness-utils';
import GraphifySourceCard from './GraphifySourceCard';
export { CopyButton } from './GraphifySourceCard';
import './GraphifyCard.css';

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

  return <GraphifySourceCard status={status} />;
}
