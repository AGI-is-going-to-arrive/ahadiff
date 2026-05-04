import { useCallback, useEffect, useRef, useState } from 'react';
import type { ProviderSummary } from '../api/config';
import type { ProviderCreateInput, ProviderUpdateInput, TaskInfoResponse } from '../api/types';
import { getTask } from '../api/tasks';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import './ProviderCard.css';

const PROVIDER_CLASSES = [
  'openai',
  'openai_responses',
  'gemini',
  'anthropic',
  'azure',
  'newapi',
  'cherryin',
  'ollama',
] as const;

type ProviderClass = (typeof PROVIDER_CLASSES)[number];

interface DraftFields {
  alias: string;
  provider_class: string;
  model_name: string;
  base_url: string;
  api_key_env: string;
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
};

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
      if (isNew) {
        const payload: ProviderCreateInput = {
          alias: draft.alias.trim(),
          provider_class: draft.provider_class,
          model_name: draft.model_name.trim(),
          base_url: draft.base_url.trim(),
          api_key_env: draft.api_key_env.trim(),
        };
        await onSave(draft.alias.trim(), payload);
      } else {
        const payload: ProviderUpdateInput = {
          provider_class: draft.provider_class,
          model_name: draft.model_name.trim(),
          base_url: draft.base_url.trim(),
          api_key_env: draft.api_key_env.trim() || undefined,
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
          {provider.probed_tpm != null && (
            <Field
              label={t('Settings_page.provider_tpm_label')}
              value={provider.probed_tpm.toLocaleString('en')}
              mono
            />
          )}
          {provider.probed_rpm != null && (
            <Field
              label={t('Settings_page.provider_rpm_label')}
              value={provider.probed_rpm.toLocaleString('en')}
              mono
            />
          )}
          {provider.supports_temperature != null && (
            <Field
              label={t('Settings_page.provider_temperature_label')}
              value={provider.supports_temperature ? t('Settings_page.switch_on') : t('Settings_page.switch_off')}
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
  const setField = <K extends keyof DraftFields>(key: K, value: DraftFields[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

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
        <input
          id={`provider-model-${isNew ? 'new' : draft.alias}`}
          type="text"
          className="provider-card__input"
          value={draft.model_name}
          onChange={(e) => setField('model_name', e.target.value)}
          required
          aria-invalid={modelInvalid}
        />
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
          placeholder="MY_API_KEY"
        />
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
