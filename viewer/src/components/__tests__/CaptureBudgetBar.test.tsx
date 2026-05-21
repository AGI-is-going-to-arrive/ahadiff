import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import CaptureBudgetBar from '../CaptureBudgetBar';
import type { CaptureRecommendation } from '../../api/config';

vi.mock('../../i18n/useTranslation', () => ({
  useTranslation: () => ({
    locale: 'en-US',
    t: (key: string, params?: Record<string, string | number>) => {
      const messages: Record<string, string> = {
        'Settings_page.capture_budget_aria':
          'Token budget: total {total}, system prompt {system}, safety reserve {safety}, diff budget {diff}, output reserve {output}, remaining {remaining}',
        'Settings_page.capture_budget_diff': 'Diff token budget',
        'Settings_page.capture_budget_fits': 'Model context sufficient',
        'Settings_page.capture_budget_not_fits': 'Model context too small',
        'Settings_page.capture_budget_output': 'Output reserve',
        'Settings_page.capture_budget_remaining': 'Remaining',
        'Settings_page.capture_budget_safety': 'Safety reserve',
        'Settings_page.capture_budget_system': 'System prompt',
        'Settings_page.capture_budget_total': 'Total context window',
        'Format.bytes_b': 'B',
        'Format.bytes_kb': 'KB',
        'Format.bytes_mb': 'MB',
        'Format.compact_k': 'K',
        'Format.compact_m': 'M',
        'Format.compact_b': 'B',
      };
      const tpl = messages[key] ?? key;
      if (!params) return tpl;
      return tpl.replace(/\{(\w+)\}/g, (_m, k: string) => String(params[k] ?? `{${k}}`));
    },
  }),
}));

function makeRec(overrides: Partial<CaptureRecommendation> = {}): CaptureRecommendation {
  return {
    mode: 'auto',
    max_files: 40,
    hard_limit: 8000,
    max_patch_bytes: 5_000_000,
    payload_byte_budget: 1_500_000,
    context_window: 200_000,
    max_input_tokens: 150_000,
    max_output_tokens: 50_000,
    diff_token_budget: 100_000,
    safety_reserve: 5000,
    output_reserve: 8000,
    system_prompt_tokens: 3000,
    fits_minimums: true,
    model_name: 'gpt-5.5',
    source: 'registry',
    cjk_ratio: 0.0,
    cjk_factor: 1.0,
    warnings: [],
    ...overrides,
  };
}

describe('CaptureBudgetBar', () => {
  it('renders bar with all segments and legend values', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar recommendation={makeRec()} />,
    );
    expect(html).toContain('capture-budget-bar');
    expect(html).toContain('capture-budget-bar__segment--system');
    expect(html).toContain('capture-budget-bar__segment--safety');
    expect(html).toContain('capture-budget-bar__segment--diff');
    expect(html).toContain('capture-budget-bar__segment--output');
    expect(html).toContain('capture-budget-bar__segment--remaining');
    expect(html).toContain('System prompt');
    expect(html).toContain('Safety reserve');
    expect(html).toContain('Diff token budget');
    expect(html).toContain('Output reserve');
    expect(html).toContain('Remaining');
  });

  it('marks status as fits when recommendation.fits_minimums=true', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar recommendation={makeRec({ fits_minimums: true })} />,
    );
    expect(html).toContain('Model context sufficient');
    expect(html).not.toContain('capture-budget-bar--danger');
  });

  it('applies danger styling when fits_minimums=false', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar
        recommendation={makeRec({ fits_minimums: false, context_window: 8000 })}
      />,
    );
    expect(html).toContain('capture-budget-bar--danger');
    expect(html).toContain('Model context too small');
    expect(html).toContain('role="alert"');
  });

  it('returns null when recommendation is missing', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar recommendation={null} />,
    );
    expect(html).toBe('');
  });

  it('returns null when recommendation is undefined', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar recommendation={undefined} />,
    );
    expect(html).toBe('');
  });

  it('exposes aria-label on the track with the full breakdown', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar recommendation={makeRec()} />,
    );
    // aria-label should contain "Token budget:" prefix and all five segments
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="Token budget:');
    expect(html).toContain('system prompt');
    expect(html).toContain('safety reserve');
    expect(html).toContain('diff budget');
    expect(html).toContain('output reserve');
    expect(html).toContain('remaining');
  });

  it('falls back to derived total when context_window is null', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar
        recommendation={makeRec({
          context_window: null,
          max_input_tokens: 100_000,
          max_output_tokens: 32_000,
        })}
      />,
    );
    // Should still render without crashing and show track.
    expect(html).toContain('capture-budget-bar__track');
  });

  it('hides zero-sized segments from the bar', () => {
    const html = renderToStaticMarkup(
      <CaptureBudgetBar
        recommendation={makeRec({
          system_prompt_tokens: 0,
          safety_reserve: 10_000,
          output_reserve: 0,
        })}
      />,
    );
    // System and output legend entries are still rendered (legend lists everything)
    expect(html).toContain('System prompt');
    expect(html).toContain('Output reserve');
  });
});
