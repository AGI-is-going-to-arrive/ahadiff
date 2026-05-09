import { memo } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import type { RatchetHistoryEntry } from '../api/types';
import './RatchetChart.css';

export interface RatchetChartProps {
  history: RatchetHistoryEntry[];
}

const SVG_W = 700;
const SVG_H = 240;
const PAD_L = 40;
const PAD_R = 20;
const PAD_T = 20;
const PAD_B = 20;
const PLOT_W = SVG_W - PAD_L - PAD_R;
const PLOT_H = SVG_H - PAD_T - PAD_B;

function toX(i: number, count: number): number {
  if (count <= 1) return PAD_L + PLOT_W / 2;
  return PAD_L + (i / (count - 1)) * PLOT_W;
}

function toY(score: number): number {
  const clamped = Math.max(0, Math.min(100, score));
  return PAD_T + PLOT_H - (clamped / 100) * PLOT_H;
}

/**
 * Inline SVG ratchet quality curve (overall score over time).
 * Returns `null` when fewer than 2 data points — parent handles the fallback text.
 */
function RatchetChartInner({ history }: RatchetChartProps) {
  const { t } = useTranslation();
  if (history.length < 2) return null;
  const ariaLabel = t('Dashboard.ratchet_chart_label');

  const sorted = [...history].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  );
  const n = sorted.length;

  const pathD = sorted
    .map((entry, i) => {
      const x = toX(i, n);
      const y = toY(entry.overall);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  // Closed area fill path (down to bottom, back to start)
  const areaD =
    pathD +
    ` L${toX(n - 1, n).toFixed(1)},${(PAD_T + PLOT_H).toFixed(1)}` +
    ` L${toX(0, n).toFixed(1)},${(PAD_T + PLOT_H).toFixed(1)} Z`;

  return (
    <svg
      className="ratchet-chart__svg"
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      role="img"
      aria-label={ariaLabel}
    >
      {/* Horizontal grid lines */}
      <g stroke="var(--hair)" strokeDasharray="2 4" strokeWidth="1" aria-hidden="true">
        {[0, 25, 50, 75, 100].map((v) => (
          <line key={v} x1={PAD_L} y1={toY(v)} x2={SVG_W - PAD_R} y2={toY(v)} />
        ))}
      </g>

      {/* Y-axis labels */}
      <g fontFamily="var(--font-mono)" fontSize="10" fill="var(--muted)" aria-hidden="true">
        {[0, 25, 50, 75, 100].map((v) => (
          <text key={v} x={PAD_L - 6} y={toY(v) + 4} textAnchor="end">
            {v}
          </text>
        ))}
      </g>

      {/* Area fill */}
      <path d={areaD} fill="var(--accent-soft)" opacity="0.35" />

      {/* Line */}
      <path d={pathD} fill="none" stroke="var(--accent)" strokeWidth="2" />

      {/* Dots */}
      <g aria-hidden="true">
        {sorted.map((entry, i) => {
          const x = toX(i, n);
          const y = toY(entry.overall);
          const isLast = i === n - 1;
          return (
            <circle
              key={entry.run_id}
              cx={x}
              cy={y}
              r={isLast ? 4 : 3}
              fill={isLast ? 'var(--elevated)' : 'var(--accent)'}
              stroke={isLast ? 'var(--accent-ink)' : 'none'}
              strokeWidth={isLast ? 2 : 0}
            />
          );
        })}
      </g>

      {/* Final score label */}
      {(() => {
        const last = sorted[n - 1];
        const x = toX(n - 1, n);
        const y = toY(last.overall);
        const labelX = x - 30;
        const labelY = y - 12;
        return (
          <g fontFamily="var(--font-mono)" fontSize="10" fill="var(--success)">
            <rect
              x={labelX}
              y={labelY - 10}
              width="60"
              height="16"
              rx="3"
              fill="var(--add-bg)"
            />
            <text x={labelX + 6} y={labelY + 2}>
              {last.overall.toFixed(0)}
            </text>
          </g>
        );
      })()}
    </svg>
  );
}

const RatchetChart = memo(RatchetChartInner);
export default RatchetChart;
