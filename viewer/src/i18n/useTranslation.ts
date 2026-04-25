import { useCallback } from 'react';
import { useLocaleStore } from '../state/locale-store';
import enMessages from './messages/en.json';
import zhCNMessages from './messages/zh-CN.json';
import type { Locale } from '../api/types';

/* ---------- Type-safe i18n key paths ---------- */

/**
 * Recursively derive all dot-separated key paths from a nested JSON shape.
 * e.g. { Brand: { name: "AhaDiff" } } => "Brand.name"
 */
type DotPaths<T, Prefix extends string = ''> = T extends string
  ? Prefix
  : T extends Record<string, unknown>
    ? {
        [K in keyof T & string]: DotPaths<
          T[K],
          Prefix extends '' ? K : `${Prefix}.${K}`
        >;
      }[keyof T & string]
    : never;

/** All valid i18n key paths derived from the English catalog. */
export type MessageKey = DotPaths<typeof enMessages>;

/**
 * Accepts known MessageKey literals (with IDE autocomplete) while also
 * allowing arbitrary `string` so callers that build keys dynamically
 * (e.g. from arrays) continue to compile without changes.
 *
 * The `(string & {})` trick preserves literal suggestions in TS intellisense.
 */
// eslint-disable-next-line @typescript-eslint/no-redundant-type-constituents
export type TranslationKey = MessageKey | (string & {});

type MessagesTree = Record<string, unknown>;

const catalogs: Record<Locale, MessagesTree> = {
  en: enMessages as MessagesTree,
  'zh-CN': zhCNMessages as MessagesTree,
};

function lookup(tree: MessagesTree, dotKey: string): string | undefined {
  const parts = dotKey.split('.');
  let current: unknown = tree;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in (current as Record<string, unknown>)) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return typeof current === 'string' ? current : undefined;
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? `{${key}}`));
}

export function useTranslation() {
  const locale = useLocaleStore((s) => s.locale);

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>): string => {
      const fromLocale = lookup(catalogs[locale] ?? catalogs.en, key);
      if (fromLocale !== undefined) return interpolate(fromLocale, params);

      const fromEn = lookup(catalogs.en, key);
      if (fromEn !== undefined) return interpolate(fromEn, params);

      if ((import.meta as unknown as Record<string, Record<string, boolean> | undefined>).env?.DEV) {
        // eslint-disable-next-line no-console
        console.warn(`[i18n] missing key: ${key} (locale=${locale})`);
      }
      return key;
    },
    [locale],
  );

  return { t, locale };
}
