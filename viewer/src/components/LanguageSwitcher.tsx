import { useCallback } from 'react';
import { useLocaleStore } from '../state/locale-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import type { Locale } from '../api/types';

const LOCALES: ReadonlyArray<{ code: Locale; labelKey: MessageKey }> = [
  { code: 'en', labelKey: 'Settings.language_en' },
  { code: 'zh-CN', labelKey: 'Settings.language_zh_CN' },
];

export default function LanguageSwitcher() {
  const { t, locale } = useTranslation();
  const setLocale = useLocaleStore((s) => s.setLocale);

  const handleSelect = useCallback(
    (next: Locale) => {
      if (next === locale) return;
      void setLocale(next);
    },
    [locale, setLocale],
  );

  return (
    <div
      className="lang-switcher"
      role="group"
      aria-label={t('Settings.language')}
    >
      {LOCALES.map((opt) => {
        const active = opt.code === locale;
        return (
          <button
            key={opt.code}
            type="button"
            className={`lang-switcher__btn${active ? ' lang-switcher__btn--active' : ''}`}
            aria-pressed={active}
            onClick={() => handleSelect(opt.code)}
          >
            {t(opt.labelKey)}
          </button>
        );
      })}
    </div>
  );
}
