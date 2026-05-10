import type { TranslateFn, TranslationKey } from '../i18n/useTranslation';

export function getErrorMessage(
  t: TranslateFn,
  code: string | null | undefined,
  fallback: string,
): string {
  if (!code) return fallback;
  const key: TranslationKey = `errors.${code}`;
  const msg = t(key);
  return msg === key ? fallback : msg;
}
