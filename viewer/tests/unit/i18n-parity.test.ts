import { describe, expect, it } from 'vitest';
import enMessages from '../../src/i18n/messages/en.json';
import zhMessages from '../../src/i18n/messages/zh-CN.json';

type MessageLeaf = string | number | boolean | null;

function flattenMessages(
  value: unknown,
  prefix = '',
  out = new Map<string, MessageLeaf>(),
): Map<string, MessageLeaf> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      flattenMessages(child, prefix ? `${prefix}.${key}` : key, out);
    }
    return out;
  }
  out.set(prefix, value as MessageLeaf);
  return out;
}

function placeholders(value: MessageLeaf): string[] {
  if (typeof value !== 'string') return [];
  return Array.from(value.matchAll(/\{[^{}]+\}/g), (match) => match[0]).sort();
}

describe('i18n catalog parity', () => {
  it('keeps en and zh-CN keys and placeholders aligned', () => {
    const en = flattenMessages(enMessages);
    const zh = flattenMessages(zhMessages);
    const enKeys = Array.from(en.keys()).sort();
    const zhKeys = Array.from(zh.keys()).sort();

    expect(zhKeys).toEqual(enKeys);
    for (const key of enKeys) {
      expect(placeholders(zh.get(key) ?? null)).toEqual(placeholders(en.get(key) ?? null));
    }
  });
});
