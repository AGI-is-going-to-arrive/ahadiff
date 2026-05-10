import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatBytes, formatCompactNumber } from './format';

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

  it('keeps negative small numbers stable in fallback mode', () => {
    vi.stubGlobal('Intl', {
      ...Intl,
      NumberFormat: vi.fn(() => ({
        format: (value: number) => realNumberFormat('en-US').format(value),
        resolvedOptions: () => ({}),
      })),
    });

    expect(formatCompactNumber(-1, 'en-US', {
      bytes_b: 'bytes',
      bytes_kb: 'KiB',
      bytes_mb: 'MiB',
      compact_k: 'k',
      compact_m: 'm',
      compact_b: 'bn',
    })).toBe('-1');
  });

  it('uses localized byte unit labels', () => {
    const texts = {
      bytes_b: '字节',
      bytes_kb: 'KiB',
      bytes_mb: 'MiB',
      compact_k: '千',
      compact_m: '百万',
      compact_b: '十亿',
    };

    expect(formatBytes(64, 'zh-CN', texts)).toBe('64 字节');
    expect(formatBytes(2048, 'zh-CN', texts)).toBe('2.0 KiB');
  });
});
