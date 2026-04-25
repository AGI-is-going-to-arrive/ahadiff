import { useLocaleStore } from '../state/locale-store';
import type { Locale } from '../api/types';
import { COOKIE_NAME } from './constants';

function readCookieFresh(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.split('; ').find((row) => row.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.split('=')[1]!) : null;
}

function coerceLocale(v: string | null | undefined): Locale | null {
  if (v === 'zh-CN' || v === 'zh') return 'zh-CN';
  if (v === 'en') return 'en';
  return null;
}

function applyLocaleFromCookie(): void {
  if (typeof document === 'undefined') return;
  const cookieLocale = coerceLocale(readCookieFresh(COOKIE_NAME));
  const store = useLocaleStore.getState();
  if (cookieLocale && store.locale !== cookieLocale) {
    useLocaleStore.setState({ locale: cookieLocale });
    document.documentElement.lang = cookieLocale;
  } else {
    document.documentElement.lang = store.locale;
  }
}

(function bootstrap() {
  if (typeof document !== 'undefined') {
    // Apply once synchronously for fast paint.
    applyLocaleFromCookie();

    // WebKit sometimes returns an empty document.cookie during module init even
    // when the cookie store has the value (page.reload race). Re-apply after a
    // microtask and a macrotask, plus DOMContentLoaded if the document is still
    // loading. Each call is idempotent (no-op if state already matches).
    queueMicrotask(applyLocaleFromCookie);
    setTimeout(applyLocaleFromCookie, 0);
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', applyLocaleFromCookie, { once: true });
    }
  }
  void useLocaleStore
    .getState()
    .initLocale()
    .catch(() => {
      // silent: initLocale may fail if serve backend is not running
    });
})();

export {};
