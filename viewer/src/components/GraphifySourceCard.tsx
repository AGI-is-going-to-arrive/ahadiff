import { useCallback, useEffect, useRef, useState, type JSX, type ReactNode } from 'react';
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
  status: GraphStatusResponse | null;
  className?: string;
  stable?: boolean;
  error?: boolean;
}

function SourceCardFrame({ className, badge, children, loading = false }: {
  className: string;
  badge: ReactNode;
  children: ReactNode;
  loading?: boolean;
}): JSX.Element {
  const { t } = useTranslation();
  return (
    <div
      className={className}
      role="region"
      aria-label={t('Graph.source_title')}
      aria-busy={loading || undefined}
    >
      <div className="graphify-card__header">
        <span className="graphify-card__icon" aria-hidden="true">◈</span>
        <strong className="graphify-card__title">{t('Graph.source_title')}</strong>
        {badge}
      </div>
      <div className="graphify-card__body">{children}</div>
    </div>
  );
}

export default function GraphifySourceCard({
  status,
  className,
  stable = false,
  error = false,
}: GraphifySourceCardProps): JSX.Element {
  const { t } = useTranslation();
  const loading = !status && !error;
  const disabled = status?.enabled === false;
  const freshness = disabled ? 'disabled' : status?.freshness ?? 'unavailable';
  const tone = loading ? 'muted' : FRESHNESS_TONE[freshness] ?? 'muted';
  const freshnessKey = loading ? 'A11y.loading' : FRESHNESS_LABEL_KEY[freshness] ?? 'Graph.freshness_unavailable';
  const rootClass = ['graphify-card', stable ? 'graphify-card--stable' : '', className]
    .filter(Boolean).join(' ');
  const labels = [
    'Graph.row_source', 'Graph.row_graph', 'Graph.row_imported',
    'Graph.row_parser', 'Graph.row_sha256',
  ] as const;

  return (
    <SourceCardFrame
      className={rootClass}
      loading={loading}
      badge={<span className={`graphify-badge graphify-badge--${tone}`}>{t(freshnessKey)}</span>}
    >
      {loading ? labels.map((label, index) => (
        <div className="graphify-card__row" key={label} aria-hidden="true">
          <span className="graphify-card__row-label">{t(label)}</span>
          {index < 2 && <span className="graphify-card__row-ok">·</span>}
          <span className="graphify-card__skeleton-value" />
        </div>
      )) : !status || disabled ? (
        <p className="graphify-card__empty">
          {t(disabled ? 'Graph.empty_disabled' : 'Graph.empty_unavailable')}
        </p>
      ) : !status.has_graph ? (
        <p className="graphify-card__empty">
          {t(status.source_exists ? 'Graph.empty_graph' : 'Graph.empty_source_missing')}
        </p>
      ) : (
        <>
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
            <span>{t('Graph.node_count', { count: status.node_count })}{t('Graph.sep')}{t('Graph.edge_count', { count: status.edge_count })}</span>
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
        </>
      )}
    </SourceCardFrame>
  );
}
