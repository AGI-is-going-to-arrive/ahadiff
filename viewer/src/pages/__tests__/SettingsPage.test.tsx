import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ConfigResponse, ProviderSummary } from '../../api/config';
import { quizConfigSchema, configResponseSchema, configUpdateResponseSchema } from '../../api/schemas';
import {
  buildProviderConfigUpdatePayload,
  clampQuizCountInput,
  effectiveModelProvider,
  isPreferencesFormDirty,
  modelOptionsForProvider,
  nextModelForProviderSelection,
  preferencesFormFromConfig,
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
      quiz_question_count_mode: 'fixed',
      quiz_auto_range_min: 3,
      quiz_auto_range_max: 8,
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

describe('PreferencesTab quiz count adaptive mode', () => {
  it('schema accepts new adaptive fields with valid defaults', () => {
    const parsed = quizConfigSchema.parse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'fixed',
      quiz_auto_range_min: 3,
      quiz_auto_range_max: 8,
    });
    expect(parsed.quiz_question_count_mode).toBe('fixed');
    expect(parsed.quiz_auto_range_min).toBe(3);
    expect(parsed.quiz_auto_range_max).toBe(8);
  });

  it('schema accepts auto mode with custom range', () => {
    const parsed = quizConfigSchema.parse({
      quiz_question_count: 5,
      quiz_question_count_mode: 'auto',
      quiz_auto_range_min: 2,
      quiz_auto_range_max: 7,
    });
    expect(parsed.quiz_question_count_mode).toBe('auto');
    expect(parsed.quiz_auto_range_min).toBe(2);
    expect(parsed.quiz_auto_range_max).toBe(7);
  });

  it('schema applies defaults when fields are omitted', () => {
    const parsed = quizConfigSchema.parse({ quiz_question_count: 4 });
    expect(parsed.quiz_question_count_mode).toBe('fixed');
    expect(parsed.quiz_auto_range_min).toBe(3);
    expect(parsed.quiz_auto_range_max).toBe(8);
  });

  it('schema rejects invalid mode values', () => {
    const result = quizConfigSchema.safeParse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'random',
      quiz_auto_range_min: 3,
      quiz_auto_range_max: 8,
    });
    expect(result.success).toBe(false);
  });

  it('schema rejects out-of-range auto bounds (>10 / <1)', () => {
    const tooHigh = quizConfigSchema.safeParse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'auto',
      quiz_auto_range_min: 3,
      quiz_auto_range_max: 11,
    });
    expect(tooHigh.success).toBe(false);

    const tooLow = quizConfigSchema.safeParse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'auto',
      quiz_auto_range_min: 0,
      quiz_auto_range_max: 8,
    });
    expect(tooLow.success).toBe(false);
  });

  it('schema rejects min > max via refine guard', () => {
    const inverted = quizConfigSchema.safeParse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'auto',
      quiz_auto_range_min: 8,
      quiz_auto_range_max: 3,
    });
    expect(inverted.success).toBe(false);
    if (!inverted.success) {
      expect(inverted.error.issues.some(i => i.message.includes('<='))).toBe(true);
    }
  });

  it('schema strict() rejects unknown extra fields', () => {
    const withExtra = quizConfigSchema.safeParse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'fixed',
      quiz_auto_range_min: 3,
      quiz_auto_range_max: 8,
      unexpected_field: true,
    });
    expect(withExtra.success).toBe(false);
  });

  it('config response schema rejects unknown top-level fields', () => {
    const withExtra = configResponseSchema.safeParse({
      lang: 'en',
      privacy_mode: 'strict_local',
      generate_model: 'gpt-5.5',
      judge_model: 'gpt-5.5',
      serve_port: 8765,
      capture: {
        max_files: 30,
        hard_limit: 3000,
        max_patch_bytes: 5_000_000,
        file_ranking: 'learning_value',
      },
      llm: {
        input_token_budget: 200_000,
        output_token_budget: 50_000,
        request_timeout_seconds: 30,
        max_concurrent: 3,
        retry_attempts: 3,
      },
      learn: {},
      quiz: {
        quiz_question_count: 3,
        quiz_question_count_mode: 'fixed',
        quiz_auto_range_min: 3,
        quiz_auto_range_max: 8,
      },
      unexpected_field: true,
    });
    expect(withExtra.success).toBe(false);
  });

  it('config update response schema rejects unknown top-level fields', () => {
    expect(configUpdateResponseSchema.safeParse({
      updated: true,
      scope: 'session',
      extra: true,
    }).success).toBe(false);
  });

  it('schema accepts min == max as valid (boundary case)', () => {
    const equal = quizConfigSchema.safeParse({
      quiz_question_count: 3,
      quiz_question_count_mode: 'auto',
      quiz_auto_range_min: 5,
      quiz_auto_range_max: 5,
    });
    expect(equal.success).toBe(true);
  });

  it('config response schema fills quiz adaptive defaults when quiz block is absent', () => {
    const minimal = configResponseSchema.parse({
      lang: 'en',
      privacy_mode: 'strict_local',
      generate_model: 'gpt-5.5',
      judge_model: 'gpt-5.5',
      serve_port: 8765,
      capture: {
        max_files: 30,
        hard_limit: 3000,
        max_patch_bytes: 5_000_000,
        file_ranking: 'learning_value',
      },
      llm: {
        input_token_budget: 200_000,
        output_token_budget: 50_000,
        request_timeout_seconds: 30,
        max_concurrent: 3,
        retry_attempts: 3,
      },
      learn: {},
    });
    expect(minimal.quiz.quiz_question_count_mode).toBe('fixed');
    expect(minimal.quiz.quiz_auto_range_min).toBe(3);
    expect(minimal.quiz.quiz_auto_range_max).toBe(8);
  });

  it('clamps quiz number inputs to integer range before saving', () => {
    expect(clampQuizCountInput('2.5', 3)).toBe(3);
    expect(clampQuizCountInput('2.4', 3)).toBe(2);
    expect(clampQuizCountInput('', 8)).toBe(8);
    expect(clampQuizCountInput('999', 3)).toBe(10);
    expect(clampQuizCountInput('-2', 3)).toBe(1);
    expect(clampQuizCountInput('NaN', 3)).toBe(3);
  });

  it('PreferencesTab source renders segmented mode buttons with ARIA semantics', () => {
    const src = readFileSync(resolve(__dirname, '../SettingsPage.tsx'), 'utf-8');

    // Toggle button group wrapper (W3C pattern: role="group" + aria-pressed buttons)
    expect(src).toContain("role=\"group\"");
    expect(src).toContain("aria-label={t('Settings_page.quiz_mode')}");

    // Both mode buttons with aria-pressed
    expect(src).toContain("aria-pressed={form.quiz_question_count_mode === 'fixed'}");
    expect(src).toContain("aria-pressed={form.quiz_question_count_mode === 'auto'}");

    // Mode toggle handlers
    expect(src).toContain("setField('quiz_question_count_mode', 'fixed')");
    expect(src).toContain("setField('quiz_question_count_mode', 'auto')");
  });

  it('PreferencesTab source conditionally renders fixed input vs auto-range UI', () => {
    const src = readFileSync(resolve(__dirname, '../SettingsPage.tsx'), 'utf-8');

    // Conditional render based on mode
    expect(src).toContain("form.quiz_question_count_mode === 'fixed' ? (");

    // Auto-range descriptor + min/max inputs
    expect(src).toContain("settings-auto-range__desc");
    expect(src).toContain("t('Settings_page.quiz_auto_min')");
    expect(src).toContain("t('Settings_page.quiz_auto_max')");

    // min/max inputs have aria-label (a11y)
    expect(src).toContain("aria-label={t('Settings_page.quiz_auto_min')}");
    expect(src).toContain("aria-label={t('Settings_page.quiz_auto_max')}");
    expect(src).toContain('step={1}');
  });

  it('PreferencesTab source clamps auto-range so min <= max bidirectionally', () => {
    const src = readFileSync(resolve(__dirname, '../SettingsPage.tsx'), 'utf-8');

    // Raising min above max bumps max
    expect(src).toContain("if (v > form.quiz_auto_range_max)");
    expect(src).toContain("setField('quiz_auto_range_max', v);");

    // Lowering max below min drops min
    expect(src).toContain("if (v < form.quiz_auto_range_min)");
    expect(src).toContain("setField('quiz_auto_range_min', v);");
  });

  it('PreferencesTab source sends all 4 quiz fields in save payload', () => {
    const src = readFileSync(resolve(__dirname, '../SettingsPage.tsx'), 'utf-8');

    expect(src).toContain('quiz_question_count: form.quiz_question_count');
    expect(src).toContain('quiz_question_count_mode: form.quiz_question_count_mode');
    expect(src).toContain('quiz_auto_range_min: form.quiz_auto_range_min');
    expect(src).toContain('quiz_auto_range_max: form.quiz_auto_range_max');
  });

  it('PreferencesTab source includes new fields in dirty check', () => {
    const src = readFileSync(resolve(__dirname, '../SettingsPage.tsx'), 'utf-8');

    expect(src).toContain('isPreferencesFormDirty(form, config)');
  });

  it('marks preferences dirty when adaptive quiz fields change from defaults', () => {
    const config = makeConfig();
    const form = preferencesFormFromConfig(config);

    expect(isPreferencesFormDirty(form, config)).toBe(false);
    expect(isPreferencesFormDirty({ ...form, quiz_question_count_mode: 'auto' }, config)).toBe(true);
    expect(isPreferencesFormDirty({ ...form, quiz_auto_range_min: 4 }, config)).toBe(true);
    expect(isPreferencesFormDirty({ ...form, quiz_auto_range_max: 9 }, config)).toBe(true);
  });
});
