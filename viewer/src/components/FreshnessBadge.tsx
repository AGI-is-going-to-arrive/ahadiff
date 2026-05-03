import { useTranslation } from '../i18n/useTranslation';
import type { FreshnessProjection } from '../api/types';
import { FRESHNESS_TONE, FRESHNESS_LABEL_KEY } from './freshness-utils';
import './GraphifyCard.css';

const VALID_PROJECTIONS: ReadonlySet<string> = new Set([
  'fresh',
  'stale',
  'unavailable',
  'disabled',
]);

/**
 * Lightweight inline freshness badge that renders from a known value
 * (no API call). Used on pages that already have `RunDetail.graphify_status`.
 * Returns null when the value is null/empty or not a valid projection.
 */
export default function FreshnessBadge({
  value,
}: {
  value: string | null | undefined;
}) {
  const { t } = useTranslation();
  if (!value || !VALID_PROJECTIONS.has(value)) return null;
  const projection = value as FreshnessProjection;
  const tone = FRESHNESS_TONE[projection];
  const labelKey = FRESHNESS_LABEL_KEY[projection];
  return (
    <span className={`graphify-badge graphify-badge--${tone}`}>
      {t(labelKey)}
    </span>
  );
}
