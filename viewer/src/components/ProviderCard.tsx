import { useCallback, useEffect, useRef, useState } from 'react';
import type { ProviderSummary } from '../api/config';
import type { ProviderCreateInput, ProviderUpdateInput, TaskInfoResponse } from '../api/types';
import { getTask } from '../api/tasks';
import { discoverModels, fetchProviderModels, saveProviderModels } from '../api/providers';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import './ProviderCard.css';

const PROVIDER_CLASSES = [
  'openai',
  'openai_responses',
  'gemini',
  'anthropic',
  'azure',
  'newapi',
  'ollama',
  'lmstudio',
] as const;

type ProviderClass = (typeof PROVIDER_CLASSES)[number];

interface DraftFields {
  alias: string;
  provider_class: string;
  model_name: string;
  base_url: string;
  api_key_env: string;
  max_output_tokens: string;
  thinking_level: string;
}

export interface ProviderCardProps {
  provider: ProviderSummary;
  isNew?: boolean;
  onSave: (alias: string, data: ProviderUpdateInput | ProviderCreateInput) => Promise<void>;
  onDelete: (alias: string) => Promise<void>;
  onProbe: (alias: string) => Promise<string | null>;
  onCancelNew?: () => void;
}

const DEFAULT_DRAFT: DraftFields = {
  alias: '',
  provider_class: 'openai',
  model_name: '',
  base_url: '',
  api_key_env: '',
  max_output_tokens: '',
  thinking_level: 'none',
};

interface ProviderExample {
  base_url: string;
  model_name: string;
  api_key: string;
}

const PROVIDER_EXAMPLES: Record<string, ProviderExample> = {
  openai: {
    base_url: 'https://api.openai.com/v1',
    model_name: 'gpt-5.5',
    api_key: 'sk-... or OPENAI_API_KEY',
  },
  openai_responses: {
    base_url: 'https://api.openai.com/v1',
    model_name: 'gpt-5.5',
    api_key: 'sk-... or OPENAI_API_KEY',
  },
  gemini: {
    base_url: 'https://generativelanguage.googleapis.com',
    model_name: 'gemini-3.1-pro-preview',
    api_key: 'AIza... or GEMINI_API_KEY',
  },
  anthropic: {
    base_url: 'https://api.anthropic.com',
    model_name: 'claude-opus-4-6',
    api_key: 'sk-ant-... or ANTHROPIC_API_KEY',
  },
  azure: {
    base_url: 'https://{resource}.openai.azure.com',
    model_name: 'gpt-5.5',
    api_key: 'AZURE_OPENAI_API_KEY',
  },
  newapi: {
    base_url: 'https://api.newapi.com/v1',
    model_name: 'gpt-5.5',
    api_key: 'sk-...',
  },
  ollama: {
    base_url: 'http://localhost:11434',
    model_name: 'qwen3.6-27b',
    api_key: '(optional)',
  },
  lmstudio: {
    base_url: 'http://localhost:1234/v1',
    model_name: 'qwen3.6-27b',
    api_key: 'lm-studio',
  },
};

const DEFAULT_EXAMPLE: ProviderExample = PROVIDER_EXAMPLES.openai;

type ProbeTaskFetcher = (
  taskId: string,
  opts?: { signal?: AbortSignal },
) => Promise<TaskInfoResponse>;
type PollTimer = ReturnType<typeof setTimeout>;

export interface ProviderProbePollCallbacks {
  onSuccess: () => void;
  onError: (message: string) => void;
}

export interface ProviderProbePoller {
  start: (taskId: string, callbacks: ProviderProbePollCallbacks) => void;
  cancel: () => void;
}

interface ProviderProbePollerOptions {
  delayMs?: number;
  setTimeoutFn?: (callback: () => void, delayMs: number) => PollTimer;
  clearTimeoutFn?: (timer: PollTimer) => void;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === 'AbortError'
    : error instanceof Error && error.name === 'AbortError';
}

function taskErrorMessage(info: TaskInfoResponse): string {
  return info.error ?? info.status;
}

