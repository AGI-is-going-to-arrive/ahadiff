import { describe, expect, it } from 'vitest';
import { learnEstimateResponseSchema } from '../schemas';
import type { LearnEstimateResponse } from '../types';

describe('learn task API schemas', () => {
  it('keeps learn estimate responses strict and aligned with TypeScript callers', () => {
    const estimate = {
      patch_bytes: 128,
      file_count: 2,
      total_lines: 12,
      estimated_tokens: 256,
      provider_context_window: 128000,
      provider_max_output: null,
      risk_level: 'warn',
      warnings: ['large diff'],
    } satisfies LearnEstimateResponse;

    // Schema applies defaults for the new optional Phase-3 fields, so we
    // compare against the augmented expectation rather than the raw input.
    expect(learnEstimateResponseSchema.parse(estimate)).toEqual({
      ...estimate,
      diff_clipped: false,
      omitted_files_count: 0,
    });
    expect(
      learnEstimateResponseSchema.safeParse({
        ...estimate,
        provider_context_window: 0,
      }).success,
    ).toBe(false);
    expect(
      learnEstimateResponseSchema.safeParse({
        ...estimate,
        leaked_secret: 'sk-test',
      }).success,
    ).toBe(false);
  });
});
