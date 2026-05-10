export interface FormatTexts {
  bytes_b: string;
  bytes_kb: string;
  bytes_mb: string;
  compact_k: string;
  compact_m: string;
  compact_b: string;
}

const DEFAULT_TEXTS: FormatTexts = {
  bytes_b: 'B',
  bytes_kb: 'KB',
  bytes_mb: 'MB',
  compact_k: 'K',
  compact_m: 'M',
  compact_b: 'B',
};

export function formatBytes(bytes: number, locale: string, texts?: FormatTexts): string {
  const t = texts ?? DEFAULT_TEXTS;
  const fmt = (n: number) => {
    try {
      return n.toLocaleString(locale || undefined, {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      });
    } catch {
      return n.toFixed(1);
    }
  };
  if (bytes < 1024) return `${bytes} ${t.bytes_b}`;
  if (bytes < 1024 * 1024) return `${fmt(bytes / 1024)} ${t.bytes_kb}`;
  return `${fmt(bytes / (1024 * 1024))} ${t.bytes_mb}`;
}

export function formatCompactNumber(value: number, locale: string, texts?: FormatTexts): string {
  try {
    const formatter = new Intl.NumberFormat(locale || undefined, {
      notation: 'compact',
      maximumFractionDigits: 1,
    });
    if (formatter.resolvedOptions().notation === 'compact') {
      return formatter.format(value);
    }
  } catch {
    // Fall through to the deterministic fallback below.
  }
  return formatCompactFallback(value, locale, texts ?? DEFAULT_TEXTS);
}

function formatCompactFallback(value: number, locale: string, texts: FormatTexts): string {
  const abs = Math.abs(value);
  if (abs < 1000) return formatNumberPart(value, locale, 0);

  const units: Array<[number, string]> = [
    [1_000_000_000, texts.compact_b],
    [1_000_000, texts.compact_m],
    [1_000, texts.compact_k],
  ];
  const [divisor, suffix] = units.find(([threshold]) => abs >= threshold) ?? [1, ''];
  const scaled = value / divisor;
  const maximumFractionDigits = Math.abs(scaled) < 10 ? 1 : 0;
  return `${formatNumberPart(scaled, locale, maximumFractionDigits)}${suffix}`;
}

function formatNumberPart(value: number, locale: string, maximumFractionDigits: number): string {
  try {
    return value.toLocaleString(locale || undefined, { maximumFractionDigits });
  } catch {
    return value.toFixed(maximumFractionDigits).replace(/\.0$/, '');
  }
}

export function formatScore(value: number): string {
  return value.toFixed(1);
}

export function formatCurrency(value: number, locale: string, currency = 'USD'): string {
  try {
    return new Intl.NumberFormat(locale || undefined, {
      style: 'currency',
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    }).format(value);
  } catch {
    return `$${value.toFixed(4)}`;
  }
}

/**
 * Build a {@link FormatTexts} bundle from an i18n translate function.
 * Use this in components that already call `useTranslation()`.
 */
export function buildFormatTexts(t: (key: string) => string): FormatTexts {
  return {
    bytes_b: t('Format.bytes_b'),
    bytes_kb: t('Format.bytes_kb'),
    bytes_mb: t('Format.bytes_mb'),
    compact_k: t('Format.compact_k'),
    compact_m: t('Format.compact_m'),
    compact_b: t('Format.compact_b'),
  };
}