export function createProviderProbePoller(
  fetchTask: ProbeTaskFetcher,
  {
    delayMs = 1000,
    setTimeoutFn = (callback, timeout) => setTimeout(callback, timeout),
    clearTimeoutFn = (timer) => clearTimeout(timer),
  }: ProviderProbePollerOptions = {},
): ProviderProbePoller {
  let timer: PollTimer | null = null;
  let controller: AbortController | null = null;
  let generation = 0;

  const clearTimer = () => {
    if (timer != null) {
      clearTimeoutFn(timer);
      timer = null;
    }
  };

  const cancel = () => {
    generation += 1;
    clearTimer();
    controller?.abort();
    controller = null;
  };

  const start = (taskId: string, callbacks: ProviderProbePollCallbacks) => {
    generation += 1;
    const runGeneration = generation;
    clearTimer();
    controller?.abort();
    controller = null;

    const isCurrent = () => generation === runGeneration;
    const tick = async () => {
      clearTimer();
      const currentController = new AbortController();
      controller = currentController;
      try {
        const info = await fetchTask(taskId, { signal: currentController.signal });
        if (controller === currentController) controller = null;
        if (!isCurrent()) return;

        if (info.status === 'completed') {
          callbacks.onSuccess();
          return;
        }
        if (info.status === 'failed' || info.status === 'cancelled') {
          callbacks.onError(taskErrorMessage(info));
          return;
        }
        timer = setTimeoutFn(() => void tick(), delayMs);
      } catch (error) {
        if (controller === currentController) controller = null;
        if (!isCurrent() || isAbortError(error)) return;
        callbacks.onError(error instanceof Error ? error.message : 'probe_poll_failed');
      }
    };

    void tick();
  };

  return { start, cancel };
}

function toDraft(p: ProviderSummary): DraftFields {
  return {
    alias: p.alias,
    provider_class: p.provider_class,
    model_name: p.model_name,
    base_url: p.base_url,
    api_key_env: p.api_key_env ?? '',
    max_output_tokens: p.max_output_tokens != null ? String(p.max_output_tokens) : '',
    thinking_level: p.thinking_level ?? 'none',
  };
}

