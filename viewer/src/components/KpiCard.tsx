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
    <div className={`kpi kpi--${tone}`}>
      <div className="lb">{label}</div>
      <div className="vl">{value}</div>
      {hint && <div className="delta">{hint}</div>}
    </div>
  );
}
