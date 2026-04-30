/**
 * Phase 4A: 30-day review activity heatmap.
 *
 * Mirrors V6 template (AhaDiff Warm v6.html L2228-L2244): 30 cells laid out
 * as a 10×3 grid, intensity bucketed into 4 levels (none / low / mid / high)
 * keyed off review counts per day. The component is data-agnostic — pass
 * already-bucketed `cells` from the consumer (DashboardPage / RatchetPage /
 * ReviewPage) so the same widget supports `/api/review/heatmap` once the
 * Phase 1E backend route lands without a UI rewrite.
 */

import { useMemo } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import './CalendarHeatmap.css';

export interface HeatmapCell {
  /** ISO date (YYYY-MM-DD) the cell represents. */
  iso_date: string;
  /** Activity count — higher count → darker cell. 0 means no activity. */
  count: number;
}

export interface CalendarHeatmapProps {
  /** Optional title shown above the grid. Falls back to localized default. */
  title?: string;
  /** Cells in chronological order; component pads/clips to 30 cells. */
  cells: ReadonlyArray<HeatmapCell>;
  /** Skeleton mode while data is in flight. */
  loading?: boolean;
  /** Bucket thresholds; counts ≥ threshold[i] use level i+1. Default: [1, 3, 6]. */
  thresholds?: readonly [number, number, number];
}

const DEFAULT_THRESHOLDS = [1, 3, 6] as const;
const TOTAL_CELLS = 30;

function bucket(
  count: number,
  thresholds: readonly [number, number, number],
): 0 | 1 | 2 | 3 {
  if (count <= 0) return 0;
  if (count < thresholds[0]) return 0;
  if (count < thresholds[1]) return 1;
  if (count < thresholds[2]) return 2;
  return 3;
}

function padCells(cells: ReadonlyArray<HeatmapCell>): ReadonlyArray<HeatmapCell> {
  if (cells.length >= TOTAL_CELLS) return cells.slice(-TOTAL_CELLS);
  /* Left-pad with zero-count placeholder cells so layout is always 30. */
  const padCount = TOTAL_CELLS - cells.length;
  const earliest = cells[0]?.iso_date ?? new Date().toISOString().slice(0, 10);
  const padded: HeatmapCell[] = [];
  for (let i = 0; i < padCount; i += 1) {
    padded.push({ iso_date: `pad-${earliest}-${i}`, count: 0 });
  }
  return [...padded, ...cells];
}

export default function CalendarHeatmap({
  title,
  cells,
  loading = false,
  thresholds = DEFAULT_THRESHOLDS,
}: CalendarHeatmapProps) {
  const { t } = useTranslation();

  const padded = useMemo(() => padCells(cells), [cells]);
  const totalActivity = useMemo(
    () => cells.reduce((sum, c) => sum + Math.max(0, c.count), 0),
    [cells],
  );

  const headerTitle = title ?? t('Heatmap.title');
  const meta = t('Heatmap.meta_30d', { count: String(totalActivity) });

  return (
    <section
      className="calendar-heatmap"
      aria-label={headerTitle}
      data-loading={loading ? 'true' : undefined}
    >
      <header className="calendar-heatmap__header">
        <h3 className="calendar-heatmap__title">{headerTitle}</h3>
        <span className="calendar-heatmap__meta">{meta}</span>
      </header>
      <div
        className="calendar-heatmap__grid"
        role="img"
        aria-label={t('Heatmap.aria_grid', {
          total: String(totalActivity),
        })}
      >
        {loading
          ? Array.from({ length: TOTAL_CELLS }, (_, i) => (
              <span
                key={`skel-${i}`}
                className="calendar-heatmap__cell calendar-heatmap__cell--skeleton"
                aria-hidden="true"
              />
            ))
          : padded.map((cell) => {
              const level = bucket(cell.count, thresholds);
              return (
                <span
                  key={cell.iso_date}
                  className={`calendar-heatmap__cell calendar-heatmap__cell--lvl-${level}`}
                  data-date={cell.iso_date}
                  data-count={cell.count}
                  title={t('Heatmap.cell_title', {
                    date: cell.iso_date.startsWith('pad-')
                      ? '—'
                      : cell.iso_date,
                    count: String(cell.count),
                  })}
                />
              );
            })}
      </div>
      <footer className="calendar-heatmap__legend" aria-hidden="true">
        <span>{t('Heatmap.legend_less')}</span>
        <span className="calendar-heatmap__legend-cell calendar-heatmap__legend-cell--lvl-0" />
        <span className="calendar-heatmap__legend-cell calendar-heatmap__legend-cell--lvl-1" />
        <span className="calendar-heatmap__legend-cell calendar-heatmap__legend-cell--lvl-2" />
        <span className="calendar-heatmap__legend-cell calendar-heatmap__legend-cell--lvl-3" />
        <span>{t('Heatmap.legend_more')}</span>
      </footer>
    </section>
  );
}