export default function ProviderCard({
  provider,
  isNew = false,
  onSave,
  onDelete,
  onProbe,
  onCancelNew,
}: ProviderCardProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState<boolean>(isNew);
  const [editing, setEditing] = useState<boolean>(isNew);
  const [draft, setDraft] = useState<DraftFields>(() => (isNew ? DEFAULT_DRAFT : toDraft(provider)));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [probeTaskId, setProbeTaskId] = useState<string | null>(null);
  const [probeStatus, setProbeStatus] = useState<'idle' | 'running' | 'success' | 'error'>('idle');
  const [probeError, setProbeError] = useState<string | null>(null);
  const [remoteModels, setRemoteModels] = useState<string[] | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState<string | null>(null);
  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    new Set(provider.available_models ?? []),
  );
  const [savingModels, setSavingModels] = useState(false);
  const mountedRef = useRef(false);
  const probeRequestRef = useRef(0);
  const probePollerRef = useRef<ProviderProbePoller | null>(null);

  const getProbePoller = useCallback(() => {
    probePollerRef.current ??= createProviderProbePoller(getTask);
    return probePollerRef.current;
  }, []);

  const cancelProbePolling = useCallback(() => {
    probeRequestRef.current += 1;
    probePollerRef.current?.cancel();
  }, []);

  const isCurrentProbe = (requestId: number) =>
    mountedRef.current && probeRequestRef.current === requestId;

  // Sync external provider updates back to draft when not editing
  useEffect(() => {
    if (!editing && !isNew) {
      setDraft(toDraft(provider));
    }
  }, [provider, editing, isNew]);

  // Cleanup probe poll timer and in-flight fetches
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cancelProbePolling();
    };
  }, [cancelProbePolling]);

  useEffect(() => {
    return () => {
      cancelProbePolling();
    };
  }, [provider.alias, cancelProbePolling]);

  const headerClick = () => {
    if (editing) return;
    setExpanded((v) => !v);
  };

  const headerKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (editing) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setExpanded((v) => !v);
    }
  };

  const enterEdit = () => {
    setDraft(toDraft(provider));
    setEditing(true);
    setExpanded(true);
    setSaveError(null);
  };

  const cancelEdit = () => {
    if (isNew) {
      onCancelNew?.();
      return;
    }
    setDraft(toDraft(provider));
    setEditing(false);
    setSaveError(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const parsedMaxOutput = parseInt(draft.max_output_tokens, 10);
      const maxOutput = Number.isFinite(parsedMaxOutput) && parsedMaxOutput > 0 ? parsedMaxOutput : null;
      const thinkingLevel = draft.thinking_level === 'none' || !draft.thinking_level ? null : draft.thinking_level;
      if (isNew) {
        const payload: ProviderCreateInput = {
          alias: draft.alias.trim(),
          provider_class: draft.provider_class,
          model_name: draft.model_name.trim(),
          base_url: draft.base_url.trim(),
          api_key_env: draft.api_key_env.trim(),
          max_output_tokens: maxOutput,
          thinking_level: thinkingLevel,
        };
        await onSave(draft.alias.trim(), payload);
      } else {
        const payload: ProviderUpdateInput = {
          provider_class: draft.provider_class,
          model_name: draft.model_name.trim(),
          base_url: draft.base_url.trim(),
          api_key_env: draft.api_key_env.trim() || undefined,
          max_output_tokens: maxOutput,
          thinking_level: thinkingLevel,
        };
        await onSave(provider.alias, payload);
      }
      setEditing(false);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'save_failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteConfirmed = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(provider.alias);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : 'delete_failed');
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const handleProbe = async () => {
    cancelProbePolling();
    const requestId = probeRequestRef.current;
    setProbeStatus('running');
    setProbeError(null);
    try {
      const taskId = await onProbe(provider.alias);
      if (!isCurrentProbe(requestId)) return;
      if (taskId) {
        setProbeTaskId(taskId);
        getProbePoller().start(taskId, {
          onSuccess: () => {
            if (!isCurrentProbe(requestId)) return;
            setProbeStatus('success');
            setProbeTaskId(null);
          },
          onError: (message) => {
            if (!isCurrentProbe(requestId)) return;
            setProbeStatus('error');
            setProbeError(message);
            setProbeTaskId(null);
          },
        });
      } else {
        setProbeStatus('error');
        setProbeError('probe_no_task');
      }
    } catch (e) {
      if (!isCurrentProbe(requestId)) return;
      setProbeStatus('error');
      setProbeError(e instanceof Error ? e.message : 'probe_failed');
    }
  };

  const handleFetchModels = async () => {
    if (isNew) return;
    setFetchingModels(true);
    setFetchModelsError(null);
    try {
      const result = await fetchProviderModels(provider.alias);
      setRemoteModels(result.models);
      const existing = new Set(provider.available_models ?? []);
      setSelectedModels(existing.size > 0 ? existing : new Set(result.models));
    } catch (e) {
      setFetchModelsError(e instanceof Error ? e.message : 'fetch_failed');
    } finally {
      setFetchingModels(false);
    }
  };

  const handleSaveModels = async () => {
    if (isNew) return;
    setSavingModels(true);
    try {
      await saveProviderModels(provider.alias, [...selectedModels]);
      setRemoteModels(null);
    } catch {
      // keep panel open on error
    } finally {
      setSavingModels(false);
    }
  };

  const toggleModel = (modelId: string) => {
    setSelectedModels(prev => {
      const next = new Set(prev);
      if (next.has(modelId)) next.delete(modelId);
      else next.add(modelId);
      return next;
    });
  };

  // Determine status dot variant
  const statusVariant: 'probed' | 'not-probed' | 'missing' = (() => {
    if (provider.key_status === 'missing') return 'missing';
    if (provider.probed) return 'probed';
    return 'not-probed';
  })();

  const statusLabel = (() => {
    if (statusVariant === 'missing') return t('Settings_page.provider_status_key_missing');
    if (statusVariant === 'probed') return t('Settings_page.provider_status_probed');
    return t('Settings_page.provider_status_not_probed');
  })();

  const keyStatusLabelKey: MessageKey = provider.key_status === 'configured'
    ? 'Settings_page.key_configured'
    : provider.key_status === 'unknown'
      ? 'Settings_page.key_unknown'
      : 'Settings_page.key_missing';

  const cardClass = [
    'provider-card',
    expanded ? 'provider-card--expanded' : '',
    editing ? 'provider-card--editing' : '',
    isNew ? 'provider-card--new' : '',
  ].filter(Boolean).join(' ');

  const headerId = `provider-card-header-${isNew ? 'new' : provider.alias}`;
  const bodyId = `provider-card-body-${isNew ? 'new' : provider.alias}`;

  return (
    <div className={cardClass} data-testid={`provider-card-${isNew ? 'new' : provider.alias}`}>
      {/* Header (clickable to toggle expand, except in edit mode) */}
      <div
        className="provider-card__header"
        id={headerId}
        role={editing ? undefined : 'button'}
        tabIndex={editing ? undefined : 0}
        aria-expanded={expanded}
        aria-controls={bodyId}
        onClick={headerClick}
        onKeyDown={headerKey}
      >
        <span
          className={`provider-card__status-dot provider-card__status-dot--${statusVariant}`}
          aria-hidden="true"
          title={statusLabel}
        />
        <span className="sr-only">{statusLabel}</span>
        <div className="provider-card__header-main">
          <div className="provider-card__alias">
            {isNew ? t('Settings_page.provider_new_title') : provider.alias}
          </div>
          <div className="provider-card__header-meta">
            <span className="provider-card__badge">
              {provider.provider_class}
            </span>
            {!isNew && (
              <span className="provider-card__model">{provider.model_name}</span>
            )}
          </div>
        </div>
        {!isNew && (
          <span
            className={`provider-card__key-badge provider-card__key-badge--${provider.key_status}`}
          >
            {t(keyStatusLabelKey)}
          </span>
        )}
        {!editing && (
          <span className="provider-card__caret" aria-hidden="true">
            {expanded ? '▾' : '▸'}
          </span>
        )}
      </div>

      {/* Body (read-only details OR edit form) */}
      {expanded && (
        <div className="provider-card__body" id={bodyId} role="region" aria-labelledby={headerId}>
          {editing ? (
            <ProviderEditForm
              draft={draft}
              setDraft={setDraft}
              isNew={isNew}
              saving={saving}
              saveError={saveError}
              onSave={handleSave}
              onCancel={cancelEdit}
              t={t}
            />
          ) : (
            <ProviderDetailView
              provider={provider}
              probeStatus={probeStatus}
              probeError={probeError}
              probeRunning={probeTaskId != null || probeStatus === 'running'}
              confirmDelete={confirmDelete}
              deleting={deleting}
              deleteError={deleteError}
              onEdit={enterEdit}
              onProbe={handleProbe}
              onAskDelete={() => {
                setConfirmDelete(true);
                setDeleteError(null);
              }}
              onCancelDelete={() => setConfirmDelete(false)}
              onConfirmDelete={handleDeleteConfirmed}
              remoteModels={remoteModels}
              fetchingModels={fetchingModels}
              fetchModelsError={fetchModelsError}
              selectedModels={selectedModels}
              savingModels={savingModels}
              onFetchModels={handleFetchModels}
              onSaveModels={handleSaveModels}
              onToggleModel={toggleModel}
              onCancelModels={() => setRemoteModels(null)}
              t={t}
            />
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------- subcomponents ---------------- */

interface DetailProps {
  provider: ProviderSummary;
  probeStatus: 'idle' | 'running' | 'success' | 'error';
  probeError: string | null;
  probeRunning: boolean;
  confirmDelete: boolean;
  deleting: boolean;
  deleteError: string | null;
  onEdit: () => void;
  onProbe: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  remoteModels: string[] | null;
  fetchingModels: boolean;
  fetchModelsError: string | null;
  selectedModels: Set<string>;
  savingModels: boolean;
  onFetchModels: () => void;
  onSaveModels: () => void;
  onToggleModel: (id: string) => void;
  onCancelModels: () => void;
  t: ReturnType<typeof useTranslation>['t'];
}

function ProviderDetailView({
  provider,
  probeStatus,
  probeError,
  probeRunning,
  confirmDelete,
  deleting,
  deleteError,
  onEdit,
  onProbe,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
  remoteModels,
  fetchingModels,
  fetchModelsError,
  selectedModels,
  savingModels,
  onFetchModels,
  onSaveModels,
  onToggleModel,
  onCancelModels,
  t,
}: DetailProps) {
  return (
    <>
      <dl className="provider-card__fields">
        <Field
          label={t('Settings_page.provider_base_url_label')}
          value={provider.base_url}
          mono
        />
        <Field
          label={t('Settings_page.provider_model_name_label')}
          value={provider.model_name}
          mono
        />
        <Field
          label={t('Settings_page.provider_api_key_env_label')}
          value={provider.api_key_env ?? '—'}
          mono
        />
        {provider.max_output_tokens != null && (
          <Field label={t('Settings_page.provider_max_output_label')} value={provider.max_output_tokens.toLocaleString('en')} mono />
        )}
        {provider.thinking_level != null && provider.thinking_level !== 'none' && (
          <Field label={t('Settings_page.provider_thinking_label')} value={t(`Settings_page.provider_thinking_level_${provider.thinking_level}` as MessageKey)} mono />
        )}
      </dl>

      {provider.probed && (
        <div className="provider-card__probe-results">
          {provider.probed_max_context != null && (
            <Field
              label={t('Settings_page.provider_context_label')}
              value={`${(provider.probed_max_context / 1000).toFixed(0)}K`}
              mono
            />
          )}
          {provider.probe_timestamp && (
            <Field
              label={t('Settings_page.provider_probe_time_label')}
              value={provider.probe_timestamp}
              mono
            />
          )}
        </div>
      )}

      {/* Models section */}
      <div className="provider-card__models-section">
        <div className="provider-card__models-header">
          <span className="provider-card__models-label">
            {t('Settings_page.provider_models_label')}
            {(provider.available_models?.length ?? 0) > 0 && (
              <span className="provider-card__models-count">{provider.available_models!.length}</span>
            )}
          </span>
          <button
            type="button"
            className="provider-card__btn provider-card__btn--secondary provider-card__btn--sm"
            onClick={onFetchModels}
            disabled={fetchingModels}
          >
            {fetchingModels ? t('Settings_page.provider_models_fetching') : t('Settings_page.provider_models_fetch')}
          </button>
        </div>
        {fetchModelsError && (
          <p className="provider-card__error">{fetchModelsError}</p>
        )}
        {remoteModels && (
          <div className="provider-card__models-list">
            {remoteModels.length === 0 ? (
              <p className="provider-card__models-empty">{t('Settings_page.provider_models_empty')}</p>
            ) : (
              <>
                <div className="provider-card__models-grid">
                  {remoteModels.map(m => (
                    <label key={m} className="provider-card__model-item">
                      <input
                        type="checkbox"
                        checked={selectedModels.has(m)}
                        onChange={() => onToggleModel(m)}
                      />
                      <span className="provider-card__model-name">{m}</span>
                    </label>
                  ))}
                </div>
                <div className="provider-card__models-actions">
                  <button
                    type="button"
                    className="provider-card__btn provider-card__btn--primary provider-card__btn--sm"
                    onClick={onSaveModels}
                    disabled={savingModels || selectedModels.size === 0}
                  >
                    {savingModels ? '...' : t('Settings_page.provider_models_save')}
                  </button>
                  <button
                    type="button"
                    className="provider-card__btn provider-card__btn--sm"
                    onClick={onCancelModels}
                  >
                    {t('Settings_page.provider_models_cancel')}
                  </button>
                  <span className="provider-card__models-selected">
                    {selectedModels.size} / {remoteModels.length}
                  </span>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="provider-card__actions" role="group" aria-label={provider.alias}>
        <button type="button" className="provider-card__btn" onClick={onEdit}>
          {t('Settings_page.provider_edit')}
        </button>
        <button
          type="button"
          className="provider-card__btn provider-card__btn--secondary"
          onClick={onProbe}
          disabled={probeRunning}
        >
          {probeRunning ? (
            <>
              <span className="provider-card__probe-spinner" aria-hidden="true" />
              {t('Settings_page.provider_probe_running')}
            </>
          ) : (
            t('Settings_page.provider_probe')
          )}
        </button>
        {!confirmDelete ? (
          <button
            type="button"
            className="provider-card__btn provider-card__btn--danger"
            onClick={onAskDelete}
          >
            {t('Settings_page.provider_delete')}
          </button>
        ) : (
          <span className="provider-card__confirm-delete" role="alert">
            <span className="provider-card__confirm-delete-text">
              {t('Settings_page.provider_delete_confirm')}
            </span>
            <button
              type="button"
              className="provider-card__btn provider-card__btn--danger-solid"
              onClick={onConfirmDelete}
              disabled={deleting}
            >
              {t('Settings_page.provider_delete_yes')}
            </button>
            <button
              type="button"
              className="provider-card__btn"
              onClick={onCancelDelete}
              disabled={deleting}
            >
              {t('Settings_page.provider_delete_no')}
            </button>
          </span>
        )}
      </div>

      {probeStatus === 'success' && (
        <div className="provider-card__probe-msg provider-card__probe-msg--success" role="status">
          {t('Settings_page.provider_probe_success')}
        </div>
      )}
      {probeStatus === 'error' && (
        <div className="provider-card__probe-msg provider-card__probe-msg--error" role="alert">
          {t('Settings_page.provider_probe_error')}
          {probeError && <code className="provider-card__probe-msg-code">{probeError}</code>}
        </div>
      )}
      {deleteError && (
        <div className="provider-card__probe-msg provider-card__probe-msg--error" role="alert">
          {deleteError}
        </div>
      )}
    </>
  );
}

interface FormProps {
  draft: DraftFields;
  setDraft: React.Dispatch<React.SetStateAction<DraftFields>>;
  isNew: boolean;
  saving: boolean;
  saveError: string | null;
  onSave: () => void;
  onCancel: () => void;
  t: ReturnType<typeof useTranslation>['t'];
}

function ProviderEditForm({
  draft,
  setDraft,
  isNew,
  saving,
  saveError,
  onSave,
  onCancel,
  t,
}: FormProps) {
  const [discoveredModels, setDiscoveredModels] = useState<string[] | null>(null);
  const [discoveringModels, setDiscoveringModels] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const handleDiscoverModels = async () => {
    if (!draft.base_url.trim() || !draft.api_key_env.trim()) return;
    setDiscoveringModels(true);
    setDiscoverError(null);
    try {
      const result = await discoverModels({
        base_url: draft.base_url.trim(),
        api_key: draft.api_key_env.trim(),
        provider_class: draft.provider_class,
      });
      setDiscoveredModels(result.models);
      if (result.models.length > 0 && !draft.model_name.trim()) {
        setDraft(prev => ({ ...prev, model_name: result.models[0] }));
      }
    } catch (e) {
      setDiscoverError(e instanceof Error ? e.message : 'fetch_failed');
    } finally {
      setDiscoveringModels(false);
    }
  };

  const setField = <K extends keyof DraftFields>(key: K, value: DraftFields[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const example = PROVIDER_EXAMPLES[draft.provider_class] ?? DEFAULT_EXAMPLE;
  const aliasInvalid = isNew && draft.alias.trim() === '';
  const modelInvalid = draft.model_name.trim() === '';
  const baseInvalid = draft.base_url.trim() === '';
  const canSave = !saving && !aliasInvalid && !modelInvalid && !baseInvalid;

  return (
    <form
      className="provider-card__form"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSave) onSave();
      }}
    >
      {isNew && (
        <div className="provider-card__form-row">
          <label className="provider-card__form-label" htmlFor="provider-alias-input">
            {t('Settings_page.provider_alias_label')}
          </label>
          <input
            id="provider-alias-input"
            type="text"
            className="provider-card__input"
            value={draft.alias}
            onChange={(e) => setField('alias', e.target.value)}
            placeholder="my-provider"
            required
            aria-invalid={aliasInvalid}
            autoFocus
          />
        </div>
      )}

      <div className="provider-card__form-row">
        <label
          className="provider-card__form-label"
          htmlFor={`provider-class-${isNew ? 'new' : draft.alias}`}
        >
          {t('Settings_page.provider_class_label')}
        </label>
        <select
          id={`provider-class-${isNew ? 'new' : draft.alias}`}
          className="provider-card__select"
          value={draft.provider_class}
          onChange={(e) => setField('provider_class', e.target.value as ProviderClass)}
        >
          {PROVIDER_CLASSES.map((cls) => (
            <option key={cls} value={cls}>
              {cls}
            </option>
          ))}
        </select>
      </div>

      <div className="provider-card__form-row">
        <label
          className="provider-card__form-label"
          htmlFor={`provider-model-${isNew ? 'new' : draft.alias}`}
        >
          {t('Settings_page.provider_model_name_label')}
        </label>
        <div className="provider-card__model-discover">
          {discoveredModels && discoveredModels.length > 0 ? (
            <select
              id={`provider-model-${isNew ? 'new' : draft.alias}`}
              className="provider-card__select"
              value={draft.model_name}
              onChange={(e) => setField('model_name', e.target.value)}
            >
              {!discoveredModels.includes(draft.model_name) && draft.model_name && (
                <option value={draft.model_name}>{draft.model_name}</option>
              )}
              {discoveredModels.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          ) : (
            <input
              id={`provider-model-${isNew ? 'new' : draft.alias}`}
              type="text"
              className="provider-card__input"
              value={draft.model_name}
              onChange={(e) => setField('model_name', e.target.value)}
              placeholder={example.model_name}
              required
              aria-invalid={modelInvalid}
            />
          )}
          <button
            type="button"
            className="provider-card__btn provider-card__btn--secondary provider-card__btn--sm"
            onClick={handleDiscoverModels}
            disabled={discoveringModels || !draft.base_url.trim() || !draft.api_key_env.trim()}
            title={t('Settings_page.provider_models_fetch')}
          >
            {discoveringModels ? '…' : '↻'}
          </button>
        </div>
        {discoverError && <p className="provider-card__error provider-card__error--sm">{discoverError}</p>}
      </div>

      <div className="provider-card__form-row">
        <label
          className="provider-card__form-label"
          htmlFor={`provider-baseurl-${isNew ? 'new' : draft.alias}`}
        >
          {t('Settings_page.provider_base_url_label')}
        </label>
        <input
          id={`provider-baseurl-${isNew ? 'new' : draft.alias}`}
          type="text"
          className="provider-card__input"
          value={draft.base_url}
          onChange={(e) => setField('base_url', e.target.value)}
          placeholder={example.base_url}
          required
          aria-invalid={baseInvalid}
        />
      </div>

      <div className="provider-card__form-row">
        <label
          className="provider-card__form-label"
          htmlFor={`provider-keyenv-${isNew ? 'new' : draft.alias}`}
        >
          {t('Settings_page.provider_api_key_env_label')}
        </label>
        <input
          id={`provider-keyenv-${isNew ? 'new' : draft.alias}`}
          type="text"
          className="provider-card__input"
          value={draft.api_key_env}
          onChange={(e) => setField('api_key_env', e.target.value)}
          placeholder={example.api_key}
        />
      </div>

      <div className="provider-card__form-row">
        <label
          className="provider-card__form-label"
          htmlFor={`provider-maxout-${isNew ? 'new' : draft.alias}`}
        >
          {t('Settings_page.provider_max_output_label')}
        </label>
        <input
          id={`provider-maxout-${isNew ? 'new' : draft.alias}`}
          type="number"
          className="provider-card__input"
          value={draft.max_output_tokens}
          onChange={(e) => setField('max_output_tokens', e.target.value)}
          placeholder="4096"
          min={1}
        />
      </div>

      <div className="provider-card__form-row">
        <label
          className="provider-card__form-label"
          htmlFor={`provider-thinking-${isNew ? 'new' : draft.alias}`}
        >
          {t('Settings_page.provider_thinking_label')}
        </label>
        <select
          id={`provider-thinking-${isNew ? 'new' : draft.alias}`}
          className="provider-card__select"
          value={draft.thinking_level}
          onChange={(e) => setField('thinking_level', e.target.value)}
        >
          <option value="none">{t('Settings_page.provider_thinking_level_none')}</option>
          <option value="low">{t('Settings_page.provider_thinking_level_low')}</option>
          <option value="medium">{t('Settings_page.provider_thinking_level_medium')}</option>
          <option value="high">{t('Settings_page.provider_thinking_level_high')}</option>
        </select>
      </div>

      {saveError && (
        <div className="provider-card__probe-msg provider-card__probe-msg--error" role="alert">
          {saveError}
        </div>
      )}

      <div className="provider-card__actions">
        <button
          type="submit"
          className="provider-card__btn provider-card__btn--primary"
          disabled={!canSave}
        >
          {saving ? t('Settings_page.capture_saving') : t('Settings_page.provider_save')}
        </button>
        <button
          type="button"
          className="provider-card__btn"
          onClick={onCancel}
          disabled={saving}
        >
          {t('Settings_page.provider_cancel')}
        </button>
      </div>
    </form>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="provider-card__field">
      <dt className="provider-card__field-label">{label}</dt>
      <dd className={`provider-card__field-value${mono ? ' provider-card__field-value--mono' : ''}`}>
        {value}
      </dd>
    </div>
  );
}
