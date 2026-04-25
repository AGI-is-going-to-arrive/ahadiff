export interface KpiCardProps {
  label: string;
  value: string | number;
  hint?: string;
  tone?: 'default' | 'success' | 'warning' | 'danger';
}

/**
 * KPI indicator card matching the Warm v6 `.kpi` pattern.
 * Pure presentational — no store subscription.
 */
export default function KpiCard({ label, value, hint, tone = 'default' }: KpiCardProps) {
  return (
    <div className={`kpi-card kpi-card--${tone}`}>
      <div className="kpi-card__label">{label}</div>
      <div className="kpi-card__value">{value}</div>
      {hint && <div className="kpi-card__hint">{hint}</div>}
    </div>
  );
}
