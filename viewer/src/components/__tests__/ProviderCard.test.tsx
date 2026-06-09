import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ProviderCard, {
  ProviderDetailView,
  ProviderVerificationNotice,
  createProviderProbePoller,
  providerLimitsSourceLabel,
  providerLimitsWarningMessage,
  providerThinkingHintKey,
  shouldShowRecommendedLimitAction,
  buildProviderUpdatePayload,
  ProviderEditForm,
  PROVIDER_ERROR_KEY_BY_CODE,
} from '../ProviderCard';
import type { ProviderSummary } from '../../api/config';
import type { TaskInfoResponse } from '../../api/types';

let mockLocale = 'en-US';

vi.mock('../../i18n/useTranslation', () => ({
  useTranslation: () => ({
    locale: mockLocale,
    t: (key: string, params?: Record<string, string | number>) => {
      const messages: Record<string, string> = {
        'Settings_page.key_configured': 'configured',
        'Settings_page.key_missing': 'not set',
        'Settings_page.key_unknown': 'unknown',
        'Settings_page.provider_status_key_missing': 'Key missing',
        'Settings_page.provider_status_not_probed': 'Not probed',
        'Settings_page.provider_status_probed': 'Probed',
        'Settings_page.provider_limits_source': 'Limits source',
        'Settings_page.provider_limits_source_fallback': 'Fallback probe',
        'Settings_page.provider_context_label': 'Context Length',
        'Settings_page.provider_model_limits_name': 'Limits profile',
        'Settings_page.provider_limits_warning_route_specific': 'Route-specific limits can vary.',
        'Settings_page.provider_limits_warning_unknown': 'Limits could not be verified.',
        'Settings_page.provider_thinking_hint_gemini': 'Gemini hint',
        'Settings_page.provider_api_key_hint': 'stored in local {location}',
        'Settings_page.provider_api_key_location_repo': 'repo-env',
        'Settings_page.provider_api_key_location_global': 'global-env',
        'Settings_page.provider_api_key_keep_ph': 'leave blank to keep',
        'Settings_page.provider_verify_ok': 'verified ok',
        'Settings_page.provider_verify_failed': 'verify failed',
        'Settings_page.provider_scope_label': 'Scope',
        'Settings_page.provider_scope_repo': 'This repo',
        'Settings_page.provider_scope_global': 'All repos (global)',
        'Settings_page.provider_scope_hint': 'Choose scope',
        'Settings_page.provider_scope_global_badge': 'From global config',
        'Settings_page.provider_scope_global_hint_override': 'override locally',
      };
      const template = messages[key] ?? key;
      if (!params) return template;
      return template.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`));
    },
  }),
}));

function makeProvider(overrides: Partial<ProviderSummary> = {}): ProviderSummary {
  return {
    alias: 'local',
    role: null,
    provider_class: 'openai',
    provider_kind: 'openai',
    model_name: 'gpt-test',
    base_url: 'https://api.example.test/v1',
    api_key_env: 'TEST_API_KEY',
    key_status: 'configured',
    api_family: null,
    api_family_version: null,
    probed: false,
    probed_max_context: null,
    probed_tpm: null,
    probed_rpm: null,
    probe_timestamp: null,
    scope: 'repo',
    ...overrides,
  };
}

function makeTask(overrides: Partial<TaskInfoResponse> = {}): TaskInfoResponse {
  return {
    task_id: 'task-1',
    task_type: 'provider_probe',
    status: 'running',
    progress: { current: 0, total: 1, message: '', step_started_at: '' },
    result_summary: null,
    error: null,
    error_code: null,
    created_at: '2026-05-04T00:00:00Z',
    started_at: null,
    completed_at: null,
    elapsed_seconds: null,
    recovery_hint: null,
    ...overrides,
  };
}

describe('createProviderProbePoller', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('aborts in-flight probe polling and stops later polls after cleanup', async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const fetchTask = vi.fn(
      (_taskId: string, opts?: { signal?: AbortSignal }) =>
        new Promise<TaskInfoResponse>((_resolve, reject) => {
          if (opts?.signal) {
            signals.push(opts.signal);
            opts.signal.addEventListener(
              'abort',
              () => reject(new DOMException('The operation was aborted.', 'AbortError')),
              { once: true },
            );
          }
        }),
    );
    const onSuccess = vi.fn();
    const onError = vi.fn();
    const poller = createProviderProbePoller(fetchTask, { delayMs: 1000 });

    poller.start('task-1', { onSuccess, onError });
    expect(fetchTask).toHaveBeenCalledTimes(1);
    expect(signals).toHaveLength(1);

    poller.cancel();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1200);

    expect(signals[0]?.aborted).toBe(true);
    expect(fetchTask).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
  });

  it('polls again while the task is still running', async () => {
    vi.useFakeTimers();
    const fetchTask = vi.fn(async () => makeTask());
    const poller = createProviderProbePoller(fetchTask, { delayMs: 1000 });

    poller.start('task-1', { onSuccess: vi.fn(), onError: vi.fn() });
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1000);

    expect(fetchTask).toHaveBeenCalledTimes(2);
    poller.cancel();
  });
});

describe('ProviderCard', () => {
  it.each([
    ['probed', makeProvider({ probed: true, key_status: 'configured' }), 'Probed'],
    ['not probed', makeProvider({ probed: false, key_status: 'configured' }), 'Not probed'],
    ['missing key', makeProvider({ probed: false, key_status: 'missing' }), 'Key missing'],
  ] as const)('renders sr-only status text for %s status', (_name, provider, expected) => {
    const html = renderToStaticMarkup(
      <ProviderCard
        provider={provider}
        onSave={async () => undefined}
        onDelete={async () => undefined}
        onProbe={async () => 'task-1'}
      />,
    );

    expect(html).toContain('class="sr-only"');
    expect(html).toContain(`>${expected}</span>`);
  });

  it('localizes fallback provider limit source', () => {
    const t = (key: string) => {
      const messages: Record<string, string> = {
        'Settings_page.provider_limits_source_fallback': 'Fallback probe',
      };
      return messages[key] ?? key;
    };

    const label = providerLimitsSourceLabel(t, 'fallback');

    expect(label).toBe('Fallback probe');
    expect(label).not.toBe('fallback');
  });

  it('maps provider limit warning codes through a frontend i18n allowlist', () => {
    const t = (key: string) => {
      const messages: Record<string, string> = {
        'Settings_page.provider_limits_warning_route_specific': 'Route-specific limits can vary.',
        'Settings_page.provider_limits_warning_unknown': 'Limits could not be verified.',
      };
      return messages[key] ?? key;
    };

    expect(providerLimitsWarningMessage(t, { code: 'provider_limits.route_specific', params: {} }))
      .toBe('Route-specific limits can vary.');
    expect(providerLimitsWarningMessage(t, { code: 'provider_limits.future', params: {} }))
      .toBe('Limits could not be verified.');
  });

  it('derives thinking hint keys locally instead of rendering backend key names', () => {
    expect(providerThinkingHintKey('gemini')).toBe('Settings_page.provider_thinking_hint_gemini');
    expect(providerThinkingHintKey('openai')).toBeNull();
  });

  it('only offers recommended output when a manual value differs from the known limit', () => {
    const limits = {
      max_output_known: true,
      max_output_tokens: 8192,
    };

    expect(shouldShowRecommendedLimitAction(limits, '')).toBe(false);
    expect(shouldShowRecommendedLimitAction(limits, '8192')).toBe(false);
    expect(shouldShowRecommendedLimitAction(limits, '4096')).toBe(true);
  });

  it('renders context-only fallback probe source and limits profile', () => {
    const html = renderToStaticMarkup(
      <ProviderDetailView
        provider={makeProvider({
          probed: true,
          probed_max_context: 128_000,
          probed_limits_source: 'fallback',
          model_limits_name: 'openai/gpt-5',
        })}
        probeStatus="idle"
        probeError={null}
        probeRunning={false}
        confirmDelete={false}
        deleting={false}
        deleteError={null}
        onEdit={() => undefined}
        onProbe={() => undefined}
        onAskDelete={() => undefined}
        onCancelDelete={() => undefined}
        onConfirmDelete={() => undefined}
        remoteModels={null}
        fetchingModels={false}
        fetchModelsError={null}
        selectedModels={new Set()}
        savingModels={false}
        onFetchModels={() => undefined}
        onSaveModels={() => undefined}
        onToggleModel={() => undefined}
        onCancelModels={() => undefined}
        t={(key: string) => {
          const messages: Record<string, string> = {
            'Settings_page.provider_limits_source': 'Limits source',
            'Settings_page.provider_limits_source_fallback': 'Fallback probe',
            'Settings_page.provider_context_label': 'Context Length',
            'Settings_page.provider_model_limits_name': 'Limits profile',
          };
          return messages[key] ?? key;
        }}
        locale="en-US"
      />,
    );

    expect(html).toContain('Context Length');
    expect(html).toContain('128,000');
    expect(html).toContain('Limits source');
    expect(html).toContain('Fallback probe');
    expect(html).toContain('Limits profile');
    expect(html).toContain('openai/gpt-5');
  });

  it('renders a password-type API key field with a local-storage hint when adding a provider', () => {
    const html = renderToStaticMarkup(
      <ProviderCard
        provider={makeProvider({ alias: '' })}
        isNew
        onSave={async () => undefined}
        onDelete={async () => undefined}
        onProbe={async () => 'task-1'}
      />,
    );

    expect(html).toContain('type="password"');
    expect(html).toContain('id="provider-apikey-new"');
    expect(html).toContain('stored in local repo-env');
    // The security/storage hint must be announced to screen readers on focus:
    // the API-key input is aria-describedby the hint paragraph's stable id.
    expect(html).toContain('aria-describedby="provider-apikey-hint-new"');
    expect(html).toContain('id="provider-apikey-hint-new"');
  });

  it('shows a save-time verification success notice', () => {
    const t = (key: string) =>
      (({ 'Settings_page.provider_verify_ok': 'verified ok' }) as Record<string, string>)[key] ?? key;
    const html = renderToStaticMarkup(
      <ProviderVerificationNotice verification={{ ok: true, error: null, detail: 'ok' }} t={t} />,
    );

    expect(html).toContain('verified ok');
  });

  it('shows a verification failure notice carrying the backend reason (no plaintext)', () => {
    const t = (key: string) =>
      (({ 'Settings_page.provider_verify_failed': 'verify failed' }) as Record<string, string>)[key] ?? key;
    const html = renderToStaticMarkup(
      <ProviderVerificationNotice
        verification={{ ok: false, error: 'provider_probe_failed', detail: 'ProviderError' }}
        t={t}
      />,
    );

    expect(html).toContain('verify failed');
    expect(html).toContain('provider_probe_failed');
  });

  describe('M1: max_output_tokens validation', () => {
    const defaultDraft = {
      alias: 'local',
      provider_class: 'openai',
      model_name: 'gpt-test',
      base_url: 'https://api.example.test/v1',
      api_key: '',
      max_output_tokens: '',
      thinking_level: 'none',
      model_limits_name: '',
      scope: 'repo' as const,
    };

    it('blocks saving and shows validation message for non-integer "12.5"', () => {
      const draft = { ...defaultDraft, max_output_tokens: '12.5' };
      const html = renderToStaticMarkup(
        <ProviderEditForm
          draft={draft}
          setDraft={() => {}}
          isNew={false}
          saving={false}
          saveError={null}
          onSave={() => {}}
          onCancel={() => {}}
          t={(key) => key}
          locale="en-US"
        />
      );

      // Verify that the submit button is disabled
      const submitBtnHtml = html.match(/<button type="submit"[^>]+>/)?.[0] || '';
      expect(submitBtnHtml).toContain('disabled');
      // Verify validation error is displayed
      expect(html).toContain('Settings_page.provider_max_output_invalid');
    });

    it('blocks saving and shows validation message for scientific notation "1e6"', () => {
      const draft = { ...defaultDraft, max_output_tokens: '1e6' };
      const html = renderToStaticMarkup(
        <ProviderEditForm
          draft={draft}
          setDraft={() => {}}
          isNew={false}
          saving={false}
          saveError={null}
          onSave={() => {}}
          onCancel={() => {}}
          t={(key) => key}
          locale="en-US"
        />
      );

      const submitBtnHtml = html.match(/<button type="submit"[^>]+>/)?.[0] || '';
      expect(submitBtnHtml).toContain('disabled');
      expect(html).toContain('Settings_page.provider_max_output_invalid');
    });

    it('allows valid integer "4096"', () => {
      const draft = { ...defaultDraft, max_output_tokens: '4096' };
      const html = renderToStaticMarkup(
        <ProviderEditForm
          draft={draft}
          setDraft={() => {}}
          isNew={false}
          saving={false}
          saveError={null}
          onSave={() => {}}
          onCancel={() => {}}
          t={(key) => key}
          locale="en-US"
        />
      );

      // Verify that the submit button is NOT disabled
      const submitBtnHtml = html.match(/<button type="submit"[^>]+>/)?.[0] || '';
      expect(submitBtnHtml).not.toContain('disabled');
      // Verify validation error is NOT displayed
      expect(html).not.toContain('Settings_page.provider_max_output_invalid');
    });

    it('allows empty value (clear/unset)', () => {
      const draft = { ...defaultDraft, max_output_tokens: '' };
      const html = renderToStaticMarkup(
        <ProviderEditForm
          draft={draft}
          setDraft={() => {}}
          isNew={false}
          saving={false}
          saveError={null}
          onSave={() => {}}
          onCancel={() => {}}
          t={(key) => key}
          locale="en-US"
        />
      );

      const submitBtnHtml = html.match(/<button type="submit"[^>]+>/)?.[0] || '';
      expect(submitBtnHtml).not.toContain('disabled');
      expect(html).not.toContain('Settings_page.provider_max_output_invalid');
    });

    it('blocks saving and shows validation message for "0"', () => {
      const draft = { ...defaultDraft, max_output_tokens: '0' };
      const html = renderToStaticMarkup(
        <ProviderEditForm
          draft={draft}
          setDraft={() => {}}
          isNew={false}
          saving={false}
          saveError={null}
          onSave={() => {}}
          onCancel={() => {}}
          t={(key) => key}
          locale="en-US"
        />
      );

      const submitBtnHtml = html.match(/<button type="submit"[^>]+>/)?.[0] || '';
      expect(submitBtnHtml).toContain('disabled');
      expect(html).toContain('Settings_page.provider_max_output_invalid');
    });

    it('renders max output tokens hint describing blank behavior', () => {
      const html = renderToStaticMarkup(
        <ProviderEditForm
          draft={defaultDraft}
          setDraft={() => {}}
          isNew={false}
          saving={false}
          saveError={null}
          onSave={() => {}}
          onCancel={() => {}}
          t={(key) => key}
          locale="en-US"
        />
      );

      expect(html).toContain('id="provider-maxout-hint-local"');
      expect(html).toContain('Settings_page.provider_max_output_hint');
    });

    it('buildProviderUpdatePayload clears max_output_tokens to null when blank', () => {
      const provider = makeProvider({
        max_output_tokens: 4096,
      });
      const draft = {
        alias: 'local',
        provider_class: 'openai',
        model_name: 'gpt-test',
        base_url: 'https://api.example.test/v1',
        api_key: '',
        max_output_tokens: '',
        thinking_level: 'none',
        model_limits_name: '',
        scope: 'repo' as const,
      };

      const payload = buildProviderUpdatePayload(draft, provider);
      expect(payload.max_output_tokens).toBeNull();
    });
  });

  describe('M2: buildProviderUpdatePayload identity fields diffing', () => {
    it('does not send unchanged identity fields on update', () => {
      const provider = makeProvider({
        provider_class: 'openai',
        model_name: 'gpt-test',
        base_url: 'https://api.example.test/v1',
        max_output_tokens: 4096,
      });
      const draft = {
        alias: 'local',
        provider_class: 'openai',
        model_name: 'gpt-test',
        base_url: 'https://api.example.test/v1',
        api_key: '',
        max_output_tokens: '8192',
        thinking_level: 'none',
        model_limits_name: '',
        scope: 'repo' as const,
      };

      const payload = buildProviderUpdatePayload(draft, provider);

      // Identity fields are not included because they did not change
      expect(payload.provider_class).toBeUndefined();
      expect(payload.model_name).toBeUndefined();
      expect(payload.base_url).toBeUndefined();

      // Non-identity fields / changed fields are included
      expect(payload.max_output_tokens).toBe(8192);
    });

    it('sends changed identity fields on update', () => {
      const provider = makeProvider({
        provider_class: 'openai',
        model_name: 'gpt-test',
        base_url: 'https://api.example.test/v1',
      });
      const draft = {
        alias: 'local',
        provider_class: 'anthropic',
        model_name: 'claude-3-opus',
        base_url: 'https://api.anthropic.com/v1',
        api_key: 'new-key',
        max_output_tokens: '',
        thinking_level: 'none',
        model_limits_name: '',
        scope: 'repo' as const,
      };

      const payload = buildProviderUpdatePayload(draft, provider);

      // Identity fields are included because they changed
      expect(payload.provider_class).toBe('anthropic');
      expect(payload.model_name).toBe('claude-3-opus');
      expect(payload.base_url).toBe('https://api.anthropic.com/v1');
      expect(payload.api_key).toBe('new-key');
    });
  });

  describe('PROVIDER_ERROR_KEY_BY_CODE mapping', () => {
    it('correctly maps expected backend error codes to correct translation keys', () => {
      expect(PROVIDER_ERROR_KEY_BY_CODE.INPUT_VALIDATION).toBe('Settings_page.provider_error_validation_error');
      expect(PROVIDER_ERROR_KEY_BY_CODE.INPUT_BAD_FIELD).toBe('Settings_page.provider_error_bad_field');
      expect(PROVIDER_ERROR_KEY_BY_CODE.PROVIDER_NOT_FOUND).toBe('Settings_page.provider_error_provider_not_found');
      expect(PROVIDER_ERROR_KEY_BY_CODE.AUTH_REQUIRED).toBe('Settings_page.provider_error_auth_required');
      expect(PROVIDER_ERROR_KEY_BY_CODE.LOCK_CONFLICT).toBe('Settings_page.provider_error_lock_conflict');
      expect(PROVIDER_ERROR_KEY_BY_CODE.INTERNAL_ERROR).toBe('Settings_page.provider_error_internal_error');
    });
  });

  describe('Global BYOK Scope Support', () => {
    it('defaults scope to repo in DraftFields', () => {
      const card = renderToStaticMarkup(
        <ProviderCard
          provider={makeProvider({ scope: undefined })}
          isNew
          onSave={async () => undefined}
          onDelete={async () => undefined}
          onProbe={async () => 'task-1'}
        />,
      );
      expect(card).toContain('checked');
      expect(card).toContain('This repo');
    });

    it('buildProviderUpdatePayload carries chosen scope in payload', () => {
      const provider = makeProvider({ scope: 'repo' });
      const draft = {
        alias: 'local',
        provider_class: 'openai',
        model_name: 'gpt-test',
        base_url: 'https://api.example.test/v1',
        api_key: '',
        max_output_tokens: '',
        thinking_level: 'none',
        model_limits_name: '',
        scope: 'global' as const,
      };
      const payload = buildProviderUpdatePayload(draft, provider);
      expect(payload.scope).toBe('global');
    });

    it('renders global badge and override hint when scope is global', () => {
      const html = renderToStaticMarkup(
        <ProviderDetailView
          provider={makeProvider({ scope: 'global' })}
          probeStatus="idle"
          probeError={null}
          probeRunning={false}
          confirmDelete={false}
          deleting={false}
          deleteError={null}
          onEdit={() => {}}
          onProbe={async () => 'task-1'}
          onAskDelete={() => {}}
          onCancelDelete={() => {}}
          onConfirmDelete={async () => {}}
          remoteModels={null}
          fetchingModels={false}
          fetchModelsError={null}
          selectedModels={new Set()}
          savingModels={false}
          onFetchModels={() => {}}
          onSaveModels={() => {}}
          onToggleModel={() => {}}
          onCancelModels={() => {}}
          t={(key, params) => {
            const messages: Record<string, string> = {
              'Settings_page.provider_scope_global_badge': 'From global config',
              'Settings_page.provider_scope_global_hint_override': 'override locally',
            };
            const template = messages[key] ?? key;
            if (!params) return template;
            return template.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`));
          }}
          locale="en-US"
        />,
      );
      expect(html).toContain('From global config');
      expect(html).toContain('override locally');
    });
  });
});
