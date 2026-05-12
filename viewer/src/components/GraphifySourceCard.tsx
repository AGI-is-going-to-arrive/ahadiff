import { useCallback, useEffect, useRef, useState } from 'react';
import type { GraphStatusResponse } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import { copyToClipboard } from '../utils/clipboard';
import { FRESHNESS_TONE, FRESHNESS_LABEL_KEY } from './freshness-utils';
import './GraphifyCard.css';

export function CopyButton({ text, label }: { text: string; label: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const handleCopy = useCallback(() => {
    void copyToClipboard(text).then((ok) => {
      if (!ok) return;
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
      setCopied(true);
      resetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
        resetTimerRef.current = null;
      }, 1400);
    });
  }, [text]);
  return (
    <button
      type="button"
      className={`graphify-card__copy-btn${copied ? ' is-copied' : ''}`}
      aria-label={copied ? t('Graph.sha_copied') : label}
      aria-live="polite"
      onClick={handleCopy}
    >
      {copied ? '✓' : t('Graph.copy')}
    </button>
  );
}

interface GraphifySourceCardProps {
  status: GraphStatusResponse;
  className?: string;
}

export default function GraphifySourceCard({ status, className }: GraphifySourceCardProps) {
  const { t } = useTranslation();

  const freshness = status.freshness ?? 'unavailable';
  const tone = FRESHNESS_TONE[freshness] ?? 'muted';
  const freshnessKey = FRESHNESS_LABEL_KEY[freshness] ?? 'Graph.freshness_unavailable';
  const nodeCount = t('Graph.node_count', { count: status.node_count });
  const edgeCount = t('Graph.edge_count', { count: status.edge_count });
  const rootClass = className ? `graphify-card ${className}` : 'graphify-card';

  if (!status.has_graph) {
    return (
      <div className={rootClass} role="region" aria-label={t('Graph.source_title')}>
        <div className="graphify-card__header">
          <span className="graphify-card__icon" aria-hidden="true">◈</span>
          <strong className="graphify-card__title">{t('Graph.source_title')}</strong>
          <span className={`graphify-badge graphify-badge--${tone}`}>
            {t(freshnessKey)}
          </span>
        </div>
        <p className="graphify-card__empty">
          {t(status.source_exists ? 'Graph.empty_graph' : 'Graph.empty_source_missing')}
        </p>
      </div>
    );
  }

  return (
    <div className={rootClass} role="region" aria-label={t('Graph.source_title')}>
      <div className="graphify-card__header">
        <span className="graphify-card__icon" aria-hidden="true">◈</span>
        <strong className="graphify-card__title">{t('Graph.source_title')}</strong>
        <span className={`graphify-badge graphify-badge--${tone}`}>
          {t(freshnessKey)}
        </span>
      </div>
      <div className="graphify-card__body">
        {status.source_path && (
          <div className="graphify-card__row">
            <span className="graphify-card__row-label">{t('Graph.row_source')}</span>
            <span className="graphify-card__row-ok" aria-hidden="true">✓</span>
            <span>{status.source_path}</span>
          </div>
        )}
        <div className="graphify-card__row">
          <span className="graphify-card__row-label">{t('Graph.row_graph')}</span>
          <span className="graphify-card__row-ok" aria-hidden="true">✓</span>
          <span>{nodeCount}{t('Graph.sep')}{edgeCount}</span>
        </div>
        {status.provenance && (
          <>
            <div className="graphify-card__row">
              <span className="graphify-card__row-label">{t('Graph.row_imported')}</span>
              <span>{status.provenance.import_time}</span>
            </div>
            <div className="graphify-card__row">
              <span className="graphify-card__row-label">{t('Graph.row_parser')}</span>
              <span>v{status.provenance.parser_version}</span>
            </div>
            <div className="graphify-card__row">
              <span className="graphify-card__row-label">{t('Graph.row_sha256')}</span>
              <span className="graphify-card__sha-group">
                <code>{status.provenance.graph_sha256.slice(0, 12)}…</code>
                <CopyButton text={status.provenance.graph_sha256} label={t('Graph.sha_copy')} />
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
