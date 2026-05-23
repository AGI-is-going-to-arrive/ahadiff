import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ProviderCard, {
  ProviderDetailView,
  createProviderProbePoller,
  providerLimitsSourceLabel,
  providerLimitsWarningMessage,
  providerThinkingHintKey,
  shouldShowRecommendedLimitAction,
} from '../ProviderCard';
import type { ProviderSummary } from '../../api/config';
import type { TaskInfoResponse } from '../../api/types';

let mockLocale = 'en-US';

vi.mock('../../i18n/useTranslation', () => ({
  useTranslation: () => ({
    locale: mockLocale,
    t: (key: string) => {
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
      };
      return messages[key] ?? key;
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
});
