import type { FreshnessProjection } from '../api/types';
import type { MessageKey } from '../i18n/useTranslation';

export const FRESHNESS_TONE: Record<FreshnessProjection, string> = {
  fresh: 'success',
  stale: 'warning',
  unavailable: 'muted',
  disabled: 'muted',
};

export const FRESHNESS_LABEL_KEY: Record<FreshnessProjection, MessageKey> = {
  fresh: 'Graph.freshness_fresh',
  stale: 'Graph.freshness_stale',
  unavailable: 'Graph.freshness_unavailable',
  disabled: 'Graph.freshness_disabled',
};
