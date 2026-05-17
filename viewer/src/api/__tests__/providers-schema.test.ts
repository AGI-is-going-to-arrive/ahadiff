import { describe, expect, it } from 'vitest';
import type { ProviderSummary } from '../config';
import {
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

  it('rejects unknown fields on provider responses', () => {
    expect(providerSummarySchema.safeParse({
      ...fullProvider,
      leaked_secret: 'sk-test',
    }).success).toBe(false);
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
    } satisfies ProviderCreateInput;
    const updateInput = {
      provider_class: 'openai_responses',
      model_name: 'gpt-test-2',
      base_url: 'https://api.example.test/responses',
      api_key_env: 'TEST_API_KEY_2',
    } satisfies ProviderUpdateInput;

    expect(providerCreateRequestSchema.parse(createInput)).toEqual(createInput);
    expect(providerUpdateRequestSchema.parse(updateInput)).toEqual(updateInput);
    expect(providerCreateRequestSchema.safeParse({
      ...createInput,
      api_key: 'sk-test',
    }).success).toBe(false);
    expect(providerUpdateRequestSchema.safeParse({
      ...updateInput,
      unknown: true,
    }).success).toBe(false);
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
});
