import type { ConceptHealthStatus } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import '../styles/health-badge.css';

interface HealthBadgeProps {
  status?: ConceptHealthStatus;
  showHealthy?: boolean;
  className?: string;
}

const LABEL_KEYS: Record<ConceptHealthStatus, string> = {
  healthy: 'Concept.health_healthy',
  orphan: 'Concept.health_orphan',
  stale: 'Concept.health_stale',
  contradicted: 'Concept.health_contradicted',
  dismissed: 'Concept.health_dismissed',
};

export default function HealthBadge({
  status,
  showHealthy = false,
  className,
}: HealthBadgeProps) {
  const { t } = useTranslation();

  if (!status) return null;
  if (status === 'healthy' && !showHealthy) return null;

  const label = t(LABEL_KEYS[status]);
  const aria = t('Concept.health_badge_aria', { status: label });
  const classes = [
    'health-badge',
    `health-badge--${status}`,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes} aria-label={aria}>
      <span className="health-badge__dot" aria-hidden="true" />
      {label}
    </span>
  );
}
