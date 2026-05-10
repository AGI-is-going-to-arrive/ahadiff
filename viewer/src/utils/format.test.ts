import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatCompactNumber } from './format';

const realNumberFormat = Intl.NumberFormat;

describe('formatCompactNumber', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uses Intl compact notation when the runtime supports it', () => {
    expect(formatCompactNumber(1500, 'en-US')).toBe('1.5K');
  });

  it('falls back when older runtimes silently ignore compact notation', () => {
    vi.stubGlobal('Intl', {
      ...Intl,
      NumberFormat: vi.fn(() => ({
        format: (value: number) => realNumberFormat('en-US').format(value),
        resolvedOptions: () => ({}),
      })),
    });

    expect(formatCompactNumber(1500, 'en-US')).toBe('1.5K');
    expect(formatCompactNumber(1000000, 'en-US')).toBe('1M');
  });
});
