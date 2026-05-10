export function formatBytes(bytes: number, locale: string): string {
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
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmt(bytes / 1024)} KB`;
  return `${fmt(bytes / (1024 * 1024))} MB`;
}

export function formatCompactNumber(value: number, locale: string): string {
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
  return formatCompactFallback(value, locale);
}

function formatCompactFallback(value: number, locale: string): string {
  const abs = Math.abs(value);
  if (abs < 1000) return formatNumberPart(value, locale, 0);

  const units: Array<[number, string]> = [
    [1_000_000_000, 'B'],
    [1_000_000, 'M'],
    [1_000, 'K'],
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
