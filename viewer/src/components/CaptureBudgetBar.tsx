import { useMemo, type ReactElement } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import { buildFormatTexts, formatCompactNumber } from '../utils/format';
import type { CaptureRecommendation } from '../api/config';
import './CaptureBudgetBar.css';

export interface CaptureBudgetBarProps {
  /** The recommendation payload from `/api/capture/recommended` (or estimate). */
  recommendation: CaptureRecommendation | null | undefined;
  /** Optional className for layout integration. */
  className?: string;
}

interface BudgetSegment {
  key: 'system' | 'safety' | 'diff' | 'output' | 'remaining';
  label: string;
  tokens: number;
  variant: string;
}

/**
 * Token-budget breakdown bar. Renders an external legend below the bar so
 * the visualisation never depends on text rendering inside narrow segments.
 *
 * Accessibility: the bar itself is `role="img"` with an aria-label that
 * narrates the full breakdown.  The legend duplicates that information for
 * sighted users.  When `fits_minimums` is false the bar gets a danger
 * outline and a status row clarifies the failure.
 */
export default function CaptureBudgetBar({
  recommendation,
  className = '',
}: CaptureBudgetBarProps): ReactElement | null {
  const { t, locale } = useTranslation();
  const formatTexts = useMemo(() => buildFormatTexts(t), [t]);

  if (!recommendation) {
    return null;
  }

  const contextWindow = recommendation.context_window
    ?? recommendation.max_input_tokens
    + recommendation.max_output_tokens;
  const system = Math.max(0, recommendation.system_prompt_tokens);
  const safety = Math.max(0, recommendation.safety_reserve);
  const diff = Math.max(0, recommendation.diff_token_budget);
  const output = Math.max(0, recommendation.output_reserve);
  const used = system + safety + diff + output;
  const remaining = Math.max(0, contextWindow - used);

  const segments: BudgetSegment[] = [
    {
      key: 'system',
      label: t('Settings_page.capture_budget_system'),
      tokens: system,
      variant: 'system',
    },
    {
      key: 'safety',
      label: t('Settings_page.capture_budget_safety'),
      tokens: safety,
      variant: 'safety',
    },
    {
      key: 'diff',
      label: t('Settings_page.capture_budget_diff'),
      tokens: diff,
      variant: 'diff',
    },
    {
      key: 'output',
      label: t('Settings_page.capture_budget_output'),
      tokens: output,
      variant: 'output',
    },
    {
      key: 'remaining',
      label: t('Settings_page.capture_budget_remaining'),
      tokens: remaining,
      variant: 'remaining',
    },
  ];

  const total = contextWindow > 0 ? contextWindow : Math.max(1, used + remaining);
  const fmt = (n: number) => formatCompactNumber(n, locale, formatTexts);

  const ariaLabel = t('Settings_page.capture_budget_aria', {
    total: fmt(total),
    system: fmt(system),
    safety: fmt(safety),
    diff: fmt(diff),
    output: fmt(output),
    remaining: fmt(remaining),
  });

  const fits = recommendation.fits_minimums;
  const containerClass = [
    'capture-budget-bar',
    !fits ? 'capture-budget-bar--danger' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <div className={containerClass} data-testid="capture-budget-bar">
      <div className="capture-budget-bar__header">
        <span className="capture-budget-bar__title">
          {t('Settings_page.capture_budget_total')}
        </span>
        <span className="capture-budget-bar__total" data-testid="capture-budget-bar-total">
          {fmt(total)}
        </span>
      </div>
      <div
        role="img"
        aria-label={ariaLabel}
        className="capture-budget-bar__track"
      >
        {segments.map((seg) => {
          const pct = total > 0 ? Math.max(0, (seg.tokens / total) * 100) : 0;
          if (pct <= 0) return null;
          return (
            <span
              key={seg.key}
              className={`capture-budget-bar__segment capture-budget-bar__segment--${seg.variant}`}
              style={{ width: `${pct}%` }}
              aria-hidden="true"
            />
          );
        })}
      </div>
      <ul className="capture-budget-bar__legend" aria-hidden="true">
        {segments.map((seg) => (
          <li key={seg.key} className="capture-budget-bar__legend-item">
            <span
              className={`capture-budget-bar__swatch capture-budget-bar__swatch--${seg.variant}`}
            />
            <span className="capture-budget-bar__legend-label">{seg.label}</span>
            <span className="capture-budget-bar__legend-value">{fmt(seg.tokens)}</span>
          </li>
        ))}
      </ul>
      <p
        className={`capture-budget-bar__status${fits ? '' : ' capture-budget-bar__status--danger'}`}
        role={fits ? undefined : 'alert'}
      >
        {fits
          ? t('Settings_page.capture_budget_fits')
          : t('Settings_page.capture_budget_not_fits')}
      </p>
    </div>
  );
}
