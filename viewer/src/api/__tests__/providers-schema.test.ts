import { describe, expect, it } from 'vitest';
import type { ProviderSummary } from '../config';
import {
  modelLimitsResponseSchema,
  modelThinkingSupportSchema,
  providerCreateRequestSchema,
  providerModelsResponseSchema,
  providerSummarySchema,
  providerUpdateRequestSchema,
  providersResponseSchema,
} from '../schemas';
import type { ProviderCreateInput, ProviderUpdateInput } from '../types';

const fullProvider = {
  alias: 'local',
  role: 'generate',
  provider_class: 'openai',
  provider_kind: 'openai',
  model_name: 'gpt-test',
  base_url: 'https://api.example.test/v1',
  api_key_env: 'TEST_API_KEY',
  key_status: 'configured',
  api_family: 'openai_chat',
  api_family_version: '2026-05',
  probed: true,
  probed_max_context: 128000,
  probed_tpm: 60000,
  probed_rpm: 3000,
  probe_timestamp: '2026-05-04T00:00:00Z',
  available_models: ['gpt-test', 'gpt-test-2'],
} satisfies ProviderSummary;

describe('provider API schemas', () => {
  it('accepts the full ProviderSummary shape used by TypeScript callers', () => {
    expect(providerSummarySchema.parse(fullProvider)).toEqual(fullProvider);
    expect(providersResponseSchema.parse({ providers: [fullProvider] })).toEqual({
      providers: [fullProvider],
    });
  });

  it('strips unknown provider fields while keeping the response envelope strict', () => {
    expect(providerSummarySchema.parse({
      ...fullProvider,
      leaked_secret: 'sk-test',
      future_limit_source: 'runtime',
    })).toEqual(fullProvider);
    expect(providersResponseSchema.safeParse({
      providers: [fullProvider],
      extra: true,
    }).success).toBe(false);
  });

  it('keeps mutation request schemas aligned with TypeScript input types', () => {
    const createInput = {
      alias: 'local',
      provider_class: 'openai',
      model_name: 'gpt-test',
      base_url: 'https://api.example.test/v1',
      api_key_env: 'TEST_API_KEY',
      model_limits_name: 'openai/gpt-test',
    } satisfies ProviderCreateInput;
    const updateInput = {
      provider_class: 'openai_responses',
      model_name: 'gpt-test-2',
      base_url: 'https://api.example.test/responses',
      api_key_env: 'TEST_API_KEY_2',
      model_limits_name: null,
    } satisfies ProviderUpdateInput;

    expect(providerCreateRequestSchema.parse(createInput)).toEqual(createInput);
    expect(providerUpdateRequestSchema.parse(updateInput)).toEqual(updateInput);
    // Plaintext `api_key` is now an accepted field (reference-style storage).
    expect(providerCreateRequestSchema.safeParse({
      ...createInput,
      api_key: 'sk-test',
    }).success).toBe(true);
    expect(providerUpdateRequestSchema.safeParse({
      provider_class: 'openai',
      api_key: 'sk-new-secret',
    }).success).toBe(true);
    // Genuinely unknown keys are still rejected by the strict schema.
    expect(providerCreateRequestSchema.safeParse({
      ...createInput,
      totally_unknown: 'x',
    }).success).toBe(false);
    expect(providerUpdateRequestSchema.safeParse({
      ...updateInput,
      unknown: true,
    }).success).toBe(false);
  });

  it('accepts a provider object where overrides_global is null', () => {
    const providerWithNullOverrides = {
      ...fullProvider,
      overrides_global: null,
    };
    const parsed = providerSummarySchema.parse(providerWithNullOverrides);
    expect(parsed.overrides_global).toBeNull();
  });

  it('validates provider model discovery responses strictly', () => {
    expect(
      providerModelsResponseSchema.parse({ models: ['gpt-5.5', 'gpt-5.4-mini'] }),
    ).toEqual({
      models: ['gpt-5.5', 'gpt-5.4-mini'],
    });
    expect(
      providerModelsResponseSchema.safeParse({
        models: ['gpt-5.5'],
        api_key: 'sk-test',
      }).success,
    ).toBe(false);
    expect(providerModelsResponseSchema.safeParse({ models: [42] }).success).toBe(false);
  });

  it.each(['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'enabled', null])(
    'accepts %s thinking without turning an explicit choice into the default', (level) => {
      const update = providerUpdateRequestSchema.parse({ thinking_level: level });
      expect(update.thinking_level).toBe(level);
      expect(providerCreateRequestSchema.parse({
        alias: 'local', provider_class: 'openai_responses', model_name: 'gpt-5.6-luna',
        base_url: 'https://api.example.test/v1', thinking_level: level,
      }).thinking_level).toBe(level);
      expect(providerSummarySchema.parse({ ...fullProvider, thinking_level: level }).thinking_level).toBe(level);
    },
  );

  it('rejects unsupported wire levels while accepting an omitted default', () => {
    for (const level of ['default', 'off', 'ultra', '', 1]) {
      expect(providerUpdateRequestSchema.safeParse({ thinking_level: level }).success).toBe(false);
    }
    expect(providerUpdateRequestSchema.parse({})).toEqual({});
  });

  it('requires complete and consistent capability metadata before offering explicit settings', () => {
    const thinking = {
      supported: true,
      accepted_levels: ['none', 'enabled'],
      payload_mode: 'thinking_toggle',
      warnings: ['thinking_toggle_only'],
    };
    expect(modelThinkingSupportSchema.parse(thinking)).toEqual(thinking);
    expect(modelThinkingSupportSchema.safeParse({ supported: true }).success).toBe(false);
    expect(modelThinkingSupportSchema.safeParse({ ...thinking, supported: false }).success).toBe(false);
    expect(modelThinkingSupportSchema.safeParse({ ...thinking, accepted_levels: [] }).success).toBe(false);
    expect(modelThinkingSupportSchema.safeParse({ ...thinking, accepted_levels: ['high', 'high'] }).success).toBe(false);
    expect(modelThinkingSupportSchema.safeParse({ ...thinking, accepted_levels: ['ultra'] }).success).toBe(false);
    expect(modelThinkingSupportSchema.safeParse({ ...thinking, secret: 'not-allowed' }).success).toBe(false);
  });

  it('accepts optional thinking output minimums only for available levels and positive integer totals', () => {
    const thinking = {
      supported: true, accepted_levels: ['none', 'low', 'high'],
      payload_mode: 'thinking.budget_tokens', warnings: [],
    };
    expect(modelThinkingSupportSchema.parse(thinking).minimum_output_tokens).toBeUndefined();
    expect(modelThinkingSupportSchema.parse({
      ...thinking, minimum_output_tokens: { low: 1025, high: 8193 },
    }).minimum_output_tokens).toEqual({ low: 1025, high: 8193 });
    for (const minimums of [{ high: 0 }, { high: -1 }, { high: 8192.5 }, { max: 8193 }, { invalid: 8193 }]) {
      expect(modelThinkingSupportSchema.safeParse({
        ...thinking, minimum_output_tokens: minimums,
      }).success).toBe(false);
    }
  });

  it('keeps missing limit data unknown without inventing reasoning support', () => {
    const limits = {
      alias: null, provider_class: 'openai_compat', model_name: 'private-model',
      max_context_tokens: null, max_input_tokens: null, max_output_tokens: null,
      max_context_known: false, max_input_known: false, max_output_known: false,
      context_policy: null, source: 'default', confidence: null, warnings: [],
    };
    expect(modelLimitsResponseSchema.parse(limits).thinking).toEqual({
      supported: false, accepted_levels: [], payload_mode: 'unsupported', warnings: [],
    });
    expect(modelLimitsResponseSchema.safeParse({ ...limits, max_input_tokens: -1 }).success).toBe(false);
  });
});
