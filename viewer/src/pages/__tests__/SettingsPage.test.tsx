import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ConfigResponse, ProviderSummary } from '../../api/config';
import {
  buildProviderConfigUpdatePayload,
  effectiveModelProvider,
  modelOptionsForProvider,
  nextModelForProviderSelection,
  type ProviderForm,
} from '../SettingsPage';

function makeProvider(overrides: Partial<ProviderSummary> = {}): ProviderSummary {
  return {
    alias: 'gpt',
    provider_class: 'openai_responses',
    provider_kind: 'openai_responses',
    model_name: 'gpt-5.5',
    base_url: 'https://api.openai.com/v1',
    api_key_env: 'AHADIFF_PROVIDER_API_KEY',
    key_status: 'configured',
    probed: true,
    probed_max_context: 1_000_000,
    available_models: ['gpt-5.5', 'gpt-5.4-mini'],
    ...overrides,
  };
}

function makeConfig(overrides: Partial<ConfigResponse> = {}): ConfigResponse {
  return {
    lang: 'zh-CN',
    privacy_mode: 'strict_local',
    generate_provider: '',
    generate_model: 'gpt-5.4-mini',
    judge_provider: '',
    judge_model: 'gpt-5.4-mini',
    serve_port: 8765,
    key_status: {},
    capture: {
      max_files: 30,
      hard_limit: 3000,
      max_patch_bytes: 5_000_000,
      file_ranking: 'learning_value',
      symbol_extractor: 'auto',
    },
    llm: {
      input_token_budget: 200_000,
      output_token_budget: 50_000,
      request_timeout_seconds: 30,
      max_concurrent: 3,
      retry_attempts: 3,
      output_lang: 'auto',
    },
    learn: {
      learnability_threshold: 0.3,
      desired_retention: 0.9,
    },
    quiz: {
      quiz_question_count: 3,
    },
    ...overrides,
  };
}

function formFromConfig(config: ConfigResponse, overrides: Partial<ProviderForm> = {}): ProviderForm {
  return {
    generate_provider: config.generate_provider ?? '',
    generate_model: config.generate_model ?? '',
    judge_provider: config.judge_provider ?? '',
    judge_model: config.judge_model ?? '',
    llm: { ...config.llm },
    ...overrides,
  };
}

describe('SettingsPage provider/model helpers', () => {
  it('uses a single provider as the effective auto provider and exposes its models', () => {
    const provider = makeProvider({
      available_models: ['gpt-5.5', 'gpt-5.5', 'gpt-5.4-mini'],
    });

    expect(effectiveModelProvider([provider], '')?.alias).toBe('gpt');
    expect(modelOptionsForProvider(provider)).toEqual(['gpt-5.5', 'gpt-5.4-mini']);
    expect(nextModelForProviderSelection([provider], '', 'unknown-model')).toBe('gpt-5.5');
    expect(nextModelForProviderSelection([provider], '', 'gpt-5.4-mini')).toBe('gpt-5.4-mini');
  });

  it('keeps auto provider ambiguous when multiple providers exist', () => {
    const providers = [
      makeProvider({ alias: 'gpt' }),
      makeProvider({ alias: 'azure', provider_class: 'azure', model_name: 'gpt-5.5-azure' }),
    ];

    expect(effectiveModelProvider(providers, '')).toBeUndefined();
    expect(nextModelForProviderSelection(providers, '', 'manual-model')).toBe('manual-model');
    expect(effectiveModelProvider(providers, 'azure')?.model_name).toBe('gpt-5.5-azure');
  });

  it('does not persist default model fields when only LLM limits change', () => {
    const config = makeConfig();
    const form = formFromConfig(config, {
      llm: { ...config.llm, max_concurrent: 4 },
    });

    expect(buildProviderConfigUpdatePayload(form, config)).toEqual({
      llm: { max_concurrent: 4 },
    });
  });

  it('can save generation and judge models without a provider alias for single-provider auto mode', () => {
    const config = makeConfig();
    const form = formFromConfig(config, {
      generate_model: 'gpt-5.5',
      judge_model: 'gpt-5.5-judge',
    });

    expect(buildProviderConfigUpdatePayload(form, config)).toEqual({
      generate_model: 'gpt-5.5',
      judge_model: 'gpt-5.5-judge',
    });
  });

  it('guards integration actions against unmounting while async work is pending', () => {
    const src = readFileSync(resolve(__dirname, '../SettingsPage.tsx'), 'utf-8');

    expect(src).toContain('mountedRef.current = false');
    expect(src).toContain('copiedResetTimerRef.current !== null');
    expect(src).toContain('actionAbortControllersRef.current');
    expect(src).toContain('if (controller.signal.aborted || !mountedRef.current) return;');
  });
});
