import type { Verdict } from '../api/types';

export const VALID_VERDICTS: ReadonlySet<Verdict> = new Set(['PASS', 'CAUTION', 'FAIL']);

export function safeVerdict(value: unknown): Verdict {
  return typeof value === 'string' && VALID_VERDICTS.has(value as Verdict)
    ? (value as Verdict)
    : 'CAUTION';
}
