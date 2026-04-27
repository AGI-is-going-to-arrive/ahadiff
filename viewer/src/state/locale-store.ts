import { create } from 'zustand';
import { getLocale, putLocale } from '../api/locale';
import type { Locale } from '../api/types';
import { COOKIE_NAME } from '../i18n/constants';

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.split('; ').find((row) => row.startsWith(`${name}=`));
  if (!match) return null;
  try {
    return decodeURIComponent(match.split('=')[1]!);
  } catch {
    return null;
  }
}

function writeCookie(name: string, value: string, maxAgeDays = 365): void {
  if (typeof document === 'undefined') return;
  const maxAge = maxAgeDays * 24 * 60 * 60;
  document.cookie = `${name}=${encodeURIComponent(value)}; max-age=${maxAge}; path=/; samesite=lax`;
}

function coerceLocale(v: string | null | undefined): Locale {
  if (v === 'zh-CN' || v === 'zh') return 'zh-CN';
  return 'en';
}

interface LocaleState {
  locale: Locale;
  setLocale: (locale: Locale) => Promise<void>;
  initLocale: () => Promise<void>;
}

export const useLocaleStore = create<LocaleState>((set) => ({
  locale: coerceLocale(
    readCookie(COOKIE_NAME) ?? (typeof navigator !== 'undefined' ? navigator.language : 'en'),
  ),

  setLocale: async (locale) => {
    writeCookie(COOKIE_NAME, locale);
    set({ locale });
    if (typeof document !== 'undefined') document.documentElement.lang = locale;
    try {
      await putLocale({ lang: locale });
    } catch {
      // server may be unavailable; cookie is the durable fallback
    }
  },

  initLocale: async () => {
    try {
      const res = await getLocale();
      const resolved = coerceLocale(res.locale);
      // Cookie is the source of truth per spec §4.4. If a valid cookie already
      // exists, do not let server fallback overwrite an explicit user choice;
      // only adopt server value when cookie is missing.
      const cookieRaw = readCookie(COOKIE_NAME);
      const cookieValid = cookieRaw === 'en' || cookieRaw === 'zh-CN' || cookieRaw === 'zh';
      if (cookieValid) return;
      set({ locale: resolved });
      if (typeof document !== 'undefined') document.documentElement.lang = resolved;
    } catch {
      // server may be unavailable; local cookie/navigator fallback is already set
    }
  },
}));
