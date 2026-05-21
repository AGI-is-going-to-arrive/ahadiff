import { lazy, Suspense, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import LanguageSwitcher from '../components/LanguageSwitcher';
import ProviderCard from '../components/ProviderCard';
import DiagnosticRow, { type DiagnosticStatus } from '../components/DiagnosticRow';
import { ApiError } from '../api/client';
import {
  applyInstallTarget,
  getCaptureRecommended,
  getConfig, getDoctor, getProviders, getUsage, getAudit, getInstallTargets,
  previewInstallTarget,
  putConfig,
  removeInstallTarget,
} from '../api/config';
import CaptureBudgetBar from '../components/CaptureBudgetBar';
import { buildFormatTexts, formatBytes, formatCompactNumber } from '../utils/format';
import {
  createProvider, updateProvider, deleteProvider, probeProvider,
} from '../api/providers';
import { fetchServeStatus, fetchWatchStatus } from '../api/stats';
import type {
  AuditEntry, CaptureConfig, CaptureRecommendation, ConfigResponse, DoctorCheck, LlmConfig,
  ProviderSummary, UsageResponse, AuditResponse, InstallManifestAction, InstallTarget,
} from '../api/config';
import type {
  ProviderCreateInput, ProviderUpdateInput, ServeStatusResponse, WatchStatusResponse,
} from '../api/types';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { copyToClipboard } from '../utils/clipboard';
import { mapDoctorMessage } from '../utils/doctor';
import { actionLabel, strategyLabel } from '../utils/integrationLabels';
import '../components/Settings.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));

type TabId = 'account' | 'provider' | 'capture' | 'privacy' | 'audit' | 'preferences' | 'integrations';

const TAB_IDS: TabId[] = [
  'account', 'provider', 'capture', 'privacy',
  'audit', 'preferences', 'integrations',
];

const TAB_EN: Record<TabId, string> = {
  account: 'account', provider: 'provider', capture: 'capture', privacy: 'privacy',
  audit: 'audit', preferences: 'preferences', integrations: 'guidance',
};

const TAB_LABEL_KEY: Record<TabId, MessageKey> = {
  account: 'Settings_page.tab_account',
  provider: 'Settings_page.tab_provider',
  capture: 'Settings_page.tab_capture',
  privacy: 'Settings_page.tab_privacy',
  audit: 'Settings_page.tab_audit',
  preferences: 'Settings_page.tab_preferences',
  integrations: 'Settings_page.tab_integrations',
};

const CHECK_STATUS_KEY: Record<DoctorCheck['status'], MessageKey> = {
  pass: 'Settings_page.check_pass',
  warn: 'Settings_page.check_warn',
  fail: 'Settings_page.check_fail',
};

const INTEGRATION_STATUS_KEY: Record<InstallTarget['status'], MessageKey> = {
  installed: 'Settings_page.integration_installed',
  available: 'Settings_page.integration_available',
  unsupported: 'Settings_page.integration_unsupported',
  error: 'Settings_page.integration_error',
};

const PROVIDER_SELECT_ARIA_KEY = {
  generate: 'Settings_page.generate_provider_select_aria',
  judge: 'Settings_page.judge_provider_select_aria',
} as const satisfies Record<'generate' | 'judge', MessageKey>;

const MODEL_SELECT_ARIA_KEY = {
  generate: 'Settings_page.generate_model_select_aria',
  judge: 'Settings_page.judge_model_select_aria',
} as const satisfies Record<'generate' | 'judge', MessageKey>;

type SettingsResource = 'config' | 'doctor' | 'providers' | 'usage' | 'audit' | 'installTargets';
type InstallActionKind = 'preview' | 'install' | 'uninstall';

interface InstallActionState {
  pending?: InstallActionKind;
  message?: string;
  error?: string;
  previewTarget?: InstallTarget;
  manifestHash?: string;
  previewCollapsed?: boolean;
}

interface SettingsData {
  config: ConfigResponse | null;
  checks: DoctorCheck[];
  providers: ProviderSummary[];
  usage: UsageResponse | null;
  audit: AuditResponse | null;
  installTargets: InstallTarget[];
  failed: Partial<Record<SettingsResource, boolean>>;
}

const EMPTY_DATA: SettingsData = {
  config: null,
  checks: [],
  providers: [],
  usage: null,
  audit: null,
  installTargets: [],
  failed: {},
};

type TFn = TranslateFn;

function initialSettingsTab(): TabId {
  const query = window.location.hash.split('?')[1] ?? '';
  const tab = new URLSearchParams(query).get('tab');
  return TAB_IDS.includes(tab as TabId) ? (tab as TabId) : 'privacy';
}

export default function SettingsPage() {
  const { t, locale } = useTranslation();
  const [active, setActive] = useState<TabId>(() => initialSettingsTab());
  const [data, setData] = useState<SettingsData>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [printMode, setPrintMode] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchAll = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const s = { signal: controller.signal };
      const [cfg, doc, prov, usg, aud, inst] = await Promise.allSettled([
        getConfig(s), getDoctor(s), getProviders(s),
        getUsage(s), getAudit(20, 0, s), getInstallTargets(s),
      ]);
      if (controller.signal.aborted) return;
      setData({
        config: cfg.status === 'fulfilled' ? cfg.value : null,
        checks: doc.status === 'fulfilled' ? doc.value.checks : [],
        providers: prov.status === 'fulfilled' ? prov.value.providers : [],
        usage: usg.status === 'fulfilled' ? usg.value : null,
        audit: aud.status === 'fulfilled' ? aud.value : null,
        installTargets: inst.status === 'fulfilled' ? inst.value.targets : [],
        failed: {
          config: cfg.status === 'rejected',
          doctor: doc.status === 'rejected',
          providers: prov.status === 'rejected',
          usage: usg.status === 'rejected',
          audit: aud.status === 'rejected',
          installTargets: inst.status === 'rejected',
        },
      });
    } catch (e) {
      if (controller.signal.aborted) return;
      setError(e instanceof Error ? e.message : 'fetch_failed');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  const refreshInstallTargets = useCallback(async (opts?: { signal?: AbortSignal }) => {
    const inst = await getInstallTargets(opts);
    if (opts?.signal?.aborted) return;
    setData((current) => ({
      ...current,
      installTargets: inst.targets,
      failed: {
        ...current.failed,
        installTargets: false,
      },
    }));
  }, []);

  useEffect(() => {
    void fetchAll();
    return () => abortRef.current?.abort();
  }, [fetchAll]);

  useEffect(() => {
    const syncHashTab = () => {
      const next = initialSettingsTab();
      setActive((current) => (current === next ? current : next));
    };
    window.addEventListener('hashchange', syncHashTab);
    return () => window.removeEventListener('hashchange', syncHashTab);
  }, []);

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia('print');
    const syncPrintMode = () => setPrintMode(media.matches);
    syncPrintMode();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', syncPrintMode);
      return () => media.removeEventListener('change', syncPrintMode);
    }
    media.addListener(syncPrintMode);
    return () => media.removeListener(syncPrintMode);
  }, []);

  const selectTab = useCallback((id: TabId) => {
    setActive(id);
    const [hashPath] = window.location.hash.split('?');
    if (hashPath === '#/settings' || hashPath === '') {
      window.history.replaceState(null, '', `#/settings?tab=${id}`);
    }
  }, []);

  if (loading) {
    return (
      <AppShell>
        <div className="settings" role="status" aria-label={t('A11y.loading')}>
          <div className="settings__head">
            <Skeleton variant="text" width="200px" height="2em" />
          </div>
          <SkeletonGroup count={4} variant="row" />
        </div>
      </AppShell>
    );
  }

  if (error) {
    return (
      <AppShell>
        <div className="settings">
          <div className="settings__head">
            <h1 className="settings__title">{t('Settings_page.title')}</h1>
          </div>
          <div role="alert" className="dashboard__error">
            {t('Error.fetch_failed', { resource: t('Settings_page.title') })}
            <button type="button" className="retry-btn" onClick={() => void fetchAll()}>
              {t('Error.retry')}
            </button>
          </div>
        </div>
      </AppShell>
    );
  }

  const renderTabPanel = (id: TabId) => {
    const retry = () => void fetchAll();
    switch (id) {
      case 'account':
        return (
          <AccountTab
            checks={data.checks}
            usage={data.usage}
            doctorFailed={Boolean(data.failed.doctor)}
            usageFailed={Boolean(data.failed.usage)}
            t={t}
            locale={locale}
            onRetry={retry}
          />
        );
      case 'provider':
        return (
          <ProviderTab
            config={data.config}
            providers={data.providers}
            configFailed={Boolean(data.failed.config)}
            providersFailed={Boolean(data.failed.providers)}
            t={t}
            onRetry={retry}
            onSaved={() => void fetchAll()}
          />
        );
      case 'capture':
        return (
          <CaptureTab
            config={data.config}
            failed={Boolean(data.failed.config)}
            t={t}
            locale={locale}
            onRetry={retry}
            onSaved={() => void fetchAll()}
          />
        );
      case 'privacy':
        return (
          <PrivacyTab
            config={data.config}
            failed={Boolean(data.failed.config)}
            t={t}
            onRetry={retry}
            onSaved={() => void fetchAll()}
          />
        );
      case 'audit':
        return (
          <AuditTab
            audit={data.audit}
            failed={Boolean(data.failed.audit)}
            t={t}
            locale={locale}
            onRetry={retry}
          />
        );
      case 'preferences':
        return (
          <PreferencesTab
            config={data.config}
            failed={Boolean(data.failed.config)}
            t={t}
            onRetry={retry}
            onSaved={() => void fetchAll()}
          />
        );
      case 'integrations':
        return (
          <IntegrationsTab
            targets={data.installTargets}
            failed={Boolean(data.failed.installTargets)}
            showGraphify={active === 'integrations' || printMode}
            t={t}
            onRetry={retry}
            onRefreshTargets={refreshInstallTargets}
          />
        );
      default:
        return null;
    }
  };

  return (
    <AppShell>
      <div className="settings">
        <div className="settings__head">
          <div>
            <div className="review__eyebrow">§ {t('Settings_page.title')}</div>
            <h1 className="settings__title">{t('Settings_page.title')}</h1>
            <div className="ratchet-page__sub">{t('Settings_page.subtitle')}</div>
          </div>
        </div>

        <div className="settings-layout">
          <nav className="stabs" role="tablist" aria-label={t('Settings_page.title')}>
            {TAB_IDS.map((id, idx) => (
              <button
                key={id}
                id={`stab-${id}`}
                className={`st${active === id ? ' on' : ''}`}
                role="tab"
                aria-selected={active === id}
                aria-controls={`spanel-${id}`}
                tabIndex={active === id ? 0 : -1}
                onClick={() => selectTab(id)}
                onKeyDown={(e) => {
                  let next = idx;
                  switch (e.key) {
                    case 'ArrowDown': case 'ArrowRight':
                      next = (idx + 1) % TAB_IDS.length; break;
                    case 'ArrowUp': case 'ArrowLeft':
                      next = (idx - 1 + TAB_IDS.length) % TAB_IDS.length; break;
                    case 'Home': next = 0; break;
                    case 'End': next = TAB_IDS.length - 1; break;
                    default: return;
                  }
                  e.preventDefault();
                  selectTab(TAB_IDS[next]);
                  (e.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]'))?.[next]?.focus();
                }}
              >
                {t(TAB_LABEL_KEY[id])}
                {' '}<span className="en">{TAB_EN[id]}</span>
              </button>
            ))}
          </nav>

          <div className="settings-panels">
            {TAB_IDS.map(id => (
              <div
                key={id}
                id={`spanel-${id}`}
                className={`settings-content${active === id ? '' : ' is-inactive'}`}
                role="tabpanel"
                aria-labelledby={`stab-${id}`}
                tabIndex={active === id ? 0 : undefined}
                hidden={active !== id || undefined}
              >
                {renderTabPanel(id)}
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Account                                                       */
/* ------------------------------------------------------------------ */

function AccountTab({
  checks,
  usage,
  doctorFailed,
  usageFailed,
  t,
  locale,
  onRetry,
}: {
  checks: DoctorCheck[];
  usage: UsageResponse | null;
  doctorFailed: boolean;
  usageFailed: boolean;
  t: TFn;
  locale: string;
  onRetry: () => void;
}) {
  return (
    <>
      <RuntimeStatusCard t={t} locale={locale} />

      {doctorFailed ? (
        <UnavailableCard
          title={t('Settings_page.section_doctor')}
          message={t('Settings_page.doctor_unavailable')}
          t={t}
          onRetry={onRetry}
        />
      ) : (
        <div className="settings-card">
          <div className="settings-card__header"><h2>{t('Settings_page.section_doctor')}</h2></div>
          <div className="settings-card__body">
            {checks.map(check => {
              const status: DiagnosticStatus = check.status;
              let detailText: string | null = null;
              if (check.status !== 'pass' && check.details) {
                const d = check.details;
                const keys = Array.isArray(d.keys) ? (d.keys as string[]) : [];
                const msg = typeof d.message === 'string' ? d.message : '';
                const parts: string[] = [];
                if (keys.length > 0) parts.push(keys.join(', '));
                if (msg) parts.push(msg);
                detailText = parts.length > 0 ? parts.join(' · ') : null;
              }
              return (
                <DiagnosticRow
                  key={check.name}
                  status={status}
                  text={mapDoctorMessage(check, t)}
                  details={detailText}
                  statusLabel={t(CHECK_STATUS_KEY[check.status])}
                  data-testid={`settings-doctor-check-${check.name}`}
                />
              );
            })}
            {checks.length === 0 && (
              <DiagnosticRow
                status="pending"
                text={t('Settings_page.doctor_running')}
                data-testid="settings-doctor-check-pending"
              />
            )}
          </div>
        </div>
      )}

      {usageFailed && (
        <UnavailableCard
          title={t('Settings_page.usage_title')}
          message={t('Settings_page.usage_unavailable')}
          t={t}
          onRetry={onRetry}
        />
      )}

      {!usageFailed && usage && (
        <div className="settings-card">
          <div className="settings-card__header"><h2>{t('Settings_page.usage_title')}</h2></div>
          <div className="settings-card__body">
            <div className="mode-grid">
              <ModeCell eyebrow={t('Settings_page.usage_total_calls')} value={formatNumber(usage.total_calls, locale)} />
              <ModeCell
                eyebrow={t('Settings_page.usage_total_tokens')}
                value={formatNumber(usage.total_input_tokens + usage.total_output_tokens, locale)}
              />
              <ModeCell eyebrow={t('Settings_page.usage_total_cost')} value={`$${usage.total_cost_usd.toFixed(4)}`} />
              <ModeCell
                eyebrow={t('Settings_page.usage_cache_hits')}
                value={formatNumber(usage.cache_hits, locale)}
                sub={usage.cache_hits + usage.cache_misses > 0
                  ? `${((usage.cache_hits / (usage.cache_hits + usage.cache_misses)) * 100).toFixed(0)}%`
                  : undefined}
              />
            </div>
            {usage.models && usage.models.length > 0 && (
              <details className="settings-usage__details">
                <summary>{t('Settings_page.usage_per_model')}</summary>
                <div className="settings-usage__table-wrap">
                  <table className="settings-usage__table">
                    <thead>
                      <tr>
                        <th>{t('Settings_page.usage_model')}</th>
                        <th>{t('Settings_page.usage_provider')}</th>
                        <th className="settings-usage__num">{t('Settings_page.usage_calls')}</th>
                        <th className="settings-usage__num">{t('Settings_page.usage_tokens_in')}</th>
                        <th className="settings-usage__num">{t('Settings_page.usage_tokens_out')}</th>
                        <th className="settings-usage__num">{t('Settings_page.usage_cost')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.models.map((m) => (
                        <tr key={`${m.provider_class}-${m.model_id}`}>
                          <td><code>{m.model_id}</code></td>
                          <td>{m.provider_class}</td>
                          <td className="settings-usage__num">{formatNumber(m.call_count, locale)}</td>
                          <td className="settings-usage__num">{formatNumber(m.total_input_tokens, locale)}</td>
                          <td className="settings-usage__num">{formatNumber(m.total_output_tokens, locale)}</td>
                          <td className="settings-usage__num">{`$${m.total_cost_usd.toFixed(4)}`}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Provider (merged Keys + Models + model config + LLM settings) */
/* ------------------------------------------------------------------ */

export interface ProviderForm {
  generate_provider: string;
  generate_model: string;
  judge_provider: string;
  judge_model: string;
  llm: LlmConfig;
}

const PROVIDER_LLM_CONFIG_KEYS = [
  'input_token_budget',
  'output_token_budget',
  'request_timeout_seconds',
  'max_concurrent',
  'retry_attempts',
] as const satisfies readonly (keyof LlmConfig)[];

export function modelOptionsForProvider(provider: ProviderSummary | undefined): string[] {
  if (!provider) return [];
  const availableModels = provider.available_models ?? [];
  const models = availableModels.length > 0 ? availableModels : [provider.model_name];
  return [...new Set(models.map(model => model.trim()).filter(Boolean))];
}

export function effectiveModelProvider(
  providers: ProviderSummary[],
  selectedAlias: string,
): ProviderSummary | undefined {
  if (selectedAlias) return providers.find(provider => provider.alias === selectedAlias);
  return providers.length === 1 ? providers[0] : undefined;
}

export function nextModelForProviderSelection(
  providers: ProviderSummary[],
  selectedAlias: string,
  currentModel: string,
): string {
  const modelOptions = modelOptionsForProvider(effectiveModelProvider(providers, selectedAlias));
  if (modelOptions.length === 0) return currentModel;
  return modelOptions.includes(currentModel) ? currentModel : modelOptions[0];
}

export function buildProviderConfigUpdatePayload(
  form: ProviderForm,
  config: ConfigResponse,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};

  if (form.generate_provider !== (config.generate_provider ?? '')) {
    payload.generate_provider = form.generate_provider;
  }
  if (form.generate_model !== (config.generate_model ?? '')) {
    payload.generate_model = form.generate_model;
  }
  if (form.judge_provider !== (config.judge_provider ?? '')) {
    payload.judge_provider = form.judge_provider;
  }
  if (form.judge_model !== (config.judge_model ?? '')) {
    payload.judge_model = form.judge_model;
  }

  const llm: Record<string, unknown> = {};
  for (const key of PROVIDER_LLM_CONFIG_KEYS) {
    if (form.llm[key] !== config.llm[key]) {
      llm[key] = form.llm[key];
    }
  }
  if (Object.keys(llm).length > 0) {
    payload.llm = llm;
  }

  return payload;
}

function ProviderTab({
  config,
  providers,
  configFailed,
  providersFailed,
  t,
  onRetry,
  onSaved,
}: {
  config: ConfigResponse | null;
  providers: ProviderSummary[];
  configFailed: boolean;
  providersFailed: boolean;
  t: TFn;
  onRetry: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<ProviderForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);
  const [showNewProvider, setShowNewProvider] = useState(false);

  useEffect(() => {
    if (config) {
      setForm({
        generate_provider: config.generate_provider ?? '',
        generate_model: config.generate_model ?? '',
        judge_provider: config.judge_provider ?? '',
        judge_model: config.judge_model ?? '',
        llm: { ...config.llm },
      });
    }
  }, [config]);

  const dirty = Boolean(
    config && form && Object.keys(buildProviderConfigUpdatePayload(form, config)).length > 0,
  );

  const handleSave = async () => {
    if (!form || !config) return;
    const payload = buildProviderConfigUpdatePayload(form, config);
    if (Object.keys(payload).length === 0) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await putConfig(payload);
      setSaveOk(true);
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'save failed');
    } finally {
      setSaving(false);
    }
  };

  const setField = <K extends keyof ProviderForm>(key: K, value: ProviderForm[K]) => {
    setForm(prev => prev ? { ...prev, [key]: value } : prev);
    setSaveOk(false);
  };

  const setLlmField = <K extends keyof LlmConfig>(key: K, value: LlmConfig[K]) => {
    setForm(prev => prev ? { ...prev, llm: { ...prev.llm, [key]: value } } : prev);
    setSaveOk(false);
  };

  const handleProviderSave = async (alias: string, data: ProviderUpdateInput | ProviderCreateInput) => {
    if ('alias' in data) {
      await createProvider(data);
      setShowNewProvider(false);
    } else {
      await updateProvider(alias, data);
    }
    onSaved();
  };

  const handleProviderDelete = async (alias: string) => {
    await deleteProvider(alias);
    onSaved();
  };

  const handleProviderProbe = async (alias: string): Promise<string | null> => {
    const res = await probeProvider(alias);
    return res.task_id ?? null;
  };

  // Empty placeholder ProviderSummary for the "new" card
  const newProviderSeed: ProviderSummary = {
    alias: '',
    provider_class: 'openai',
    provider_kind: 'openai',
    model_name: '',
    base_url: '',
    api_key_env: null,
    key_status: 'unknown',
    probed: false,
    probed_max_context: null,
  };

  return (
    <>
      {/* Provider grid */}
      {providersFailed ? (
        <UnavailableCard
          title={t('Settings_page.section_providers')}
          message={t('Settings_page.provider_unavailable')}
          t={t}
          onRetry={onRetry}
        />
      ) : (
        <div className="settings-card">
          <div className="settings-card__header">
            <h2>{t('Settings_page.section_providers')}</h2>
            {!showNewProvider && (
              <button
                type="button"
                className="retry-btn"
                onClick={() => setShowNewProvider(true)}
              >
                {t('Settings_page.provider_add')}
              </button>
            )}
          </div>
          <div className="settings-card__body">
            {providers.length === 0 && !showNewProvider && (
              <div className="u-muted-sm">{t('Settings_page.provider_empty')}</div>
            )}
            <div className="provider-grid">
              {showNewProvider && (
                <ProviderCard
                  key="__new__"
                  provider={newProviderSeed}
                  isNew
                  onSave={handleProviderSave}
                  onDelete={handleProviderDelete}
                  onProbe={handleProviderProbe}
                  onCancelNew={() => setShowNewProvider(false)}
                />
              )}
              {providers.map(p => (
                <ProviderCard
                  key={p.alias}
                  provider={p}
                  onSave={handleProviderSave}
                  onDelete={handleProviderDelete}
                  onProbe={handleProviderProbe}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Model selection */}
      {configFailed || !config || !form ? (
        <UnavailableCard
          title={t('Settings_page.section_model_selection')}
          message={t('Settings_page.config_unavailable')}
          t={t}
          onRetry={onRetry}
        />
      ) : (
        <>
          <div className="settings-card">
            <div className="settings-card__header"><h2>{t('Settings_page.section_model_selection')}</h2></div>
            <div className="settings-card__body">
              {(['generate', 'judge'] as const).map(role => {
                const providerKey = `${role}_provider` as keyof ProviderForm;
                const modelKey = `${role}_model` as keyof ProviderForm;
                const selectedAlias = form[providerKey] as string;
                const selectedProvider = effectiveModelProvider(providers, selectedAlias);
                const modelOptions = modelOptionsForProvider(selectedProvider);
                const currentModel = form[modelKey] as string;
                return (
                  <div className="settings-field" key={role}>
                    <div className="settings-field__label">
                      <h3>{t(`Settings_page.${role}_model`)}</h3>
                      <p>{t(`Settings_page.${role}_model_desc`)}</p>
                    </div>
                    <div className="settings-model-select">
                      <select
                        className="settings-select"
                        aria-label={t(PROVIDER_SELECT_ARIA_KEY[role])}
                        value={selectedAlias}
                        onChange={e => {
                          const alias = e.target.value;
                          setField(providerKey, alias as ProviderForm[typeof providerKey]);
                          const nextModel = nextModelForProviderSelection(
                            providers,
                            alias,
                            currentModel,
                          );
                          if (nextModel !== currentModel) {
                            setField(modelKey, nextModel as ProviderForm[typeof modelKey]);
                          }
                        }}
                      >
                        <option value="">{t('Settings_page.provider_auto')}</option>
                        {providers.map(p => (
                          <option key={p.alias} value={p.alias}>
                            {p.alias} ({p.provider_class})
                          </option>
                        ))}
                      </select>
                      {modelOptions.length > 0 ? (
                        <select
                          className="settings-select settings-select--model"
                          aria-label={t(MODEL_SELECT_ARIA_KEY[role])}
                          value={currentModel}
                          onChange={e => setField(modelKey, e.target.value as ProviderForm[typeof modelKey])}
                        >
                          {!modelOptions.includes(currentModel) && currentModel && (
                            <option value={currentModel}>{currentModel}</option>
                          )}
                          {!currentModel && (
                            <option value="" disabled>{t('Settings_page.model_name_placeholder')}</option>
                          )}
                          {modelOptions.map(m => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          className="settings-input settings-input--model"
                          aria-label={t(MODEL_SELECT_ARIA_KEY[role])}
                          value={currentModel}
                          onChange={e => setField(modelKey, e.target.value as ProviderForm[typeof modelKey])}
                          placeholder={t('Settings_page.model_name_placeholder')}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="settings-card">
            <div className="settings-card__header"><h2>{t('Settings_page.section_llm')}</h2></div>
            <div className="settings-card__body">
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.llm_input_token_budget')}</h3>
                  <p>{t('Settings_page.llm_input_token_budget_desc')}</p>
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.llm_input_token_budget')}
                  min={1000}
                  max={10000000}
                  step={10000}
                  value={form.llm.input_token_budget}
                  onChange={e => setLlmField('input_token_budget', Math.max(1000, Math.min(10000000, Number(e.target.value) || 1000)))}
                />
              </div>
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.llm_output_token_budget')}</h3>
                  <p>{t('Settings_page.llm_output_token_budget_desc')}</p>
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.llm_output_token_budget')}
                  min={1000}
                  max={10000000}
                  step={10000}
                  value={form.llm.output_token_budget}
                  onChange={e => setLlmField('output_token_budget', Math.max(1000, Math.min(10000000, Number(e.target.value) || 1000)))}
                />
              </div>
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.llm_timeout')}</h3>
                  <p>{t('Settings_page.llm_timeout_desc')}</p>
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.llm_timeout')}
                  min={5}
                  max={600}
                  value={form.llm.request_timeout_seconds}
                  onChange={e => setLlmField('request_timeout_seconds', Math.max(5, Math.min(600, Number(e.target.value) || 5)))}
                />
              </div>
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.llm_max_concurrent')}</h3>
                  <p>{t('Settings_page.llm_max_concurrent_desc')}</p>
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.llm_max_concurrent')}
                  min={1}
                  max={20}
                  value={form.llm.max_concurrent}
                  onChange={e => setLlmField('max_concurrent', Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
                />
              </div>
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.llm_retry_attempts')}</h3>
                  <p>{t('Settings_page.llm_retry_attempts_desc')}</p>
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.llm_retry_attempts')}
                  min={0}
                  max={10}
                  value={form.llm.retry_attempts}
                  onChange={e => setLlmField('retry_attempts', Math.max(0, Math.min(10, Number(e.target.value) || 0)))}
                />
              </div>
            </div>
          </div>

          <div className="settings-card">
            <div className="settings-card__body settings-card__actions">
              <button
                type="button"
                className="retry-btn"
                disabled={!dirty || saving}
                onClick={() => void handleSave()}
              >
                {saving ? t('Settings_page.capture_saving') : t('Settings_page.capture_save')}
              </button>
              {saveOk && <span className="settings-field__badge settings-field__badge--configured">{t('Settings_page.capture_saved')}</span>}
              {saveError && <span className="settings-field__badge settings-field__badge--missing">{saveError}</span>}
              {dirty && <span className="u-muted-sm">{t('Settings_page.capture_unsaved')}</span>}
            </div>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Privacy                                                       */
/* ------------------------------------------------------------------ */

const PRIVACY_MODES = ['strict_local', 'redacted_remote', 'explicit_remote'] as const;

const PRIVACY_MODE_LABEL_KEY: Record<string, MessageKey> = {
  strict_local: 'Settings_page.privacy_mode_strict_local',
  redacted_remote: 'Settings_page.privacy_mode_redacted_remote',
  explicit_remote: 'Settings_page.privacy_mode_explicit_remote',
};

interface PrivacyForm {
  privacy_mode: string;
  serve_port: number;
}

function PrivacyTab({
  config,
  failed,
  t,
  onRetry,
  onSaved,
}: {
  config: ConfigResponse | null;
  failed: boolean;
  t: TFn;
  onRetry: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<PrivacyForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (config) {
      setForm({
        privacy_mode: config.privacy_mode ?? 'strict_local',
        serve_port: config.serve_port ?? 8765,
      });
    }
  }, [config]);

  if (failed || !config || !form) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_privacy_controls')}
        message={t('Settings_page.config_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }

  const dirty = (
    form.privacy_mode !== (config.privacy_mode ?? 'strict_local')
    || form.serve_port !== (config.serve_port ?? 8765)
  );

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await putConfig({
        privacy_mode: form.privacy_mode,
        serve_port: form.serve_port,
      });
      setSaveOk(true);
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'save failed');
    } finally {
      setSaving(false);
    }
  };

  const setField = <K extends keyof PrivacyForm>(key: K, value: PrivacyForm[K]) => {
    setForm(prev => prev ? { ...prev, [key]: value } : prev);
    setSaveOk(false);
  };

  const privacyMode = form.privacy_mode;

  return (
    <>
      <div className="settings-card">
        <div className="settings-card__header"><h2>{t('Settings_page.section_privacy_controls')}</h2></div>
        <div className="settings-card__body">
          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.privacy_mode')}</h3>
              <p>{t('Settings_page.privacy_mode_desc')}</p>
            </div>
            <select
              className="settings-select"
              aria-label={t('Settings_page.privacy_mode')}
              value={form.privacy_mode}
              onChange={e => setField('privacy_mode', e.target.value)}
            >
              {PRIVACY_MODES.map(mode => (
                <option key={mode} value={mode}>{t(PRIVACY_MODE_LABEL_KEY[mode])}</option>
              ))}
            </select>
          </div>

          <PrivacyControl
            title={t('Settings_page.privacy_local_only')}
            description={t('Settings_page.privacy_local_only_desc')}
            checked={privacyMode === 'strict_local'}
            t={t}
          />
          <PrivacyControl
            title={t('Settings_page.privacy_redaction')}
            description={t('Settings_page.privacy_redaction_desc')}
            checked={privacyMode !== 'explicit_remote'}
            t={t}
          />
          <PrivacyControl
            title={t('Settings_page.privacy_audit_log')}
            description={t('Settings_page.privacy_audit_log_desc')}
            checked
            t={t}
          />
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card__header"><h2>{t('Settings_page.section_server')}</h2></div>
        <div className="settings-card__body">
          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.serve_port')}</h3>
              <p>{t('Settings_page.serve_port_desc')}</p>
            </div>
            <input
              type="number"
              className="settings-input"
              aria-label={t('Settings_page.serve_port')}
              min={1024}
              max={65535}
              value={form.serve_port}
              onChange={e => setField('serve_port', Math.max(1024, Math.min(65535, Number(e.target.value) || 1024)))}
            />
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card__body settings-card__actions">
          <button
            type="button"
            className="retry-btn"
            disabled={!dirty || saving}
            onClick={() => void handleSave()}
          >
            {saving ? t('Settings_page.capture_saving') : t('Settings_page.capture_save')}
          </button>
          {saveOk && <span className="settings-field__badge settings-field__badge--configured">{t('Settings_page.capture_saved')}</span>}
          {saveError && <span className="settings-field__badge settings-field__badge--missing">{saveError}</span>}
          {dirty && <span className="u-muted-sm">{t('Settings_page.capture_unsaved')}</span>}
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Audit                                                         */
/* ------------------------------------------------------------------ */

const AUDIT_COLS = [
  'time', 'provider', 'model', 'files_sent',
  'tokens', 'cost', 'purpose', 'status',
] as const;

type AuditColumn = (typeof AUDIT_COLS)[number];

const AUDIT_COL_KEY: Record<AuditColumn, MessageKey> = {
  time: 'Settings_page.audit_col_time',
  provider: 'Settings_page.audit_col_provider',
  model: 'Settings_page.audit_col_model',
  files_sent: 'Settings_page.audit_col_files',
  tokens: 'Settings_page.audit_col_tokens',
  cost: 'Settings_page.audit_col_cost',
  purpose: 'Settings_page.audit_col_purpose',
  status: 'Settings_page.audit_col_status',
};

function AuditTab({
  audit,
  failed,
  t,
  locale,
  onRetry,
}: {
  audit: AuditResponse | null;
  failed: boolean;
  t: TFn;
  locale: string;
  onRetry: () => void;
}) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditHasMore, setAuditHasMore] = useState(false);
  const [auditLoadingMore, setAuditLoadingMore] = useState(false);
  const [auditLoadError, setAuditLoadError] = useState(false);
  const loadGenRef = useRef(0);
  const auditRequestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    loadGenRef.current += 1;
    auditRequestRef.current?.abort();
    setAuditLoadingMore(false);
    setAuditLoadError(false);
    if (audit) {
      setEntries(audit.entries);
      setAuditOffset(audit.offset ?? 0);
      setAuditHasMore(Boolean(audit.has_more));
    } else {
      setEntries([]);
      setAuditOffset(0);
      setAuditHasMore(false);
    }
  }, [audit]);

  useEffect(() => () => {
    loadGenRef.current += 1;
    auditRequestRef.current?.abort();
  }, []);

  const loadMore = useCallback(async () => {
    if (auditLoadingMore || !auditHasMore) return;
    const gen = ++loadGenRef.current;
    const controller = new AbortController();
    auditRequestRef.current?.abort();
    auditRequestRef.current = controller;
    setAuditLoadingMore(true);
    setAuditLoadError(false);
    try {
      const newOffset = auditOffset + 20;
      const more = await getAudit(20, newOffset, { signal: controller.signal });
      if (controller.signal.aborted || gen !== loadGenRef.current) return;
      setEntries((prev) => [...prev, ...more.entries]);
      setAuditOffset(more.offset);
      setAuditHasMore(Boolean(more.has_more));
    } catch {
      if (controller.signal.aborted || gen !== loadGenRef.current) return;
      setAuditLoadError(true);
    } finally {
      if (!controller.signal.aborted && gen === loadGenRef.current) {
        setAuditLoadingMore(false);
        if (auditRequestRef.current === controller) {
          auditRequestRef.current = null;
        }
      }
    }
  }, [auditHasMore, auditLoadingMore, auditOffset]);

  if (failed || !audit) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_audit')}
        message={t('Settings_page.audit_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }
  if (entries.length === 0) {
    return (
      <div className="settings-card">
        <div className="settings-card__header"><h2>{t('Settings_page.section_audit')}</h2></div>
        <div className="settings-card__body">
          <div className="u-muted-sm">{t('Settings_page.audit_empty')}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <h2>{t('Settings_page.section_audit')}</h2>
        <span className="u-muted-sm">{t('Settings_page.audit_last_n', { count: String(entries.length) })}</span>
      </div>
      <div className="settings-card__body settings-card__body--flush">
        <div className="audit-table-wrap">
          <table className="audit-table" aria-label={t('Settings_page.audit_table_label')}>
            <caption className="u-sr-only">{t('Settings_page.audit_table_label')}</caption>
            <thead>
              <tr>
                {AUDIT_COLS.map(col => (
                  <th key={col} scope="col">{t(AUDIT_COL_KEY[col])}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, i) => (
                <tr key={i}>
                  {AUDIT_COLS.map(col => {
                    const display = formatAuditCell(entry, col, t, locale);
                    const isNum = col === 'tokens' || col === 'cost';
                    return <td key={col} className={isNum ? 'num' : ''}>{display}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {auditHasMore && (
          <div className="settings-audit__load-more">
            <button
              type="button"
              className="settings-audit__load-more-btn"
              disabled={auditLoadingMore}
              onClick={() => { void loadMore(); }}
            >
              {auditLoadingMore ? t('Settings_page.audit_loading') : t('Settings_page.audit_load_more')}
            </button>
            {auditLoadError && (
              <span role="alert" className="settings-audit__load-error">
                {t('Error.fetch_failed', { resource: t('Settings_page.section_audit') })}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Preferences (merged Language + Appearance)                    */
/* ------------------------------------------------------------------ */

type ThemeMode = 'system' | 'light' | 'dark';

const OUTPUT_LANG_OPTIONS = ['auto', 'en', 'zh-CN'] as const;

const OUTPUT_LANG_LABEL_KEY: Record<string, MessageKey> = {
  'auto': 'Settings_page.output_lang_auto',
  'en': 'Settings_page.output_lang_en',
  'zh-CN': 'Settings_page.output_lang_zh_cn',
};

const QUIZ_COUNT_MIN = 1;
const QUIZ_COUNT_MAX = 10;

export function clampQuizCountInput(rawValue: string, fallback: number): number {
  if (rawValue.trim() === '') {
    return fallback;
  }
  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(QUIZ_COUNT_MIN, Math.min(QUIZ_COUNT_MAX, Math.round(parsed)));
}

export interface PreferencesForm {
  output_lang: string;
  learnability_threshold: number;
  desired_retention: number;
  quiz_question_count: number;
  quiz_question_count_mode: 'fixed' | 'auto';
  quiz_auto_range_min: number;
  quiz_auto_range_max: number;
}

export function preferencesFormFromConfig(config: ConfigResponse): PreferencesForm {
  return {
    output_lang: config.llm.output_lang ?? 'auto',
    learnability_threshold: config.learn.learnability_threshold ?? 0.3,
    desired_retention: config.learn.desired_retention ?? 0.9,
    quiz_question_count: config.quiz.quiz_question_count ?? 3,
    quiz_question_count_mode: config.quiz.quiz_question_count_mode ?? 'fixed',
    quiz_auto_range_min: config.quiz.quiz_auto_range_min ?? 3,
    quiz_auto_range_max: config.quiz.quiz_auto_range_max ?? 8,
  };
}

export function isPreferencesFormDirty(form: PreferencesForm, config: ConfigResponse): boolean {
  return (
    form.output_lang !== (config.llm.output_lang ?? 'auto')
    || form.learnability_threshold !== (config.learn.learnability_threshold ?? 0.3)
    || form.desired_retention !== (config.learn.desired_retention ?? 0.9)
    || form.quiz_question_count !== (config.quiz.quiz_question_count ?? 3)
    || form.quiz_question_count_mode !== (config.quiz.quiz_question_count_mode ?? 'fixed')
    || form.quiz_auto_range_min !== (config.quiz.quiz_auto_range_min ?? 3)
    || form.quiz_auto_range_max !== (config.quiz.quiz_auto_range_max ?? 8)
  );
}

function PreferencesTab({
  config,
  failed,
  t,
  onRetry,
  onSaved,
}: {
  config: ConfigResponse | null;
  failed: boolean;
  t: TFn;
  onRetry: () => void;
  onSaved: () => void;
}) {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    return (localStorage.getItem('ahadiff-theme') as ThemeMode) || 'system';
  });
  const [form, setForm] = useState<PreferencesForm | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (config) {
      setForm(preferencesFormFromConfig(config));
    }
  }, [config]);

  const applyTheme = (mode: ThemeMode) => {
    setTheme(mode);
    localStorage.setItem('ahadiff-theme', mode);
    const root = document.documentElement;
    root.removeAttribute('data-theme');
    if (mode !== 'system') {
      root.setAttribute('data-theme', mode);
    }
  };

  const dirty = config && form && isPreferencesFormDirty(form, config);

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await putConfig({
        llm: { output_lang: form.output_lang },
        learn: {
          learnability_threshold: form.learnability_threshold,
          desired_retention: form.desired_retention,
        },
        quiz: {
          quiz_question_count: form.quiz_question_count,
          quiz_question_count_mode: form.quiz_question_count_mode,
          quiz_auto_range_min: form.quiz_auto_range_min,
          quiz_auto_range_max: form.quiz_auto_range_max,
        },
      });
      setSaveOk(true);
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'save failed');
    } finally {
      setSaving(false);
    }
  };

  const setField = <K extends keyof PreferencesForm>(key: K, value: PreferencesForm[K]) => {
    setForm(prev => prev ? { ...prev, [key]: value } : prev);
    setSaveOk(false);
  };

  return (
    <>
      <div className="settings-card">
        <div className="settings-card__header"><h2>{t('Settings_page.section_language')}</h2></div>
        <div className="settings-card__body">
          <div className="settings-field">
            <div className="settings-field__label"><h3>{t('Settings.language')}</h3></div>
            <LanguageSwitcher />
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card__header"><h2>{t('Settings_page.section_appearance')}</h2></div>
        <div className="settings-card__body">
          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.theme_mode')}</h3>
              <p>{t('Settings_page.theme_mode_desc')}</p>
            </div>
            <div className="settings-theme-buttons">
              {(['system', 'light', 'dark'] as ThemeMode[]).map(mode => (
                <button
                  key={mode}
                  type="button"
                  className={`settings-theme-btn${theme === mode ? ' is-active' : ''}`}
                  onClick={() => applyTheme(mode)}
                  aria-pressed={theme === mode}
                >
                  {t(`Settings_page.theme_${mode}` as MessageKey)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {failed || !config || !form ? (
        <UnavailableCard
          title={t('Settings_page.section_learning')}
          message={t('Settings_page.config_unavailable')}
          t={t}
          onRetry={onRetry}
        />
      ) : (
        <>
          <div className="settings-card">
            <div className="settings-card__header"><h2>{t('Settings_page.output_lang')}</h2></div>
            <div className="settings-card__body">
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.output_lang')}</h3>
                  <p>{t('Settings_page.output_lang_desc')}</p>
                </div>
                <select
                  className="settings-select"
                  aria-label={t('Settings_page.output_lang')}
                  value={form.output_lang}
                  onChange={e => setField('output_lang', e.target.value)}
                >
                  {OUTPUT_LANG_OPTIONS.map(opt => (
                    <option key={opt} value={opt}>{t(OUTPUT_LANG_LABEL_KEY[opt])}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          <div className="settings-card">
            <div className="settings-card__header"><h2>{t('Settings_page.section_learning')}</h2></div>
            <div className="settings-card__body">
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.learnability_threshold')}</h3>
                  <p>{t('Settings_page.learnability_threshold_desc')}</p>
                </div>
                <div className="settings-slider">
                  <span className="settings-slider__legend settings-slider__legend--start">
                    {t('Settings_page.learnability_more')}
                  </span>
                  <input
                    type="range"
                    className="settings-slider__input"
                    min={0}
                    max={1}
                    step={0.05}
                    value={form.learnability_threshold}
                    onChange={e => setField('learnability_threshold', Math.max(0, Math.min(1, Number(e.target.value) || 0)))}
                    aria-label={t('Settings_page.learnability_threshold')}
                    aria-valuemin={0}
                    aria-valuemax={1}
                    aria-valuenow={form.learnability_threshold}
                  />
                  <span className="settings-slider__legend settings-slider__legend--end">
                    {t('Settings_page.learnability_fewer')}
                  </span>
                  <span className="settings-slider__value">{form.learnability_threshold.toFixed(2)}</span>
                </div>
              </div>

              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.desired_retention_label')}</h3>
                  <p>{t('Settings_page.desired_retention_hint')}</p>
                </div>
                <div className="settings-slider">
                  <input
                    type="range"
                    className="settings-slider__input"
                    min={0.7}
                    max={0.99}
                    step={0.01}
                    value={form.desired_retention}
                    onChange={e => setField('desired_retention', Math.max(0.7, Math.min(0.99, Number(e.target.value) || 0.9)))}
                    aria-label={t('Settings_page.desired_retention_label')}
                    aria-valuemin={0.7}
                    aria-valuemax={0.99}
                    aria-valuenow={form.desired_retention}
                  />
                  <span className="settings-slider__value">{Math.round(form.desired_retention * 100)}%</span>
                </div>
              </div>

              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.quiz_question_count')}</h3>
                  <p>{t('Settings_page.quiz_question_count_desc')}</p>
                </div>
                <div className="settings-quiz-count">
                  <div
                    className="settings-theme-buttons"
                    role="group"
                    aria-label={t('Settings_page.quiz_mode')}
                  >
                    <button
                      type="button"
                      className={`settings-theme-btn${form.quiz_question_count_mode === 'fixed' ? ' is-active' : ''}`}
                      aria-pressed={form.quiz_question_count_mode === 'fixed'}
                      onClick={() => setField('quiz_question_count_mode', 'fixed')}
                    >
                      {t('Settings_page.quiz_mode_fixed')}
                    </button>
                    <button
                      type="button"
                      className={`settings-theme-btn${form.quiz_question_count_mode === 'auto' ? ' is-active' : ''}`}
                      aria-pressed={form.quiz_question_count_mode === 'auto'}
                      onClick={() => setField('quiz_question_count_mode', 'auto')}
                    >
                      {t('Settings_page.quiz_mode_auto')}
                    </button>
                  </div>
                  {form.quiz_question_count_mode === 'fixed' ? (
                    <input
                      type="number"
                      className="settings-input"
                      aria-label={t('Settings_page.quiz_question_count')}
                      min={1}
                      max={10}
                      step={1}
                      value={form.quiz_question_count}
                      onChange={e => setField('quiz_question_count', clampQuizCountInput(e.target.value, 3))}
                    />
                  ) : (
                    <div className="settings-auto-range">
                      <p className="settings-auto-range__desc">{t('Settings_page.quiz_auto_desc')}</p>
                      <div className="settings-auto-range__inputs">
                        <label>
                          {t('Settings_page.quiz_auto_min')}
                          <input
                            type="number"
                            className="settings-input"
                            min={1}
                            max={10}
                            step={1}
                            aria-label={t('Settings_page.quiz_auto_min')}
                            value={form.quiz_auto_range_min}
                            onChange={e => {
                              const v = clampQuizCountInput(e.target.value, 3);
                              setField('quiz_auto_range_min', v);
                              if (v > form.quiz_auto_range_max) {
                                setField('quiz_auto_range_max', v);
                              }
                            }}
                          />
                        </label>
                        <span className="settings-auto-range__separator" aria-hidden="true">—</span>
                        <label>
                          {t('Settings_page.quiz_auto_max')}
                          <input
                            type="number"
                            className="settings-input"
                            min={1}
                            max={10}
                            step={1}
                            aria-label={t('Settings_page.quiz_auto_max')}
                            value={form.quiz_auto_range_max}
                            onChange={e => {
                              const v = clampQuizCountInput(e.target.value, 8);
                              setField('quiz_auto_range_max', v);
                              if (v < form.quiz_auto_range_min) {
                                setField('quiz_auto_range_min', v);
                              }
                            }}
                          />
                        </label>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="settings-card">
            <div className="settings-card__body settings-card__actions">
              <button
                type="button"
                className="retry-btn"
                disabled={!dirty || saving}
                onClick={() => void handleSave()}
              >
                {saving ? t('Settings_page.capture_saving') : t('Settings_page.capture_save')}
              </button>
              {saveOk && <span className="settings-field__badge settings-field__badge--configured">{t('Settings_page.capture_saved')}</span>}
              {saveError && <span className="settings-field__badge settings-field__badge--missing">{saveError}</span>}
              {dirty && <span className="u-muted-sm">{t('Settings_page.capture_unsaved')}</span>}
            </div>
          </div>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Capture                                                       */
/* ------------------------------------------------------------------ */

const FILE_RANKING_OPTIONS = ['learning_value', 'changed_lines', 'path'] as const;

const FILE_RANKING_LABEL_KEY: Record<string, MessageKey> = {
  learning_value: 'Settings_page.capture_ranking_learning_value',
  changed_lines: 'Settings_page.capture_ranking_changed_lines',
  path: 'Settings_page.capture_ranking_path',
};

const SYMBOL_EXTRACTOR_OPTIONS = ['auto', 'builtin', 'tree_sitter'] as const;

const SYMBOL_EXTRACTOR_LABEL_KEY: Record<string, MessageKey> = {
  auto: 'Settings_page.capture_extractor_auto',
  builtin: 'Settings_page.capture_extractor_builtin',
  tree_sitter: 'Settings_page.capture_extractor_tree_sitter',
};

const CAPTURE_SOURCE_KEYS: Record<string, MessageKey> = {
  live: 'Settings_page.capture_auto_source_live',
  registry: 'Settings_page.capture_auto_source_registry',
  default: 'Settings_page.capture_auto_source_default',
};

function captureSourceLabel(t: TFn, source: string): string {
  const key = CAPTURE_SOURCE_KEYS[source];
  return key ? t(key) : source;
}

/**
 * Pure derivation: compare a manual draft against the saved capture config to
 * detect dirty state.  Exported for unit tests.
 */
export function isCaptureFormDirty(
  form: CaptureConfig,
  saved: CaptureConfig | undefined | null,
): boolean {
  if (!saved) return false;
  const savedMode = saved.mode ?? 'manual';
  const formMode = form.mode ?? 'manual';
  return (
    formMode !== savedMode
    || form.max_files !== saved.max_files
    || form.hard_limit !== saved.hard_limit
    || form.max_patch_bytes !== saved.max_patch_bytes
    || form.file_ranking !== saved.file_ranking
    || form.symbol_extractor !== saved.symbol_extractor
  );
}

function CaptureTab({
  config,
  failed,
  t,
  locale,
  onRetry,
  onSaved,
}: {
  config: ConfigResponse | null;
  failed: boolean;
  t: TFn;
  locale: string;
  onRetry: () => void;
  onSaved: () => void;
}) {
  const capture = config?.capture;
  const [form, setForm] = useState<CaptureConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);
  const [recommendation, setRecommendation] = useState<CaptureRecommendation | null>(null);
  const [recommendationLoading, setRecommendationLoading] = useState(false);
  const [recommendationError, setRecommendationError] = useState<string | null>(null);

  useEffect(() => {
    if (capture) setForm({ ...capture });
  }, [capture]);

  // Fetch capture recommendation (used in both auto/manual modes for hints).
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setRecommendationLoading(true);
    setRecommendationError(null);
    void (async () => {
      try {
        const rec = await getCaptureRecommended({ signal: controller.signal });
        if (cancelled) return;
        setRecommendation(rec);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (err instanceof Error && err.name === 'AbortError') return;
        // 404/NOT_FOUND from /api/capture/recommended means no provider is
        // configured yet. That is not an error — the auto-mode no-provider
        // banner should render instead of the generic failure badge.
        const isNoProvider =
          err instanceof ApiError
          && (err.status === 404 || err.errorCode === 'NOT_FOUND');
        setRecommendation(null);
        if (isNoProvider) {
          setRecommendationError(null);
        } else {
          setRecommendationError(err instanceof Error ? err.message : 'failed');
        }
      } finally {
        if (!cancelled) setRecommendationLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [config]);

  const formatTexts = useMemo(() => buildFormatTexts(t), [t]);

  if (failed || !config || !form) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_capture')}
        message={t('Settings_page.config_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }

  const mode: 'auto' | 'manual' = form.mode ?? 'manual';
  const isAuto = mode === 'auto';
  const dirty = isCaptureFormDirty(form, capture);

  const fmtTokens = (n: number) => formatCompactNumber(n, locale, formatTexts);
  const fmtBytes = (n: number) => formatBytes(n, locale, formatTexts);

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await putConfig({ capture: form });
      setSaveOk(true);
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'save failed');
    } finally {
      setSaving(false);
    }
  };

  const setField = <K extends keyof CaptureConfig>(key: K, value: CaptureConfig[K]) => {
    setForm(prev => prev ? { ...prev, [key]: value } : prev);
    setSaveOk(false);
  };

  const setMode = (next: 'auto' | 'manual') => {
    setForm(prev => prev ? { ...prev, mode: next } : prev);
    setSaveOk(false);
  };

  // Tracks recommendation availability for the no-provider / too-small banners.
  const hasRecommendation = recommendation != null;
  const recFitsMinimums = recommendation?.fits_minimums ?? true;
  const recWarnings = recommendation?.warnings ?? [];

  return (
    <>
      <div className="settings-card">
        <div className="settings-card__header">
          <h2>{t('Settings_page.section_capture')}</h2>
        </div>
        <div className="settings-card__body">
          <p className="u-muted-sm settings-card__intro">
            {t('Settings_page.capture_description')}
          </p>

          {/* Auto / Manual mode toggle (segmented control) */}
          <div
            className="settings-field"
            role="radiogroup"
            aria-label={t('Settings_page.capture_mode')}
          >
            <div className="settings-field__label">
              <h3>{t('Settings_page.capture_mode')}</h3>
              <p>{t('Settings_page.capture_mode_desc')}</p>
            </div>
            <div className="capture-mode-segmented" role="presentation">
              <label
                className={`capture-mode-segmented__option${isAuto ? ' is-active' : ''}`}
              >
                <input
                  type="radio"
                  name="capture-mode"
                  value="auto"
                  checked={isAuto}
                  onChange={() => setMode('auto')}
                  className="capture-mode-segmented__radio"
                  data-testid="capture-mode-auto"
                />
                <span>{t('Settings_page.capture_mode_auto')}</span>
              </label>
              <label
                className={`capture-mode-segmented__option${!isAuto ? ' is-active' : ''}`}
              >
                <input
                  type="radio"
                  name="capture-mode"
                  value="manual"
                  checked={!isAuto}
                  onChange={() => setMode('manual')}
                  className="capture-mode-segmented__radio"
                  data-testid="capture-mode-manual"
                />
                <span>{t('Settings_page.capture_mode_manual')}</span>
              </label>
            </div>
          </div>

          {/* Recommendation loading / error banner (visible in both modes) */}
          {recommendationLoading && (
            <p className="u-muted-sm" role="status">
              {t('Settings_page.capture_recommendation_loading')}
            </p>
          )}
          {!recommendationLoading && recommendationError && (
            <p className="settings-field__badge settings-field__badge--missing" role="alert">
              {t('Settings_page.capture_recommendation_failed')}
            </p>
          )}

          {/* Auto mode: show computed values + budget bar + warnings */}
          {isAuto && (
            <>
              {!hasRecommendation && !recommendationLoading && !recommendationError && (
                <p className="settings-field__badge settings-field__badge--missing" role="alert">
                  {t('Settings_page.capture_auto_no_provider')}
                </p>
              )}

              {hasRecommendation && (
                <>
                  {!recFitsMinimums && (
                    <p
                      className="settings-field__badge settings-field__badge--missing"
                      role="alert"
                    >
                      {t('Settings_page.capture_auto_too_small')}
                    </p>
                  )}

                  <div className="settings-field">
                    <div className="settings-field__label">
                      <h3>{t('Settings_page.capture_model_label')}</h3>
                      <p>{t('Settings_page.capture_auto_computed')}</p>
                    </div>
                    <span className="settings-field__value">
                      {recommendation!.model_name}
                    </span>
                  </div>

                  <div className="settings-field">
                    <div className="settings-field__label">
                      <h3>{t('Settings_page.capture_auto_source')}</h3>
                    </div>
                    <span className="settings-field__value">
                      <span className="settings-field__badge">
                        {captureSourceLabel(t, recommendation!.source)}
                      </span>
                    </span>
                  </div>

                  <div className="settings-field">
                    <div className="settings-field__label">
                      <h3>{t('Settings_page.capture_max_files')}</h3>
                      <p>{t('Settings_page.capture_max_files_desc')}</p>
                    </div>
                    <span
                      className="settings-field__value"
                      data-testid="capture-auto-max-files"
                    >
                      {fmtTokens(recommendation!.max_files)}
                    </span>
                  </div>

                  <div className="settings-field">
                    <div className="settings-field__label">
                      <h3>{t('Settings_page.capture_hard_limit')}</h3>
                      <p>{t('Settings_page.capture_hard_limit_desc')}</p>
                    </div>
                    <span
                      className="settings-field__value"
                      data-testid="capture-auto-hard-limit"
                    >
                      {fmtTokens(recommendation!.hard_limit)}
                    </span>
                  </div>

                  <div className="settings-field">
                    <div className="settings-field__label">
                      <h3>{t('Settings_page.capture_max_patch_bytes')}</h3>
                      <p>{t('Settings_page.capture_max_patch_bytes_desc')}</p>
                    </div>
                    <span
                      className="settings-field__value"
                      data-testid="capture-auto-max-patch-bytes"
                    >
                      {fmtBytes(recommendation!.max_patch_bytes)}
                    </span>
                  </div>

                  <div className="settings-field">
                    <div className="settings-field__label">
                      <h3>{t('Settings_page.capture_budget_total')}</h3>
                    </div>
                    <div className="settings-field__value capture-budget-bar-wrap">
                      <CaptureBudgetBar recommendation={recommendation} />
                    </div>
                  </div>

                  {recWarnings.length > 0 && (
                    <div className="settings-field">
                      <div className="settings-field__label">
                        <h3>{t('Settings_page.capture_warnings_title')}</h3>
                      </div>
                      <ul className="capture-warning-list" role="list">
                        {recWarnings.map((w, idx) => (
                          <li key={`${idx}:${w}`} className="capture-warning-list__item">
                            {/*
                              Backend warning strings are currently English-only;
                              wrap in lang="en" so screen readers pronounce them
                              correctly even when the UI locale is non-English.
                              TODO(i18n): backend-side localization pending so we
                              can drop this wrapper and translate the string.
                            */}
                            <span lang="en">{w}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {/* Manual mode: keep numeric inputs editable */}
          {!isAuto && (
            <>
              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.capture_max_files')}</h3>
                  <p>{t('Settings_page.capture_max_files_desc')}</p>
                  {hasRecommendation && (
                    <p className="u-muted-sm" data-testid="capture-hint-max-files">
                      {t('Settings_page.capture_auto_hint', {
                        value: fmtTokens(recommendation!.max_files),
                      })}
                    </p>
                  )}
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.capture_max_files')}
                  min={1}
                  max={500}
                  value={form.max_files}
                  onChange={e => setField('max_files', Math.max(1, Math.min(500, Number(e.target.value) || 1)))}
                />
              </div>

              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.capture_hard_limit')}</h3>
                  <p>{t('Settings_page.capture_hard_limit_desc')}</p>
                  {hasRecommendation && (
                    <p className="u-muted-sm" data-testid="capture-hint-hard-limit">
                      {t('Settings_page.capture_auto_hint', {
                        value: fmtTokens(recommendation!.hard_limit),
                      })}
                    </p>
                  )}
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.capture_hard_limit')}
                  min={100}
                  max={100000}
                  value={form.hard_limit}
                  onChange={e => setField('hard_limit', Math.max(100, Math.min(100000, Number(e.target.value) || 100)))}
                />
              </div>

              <div className="settings-field">
                <div className="settings-field__label">
                  <h3>{t('Settings_page.capture_max_patch_bytes')}</h3>
                  <p>{t('Settings_page.capture_max_patch_bytes_desc')}</p>
                  {hasRecommendation && (
                    <p className="u-muted-sm" data-testid="capture-hint-max-patch-bytes">
                      {t('Settings_page.capture_auto_hint', {
                        value: fmtBytes(recommendation!.max_patch_bytes),
                      })}
                    </p>
                  )}
                </div>
                <input
                  type="number"
                  className="settings-input"
                  aria-label={t('Settings_page.capture_max_patch_bytes')}
                  min={10000}
                  max={100000000}
                  step={100000}
                  value={form.max_patch_bytes}
                  onChange={e => setField('max_patch_bytes', Math.max(10000, Math.min(100000000, Number(e.target.value) || 10000)))}
                />
                <span className="u-muted-sm settings-field__suffix">
                  ({fmtBytes(form.max_patch_bytes)})
                </span>
              </div>
            </>
          )}

          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.capture_file_ranking')}</h3>
              <p>{t('Settings_page.capture_file_ranking_desc')}</p>
            </div>
            <select
              className="settings-select"
              aria-label={t('Settings_page.capture_file_ranking')}
              value={form.file_ranking}
              onChange={e => setField('file_ranking', e.target.value)}
            >
              {FILE_RANKING_OPTIONS.map(opt => (
                <option key={opt} value={opt}>{t(FILE_RANKING_LABEL_KEY[opt])}</option>
              ))}
            </select>
          </div>

          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.capture_symbol_extractor')}</h3>
              <p>{t('Settings_page.capture_symbol_extractor_desc')}</p>
            </div>
            <select
              className="settings-select"
              aria-label={t('Settings_page.capture_symbol_extractor')}
              value={form.symbol_extractor}
              onChange={e => setField('symbol_extractor', e.target.value)}
            >
              {SYMBOL_EXTRACTOR_OPTIONS.map(opt => (
                <option key={opt} value={opt}>{t(SYMBOL_EXTRACTOR_LABEL_KEY[opt])}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card__body settings-card__actions">
          <button
            type="button"
            className="retry-btn"
            disabled={!dirty || saving}
            onClick={() => void handleSave()}
          >
            {saving ? t('Settings_page.capture_saving') : t('Settings_page.capture_save')}
          </button>
          {saveOk && <span className="settings-field__badge settings-field__badge--configured">{t('Settings_page.capture_saved')}</span>}
          {saveError && <span className="settings-field__badge settings-field__badge--missing">{saveError}</span>}
          {dirty && <span className="u-muted-sm">{t('Settings_page.capture_unsaved')}</span>}
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Integrations                                                  */
/* ------------------------------------------------------------------ */

function IntegrationsTab({
  targets,
  failed,
  showGraphify,
  t,
  onRetry,
  onRefreshTargets,
}: {
  targets: InstallTarget[];
  failed: boolean;
  showGraphify: boolean;
  t: TFn;
  onRetry: () => void;
  onRefreshTargets: (opts?: { signal?: AbortSignal }) => Promise<void>;
}) {
  const [copiedTarget, setCopiedTarget] = useState<string | null>(null);
  const [localTargets, setLocalTargets] = useState<InstallTarget[]>(targets);
  const [actionState, setActionState] = useState<Record<string, InstallActionState>>({});
  const mountedRef = useRef(true);
  const copiedResetTimerRef = useRef<number | null>(null);
  const actionAbortControllersRef = useRef<Set<AbortController>>(new Set());

  useEffect(() => () => {
    mountedRef.current = false;
    if (copiedResetTimerRef.current !== null) window.clearTimeout(copiedResetTimerRef.current);
    for (const controller of actionAbortControllersRef.current) controller.abort();
    actionAbortControllersRef.current.clear();
  }, []);

  useEffect(() => {
    setLocalTargets(targets);
  }, [targets]);

  const upsertTarget = useCallback((target: InstallTarget) => {
    setLocalTargets((current) => current.map((item) => (
      item.name === target.name ? target : item
    )));
  }, []);

  const copyTargetCommand = useCallback(async (
    target: InstallTarget,
    kind: 'install' | 'uninstall',
  ) => {
    const ok = await copyToClipboard(commandFor(target, kind));
    if (!ok || !mountedRef.current) return;
    setCopiedTarget(`${target.name}:${kind}`);
    if (copiedResetTimerRef.current !== null) window.clearTimeout(copiedResetTimerRef.current);
    copiedResetTimerRef.current = window.setTimeout(() => {
      copiedResetTimerRef.current = null;
      if (mountedRef.current) setCopiedTarget(null);
    }, 1400);
  }, []);

  const runAction = useCallback(async (target: InstallTarget, kind: InstallActionKind) => {
    const controller = new AbortController();
    actionAbortControllersRef.current.add(controller);
    setActionState((current) => ({
      ...current,
      [target.name]: {
        ...current[target.name],
        pending: kind,
        error: undefined,
      },
    }));
    try {
      const preview = await previewInstallTarget(target.name, { signal: controller.signal });
      if (controller.signal.aborted || !mountedRef.current) return;
      upsertTarget(preview.target);
      if (kind === 'preview') {
        setActionState((current) => ({
          ...current,
          [target.name]: {
            message: t('Settings_page.integration_preview_success_project'),
            previewTarget: preview.target,
            manifestHash: preview.manifest_hash,
            previewCollapsed: false,
          },
        }));
        return;
      }
      const result = kind === 'install'
        ? await applyInstallTarget(target.name, preview.manifest_hash, { signal: controller.signal })
        : await removeInstallTarget(target.name, preview.manifest_hash, { signal: controller.signal });
      if (controller.signal.aborted || !mountedRef.current) return;
      upsertTarget(result.target);
      setActionState((current) => ({
        ...current,
        [target.name]: {
          message: kind === 'install'
            ? t('Settings_page.integration_install_success_project')
            : t('Settings_page.integration_uninstall_success_project'),
          previewTarget: result.target,
          manifestHash: result.manifest_hash,
          previewCollapsed: true,
        },
      }));
      await onRefreshTargets({ signal: controller.signal });
    } catch (e) {
      if (controller.signal.aborted || !mountedRef.current) return;
      setActionState((current) => ({
        ...current,
        [target.name]: {
          ...current[target.name],
          pending: undefined,
          message: undefined,
          error: e instanceof Error ? e.message : t('Skills.action_failed'),
        },
      }));
    } finally {
      actionAbortControllersRef.current.delete(controller);
    }
  }, [onRefreshTargets, t, upsertTarget]);

  const togglePreview = useCallback((target: InstallTarget) => {
    const state = actionState[target.name] ?? {};
    const hasPreview = Boolean(state.previewTarget || state.manifestHash);
    if (hasPreview) {
      setActionState((current) => ({
        ...current,
        [target.name]: {
          ...current[target.name],
          previewCollapsed: !(current[target.name]?.previewCollapsed ?? false),
        },
      }));
      return;
    }
    void runAction(target, 'preview');
  }, [actionState, runAction]);

  return (
    <>
      {showGraphify && (
        <Suspense
          fallback={<div className="settings-graphify-placeholder" aria-hidden="true" />}
        >
          <GraphifyCard />
        </Suspense>
      )}
      {failed ? (
        <UnavailableCard
          title={t('Settings_page.section_integrations')}
          message={t('Settings_page.integration_unavailable')}
          t={t}
          onRetry={onRetry}
        />
      ) : (
        <div className="settings-card">
        <div className="settings-card__header">
          <h2>{t('Settings_page.section_integrations')}</h2>
          <span className="integration-card-count">{localTargets.length}</span>
        </div>
        <div className="settings-card__body">
          <p className="integration-intro">
            <strong>{t('Settings_page.integration_scope_current')}</strong>
            {t('Settings_page.integration_intro_project')}
          </p>
          {localTargets.length === 0 && <div className="u-muted-sm">{t('Settings_page.integration_empty')}</div>}
          <div className="integration-grid">
            {localTargets.map(target => {
              const statusKey = INTEGRATION_STATUS_KEY[target.status];
              const badgeVariant = target.status === 'installed'
                ? 'configured'
                : target.status === 'available'
                  ? 'unknown'
                  : 'missing';
              const state = actionState[target.name] ?? {};
              const isPending = state.pending != null;
              const primaryAction: InstallActionKind = target.status === 'installed' ? 'uninstall' : 'install';
              const primaryCommandKind = primaryAction === 'uninstall' ? 'uninstall' : 'install';
              const previewTarget = state.previewTarget ?? target;
              const manifest = previewTarget.manifest ?? target.manifest ?? null;
              const hasPreview = Boolean((state.previewTarget || state.manifestHash) && manifest);
              const isPreviewOpen = hasPreview && !state.previewCollapsed;
              const currentActions = manifest?.[primaryAction === 'install' ? 'write' : 'uninstall'] ?? [];
              const copiedKey = `${target.name}:${primaryCommandKind}`;
              const titleId = `integration-title-${target.name}`;
              const previewId = `integration-preview-${target.name}`;
              return (
                <article
                  className={`integration-card integration-card--${target.status}`}
                  key={target.name}
                  aria-labelledby={titleId}
                >
                  <div className="integration-card__top">
                    <div className="integration-mark" aria-hidden="true">
                      {targetMark(target)}
                    </div>
                    <span className={`settings-field__badge settings-field__badge--${badgeVariant}`}>
                      {t(statusKey)}
                    </span>
                  </div>
                  <div className="integration-card__main">
                    <h3 id={titleId} className="integration-card__name">{target.display_name}</h3>
                    <p className="integration-card__description">{target.description}</p>
                    <p className="integration-card__scope">
                      <span>{t('Settings_page.integration_scope_current')}</span>
                      {t('Settings_page.integration_scope_note')}
                    </p>
                    {currentActions.length > 0 && (
                      <p className="integration-card__paths">
                        {currentActions.map(action => action.path).join(' · ')}
                      </p>
                    )}
                    {target.platform_supported && (
                      <div className="integration-command" aria-label={t(
                        primaryCommandKind === 'install'
                          ? 'Settings_page.integration_install_command'
                          : 'Settings_page.integration_uninstall_command',
                      )}
                      >
                        <code>$ {commandFor(target, primaryCommandKind)}</code>
                        <button
                          type="button"
                          className="integration-copy-btn"
                          aria-label={t(
                            primaryCommandKind === 'install'
                              ? 'Settings_page.integration_copy_install_aria'
                              : 'Settings_page.integration_copy_uninstall_aria',
                            { target: target.display_name },
                          )}
                          onClick={() => void copyTargetCommand(target, primaryCommandKind)}
                        >
                          {copiedTarget === copiedKey ? t('Skills.copied') : t('Skills.copy')}
                        </button>
                      </div>
                    )}
                    {state.message && <p className="integration-message" role="status">{state.message}</p>}
                    {state.error && <p className="integration-message integration-message--error" role="alert">{state.error}</p>}
                    {isPreviewOpen && manifest && (
                      <IntegrationPreviewPanel
                        id={previewId}
                        target={previewTarget}
                        manifestHash={state.manifestHash}
                        t={t}
                      />
                    )}
                  </div>
                  <div className="integration-actions">
                    {target.platform_supported && (
                      <>
                        <button
                          type="button"
                          className="integration-btn integration-btn--secondary"
                          disabled={isPending || target.status === 'unsupported' || target.status === 'error'}
                          aria-controls={hasPreview ? previewId : undefined}
                          aria-expanded={isPreviewOpen}
                          aria-label={previewButtonAriaLabel(target, state, hasPreview, isPreviewOpen, t)}
                          onClick={() => togglePreview(target)}
                        >
                          {previewButtonLabel(state, hasPreview, isPreviewOpen, t)}
                        </button>
                        <button
                          type="button"
                          className={
                            primaryAction === 'install'
                              ? 'integration-btn integration-btn--primary'
                              : 'integration-btn integration-btn--danger'
                          }
                          disabled={isPending || target.status === 'unsupported' || target.status === 'error'}
                          aria-label={t(
                            primaryAction === 'install'
                              ? 'Settings_page.integration_install_project_aria'
                              : 'Settings_page.integration_uninstall_project_aria',
                            { target: target.display_name },
                          )}
                          onClick={() => void runAction(target, primaryAction)}
                        >
                          {state.pending === primaryAction
                            ? (primaryAction === 'install'
                              ? t('Settings_page.integration_writing_guidance')
                              : t('Settings_page.integration_removing_guidance'))
                            : (primaryAction === 'install'
                              ? t('Settings_page.integration_install_project_action')
                              : t('Settings_page.integration_uninstall_project_action'))}
                        </button>
                      </>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </div>
      )}
    </>
  );
}

function installCommand(target: InstallTarget): string {
  return target.install_command ?? `ahadiff install ${target.name}`;
}

function uninstallCommand(target: InstallTarget): string {
  return target.uninstall_command ?? `ahadiff uninstall ${target.name}`;
}

function commandFor(target: InstallTarget, kind: 'install' | 'uninstall'): string {
  return kind === 'install' ? installCommand(target) : uninstallCommand(target);
}

function targetMark(target: InstallTarget): string {
  const knownMarks: Record<string, string> = {
    aider: 'AI',
    antigravity: 'AG',
    'antigravity-cli': 'AC',
    claude: 'CC',
    cline: 'CL',
    codex: 'CD',
    continue: 'CN',
    copilot: 'CP',
    cursor: 'CX',
    gemini: 'GM',
    'github-action': 'GH',
    hooks: 'HK',
    opencode: 'OC',
    roo: 'RO',
    windsurf: 'WS',
  };
  if (knownMarks[target.name]) return knownMarks[target.name];
  const words = target.display_name
    .split(/[^A-Za-z0-9]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const mark = words.slice(0, 2).map((part) => part[0]).join('');
  return (mark || target.name.slice(0, 2)).toUpperCase();
}

function previewButtonLabel(
  state: InstallActionState,
  hasPreview: boolean,
  isPreviewOpen: boolean,
  t: TFn,
): string {
  if (state.pending === 'preview') return t('Skills.previewing');
  if (isPreviewOpen) return t('Settings_page.integration_collapse_preview');
  if (hasPreview) return t('Settings_page.integration_show_preview');
  return t('Skills.preview_action');
}

function previewButtonAriaLabel(
  target: InstallTarget,
  state: InstallActionState,
  hasPreview: boolean,
  isPreviewOpen: boolean,
  t: TFn,
): string {
  if (state.pending === 'preview') {
    return t('Settings_page.integration_preview_aria', { target: target.display_name });
  }
  if (isPreviewOpen) {
    return t('Settings_page.integration_collapse_preview_aria', { target: target.display_name });
  }
  if (hasPreview) {
    return t('Settings_page.integration_show_preview_aria', { target: target.display_name });
  }
  return t('Settings_page.integration_preview_aria', { target: target.display_name });
}

function shortManifestHash(hash?: string | null): string | null {
  return hash ? `${hash.slice(0, 10)}…` : null;
}

function IntegrationPreviewPanel({
  id,
  target,
  manifestHash,
  t,
}: {
  id: string;
  target: InstallTarget;
  manifestHash?: string | null;
  t: TFn;
}) {
  const idBase = useId().replace(/:/g, '');
  const manifest = target.manifest;
  if (!manifest) return null;
  const titleId = `${idBase}-preview-title`;
  const hash = shortManifestHash(manifestHash ?? target.manifest_hash);
  return (
    <section
      id={id}
      className="integration-preview"
      aria-labelledby={titleId}
    >
      <div className="integration-preview__header">
        <h4 id={titleId} className="integration-preview__title">
          {t('Settings_page.integration_preview_title')}
        </h4>
        {hash && <code>{t('Settings_page.integration_manifest_hash', { hash })}</code>}
      </div>
      <div className="integration-preview__grid">
        <IntegrationActionList
          title={t('Settings_page.integration_preview_install_title')}
          actions={manifest.write}
          titleId={`${idBase}-install-title`}
          t={t}
        />
        <IntegrationActionList
          title={t('Settings_page.integration_preview_uninstall_title')}
          actions={manifest.uninstall}
          titleId={`${idBase}-uninstall-title`}
          t={t}
        />
      </div>
      <p className="integration-preview__note">
        {t('Settings_page.integration_preview_note')}
      </p>
    </section>
  );
}

function IntegrationActionList({
  title,
  actions,
  titleId,
  t,
}: {
  title: string;
  actions: InstallManifestAction[];
  titleId: string;
  t: TFn;
}) {
  return (
    <section className="integration-plan" aria-labelledby={titleId}>
      <h5 id={titleId} className="integration-plan__title">{title}</h5>
      {actions.length > 0 ? (
        <ul className="integration-plan__list">
          {actions.map((action, index) => (
            <li className="integration-plan__item" key={`${action.path}:${action.action}:${index}`}>
              <span>{actionLabel(action, t)}</span>
              <code>{action.path}</code>
              <em>{strategyLabel(action, t)}</em>
            </li>
          ))}
        </ul>
      ) : (
        <p>{t('Settings_page.integration_no_actions')}</p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared sub-components                                              */
/* ------------------------------------------------------------------ */

function RuntimeStatusCard({ t, locale }: { t: TFn; locale: string }) {
  const [serve, setServe] = useState<ServeStatusResponse | null>(null);
  const [watch, setWatch] = useState<WatchStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const opts = { signal: controller.signal };
    let cancelled = false;
    setLoading(true);
    setErrored(false);
    void Promise.allSettled([fetchServeStatus(opts), fetchWatchStatus(opts)])
      .then(([s, w]) => {
        if (cancelled || controller.signal.aborted) return;
        const serveOk = s.status === 'fulfilled';
        const watchOk = w.status === 'fulfilled';
        if (!serveOk && !watchOk) {
          setErrored(true);
        } else {
          setServe(serveOk ? s.value : null);
          setWatch(watchOk ? w.value : null);
        }
      })
      .finally(() => {
        if (!cancelled && !controller.signal.aborted) setLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  if (errored) return null;

  const dash = '—';
  const servePort = (typeof window !== 'undefined' && window.location?.port) || dash;
  const repoPath = dash;
  const uptime = loading || !serve
    ? dash
    : formatUptime(serve.uptime_seconds, locale, t);
  const watcherRunning = loading || !watch
    ? null
    : watch.running;
  const watcherTriggers = loading || !watch
    ? dash
    : formatNumber(watch.total_triggers, locale);
  const watcherFailures = loading || !watch
    ? dash
    : formatNumber(watch.consecutive_failures, locale);

  return (
    <div className="settings-card">
      <div className="settings-card__header"><h2>{t('Settings_page.runtime_title')}</h2></div>
      <div className="settings-card__body">
        <div className="mode-grid">
          <ModeCell eyebrow={t('Settings_page.runtime_serve_port')} value={servePort} />
          <ModeCell eyebrow={t('Settings_page.runtime_repo_path')} value={repoPath} />
          <ModeCell eyebrow={t('Settings_page.runtime_uptime')} value={uptime} />
          <ModeCell
            eyebrow={t('Settings_page.runtime_watcher')}
            value={watcherRunning === null
              ? dash
              : watcherRunning
                ? t('Settings_page.runtime_watcher_running')
                : t('Settings_page.runtime_watcher_stopped')}
          />
          <ModeCell eyebrow={t('Settings_page.runtime_watcher_triggers')} value={watcherTriggers} />
          <ModeCell eyebrow={t('Settings_page.runtime_watcher_failures')} value={watcherFailures} />
        </div>
      </div>
    </div>
  );
}

function formatUptime(seconds: number, locale: string, t: TFn): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  const total = Math.floor(seconds);
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (d > 0) {
    return t('Settings_page.runtime_uptime_days_hours_minutes', {
      days: formatNumber(d, locale),
      hours: formatNumber(h, locale),
      minutes: formatNumber(m, locale),
    });
  }
  if (h > 0) {
    return t('Settings_page.runtime_uptime_hours_minutes', {
      hours: formatNumber(h, locale),
      minutes: formatNumber(m, locale),
    });
  }
  if (m > 0) {
    return t('Settings_page.runtime_uptime_minutes_seconds', {
      minutes: formatNumber(m, locale),
      seconds: formatNumber(s, locale),
    });
  }
  return t('Settings_page.runtime_uptime_seconds', { seconds: formatNumber(s, locale) });
}

function UnavailableCard({
  title,
  message,
  t,
  onRetry,
}: {
  title: string;
  message: string;
  t: TFn;
  onRetry: () => void;
}) {
  return (
    <div className="settings-card">
      <div className="settings-card__header"><h2>{title}</h2></div>
      <div className="settings-card__body">
        <div className="settings-empty" role="status">
          <span>{message}</span>
          <button type="button" className="retry-btn" onClick={onRetry}>
            {t('Error.retry')}
          </button>
        </div>
      </div>
    </div>
  );
}

function PrivacyControl({
  title,
  description,
  checked,
  t,
}: {
  title: string;
  description: string;
  checked: boolean;
  t: TFn;
}) {
  return (
    <div className="settings-field setting-control">
      <div className="settings-field__label">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      <StaticSwitch checked={checked} label={title} t={t} />
    </div>
  );
}

function StaticSwitch({
  checked,
  label,
  t,
}: {
  checked: boolean;
  label: string;
  t: TFn;
}) {
  return (
    <>
      <span
        className={`settings-toggle settings-toggle--readonly${checked ? ' is-on' : ''}`}
        aria-hidden="true"
      >
        <span className="settings-toggle__knob" aria-hidden="true" />
      </span>
      <span className="u-sr-only">
        {label}: {checked ? t('Settings_page.switch_on') : t('Settings_page.switch_off')}.{' '}
        {t('Settings_page.configured_via_cli')}
      </span>
    </>
  );
}

function ModeCell({ eyebrow, value, sub }: { eyebrow: string; value: string; sub?: string }) {
  return (
    <div className="mode-cell">
      <div className="mode-cell__eyebrow">{eyebrow}</div>
      <div className="mode-cell__value">
        {value}
        {sub && <span className="mode-cell__sub"> ({sub})</span>}
      </div>
    </div>
  );
}

function formatNumber(value: number, locale: string): string {
  try {
    return value.toLocaleString(locale || undefined);
  } catch {
    return value.toLocaleString();
  }
}

function formatAuditCell(entry: AuditEntry, col: AuditColumn, t: TFn, locale: string): string {
  switch (col) {
    case 'time':
      return auditScalar(entry, 'timestamp', locale) ?? auditScalar(entry, 'ts', locale) ?? '—';
    case 'provider':
      return auditScalar(entry, 'provider_class', locale) ?? auditScalar(entry, 'provider_kind', locale) ?? '—';
    case 'model':
      return auditScalar(entry, 'model_id', locale) ?? '—';
    case 'files_sent':
      return formatAuditFiles(entry, locale);
    case 'tokens':
      return formatAuditTokens(entry, locale);
    case 'cost':
      return formatAuditCost(entry, locale);
    case 'purpose':
      return (
        auditScalar(entry, 'prompt_name', locale)
        ?? auditScalar(entry, 'event_type', locale)
        ?? auditScalar(entry, 'action', locale)
        ?? auditScalar(entry, 'execution_origin', locale)
        ?? '—'
      );
    case 'status':
      return formatAuditStatus(entry, t, locale);
    default:
      return '—';
  }
}

function auditScalar(entry: AuditEntry, key: keyof AuditEntry, locale: string): string | null {
  const value = entry[key];
  if (typeof value === 'string' && value.trim() !== '') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return formatNumber(value, locale);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return null;
}

function auditNumber(entry: AuditEntry, key: keyof AuditEntry): number | null {
  const value = entry[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function formatAuditFiles(entry: AuditEntry, locale: string): string {
  const explicit = auditScalar(entry, 'files_sent', locale);
  if (explicit) return explicit;
  const fileCount = auditNumber(entry, 'file_count');
  if (fileCount != null) return formatNumber(fileCount, locale);
  if (Array.isArray(entry.files)) return formatNumber(entry.files.length, locale);
  return '—';
}

function formatAuditTokens(entry: AuditEntry, locale: string): string {
  const input = auditNumber(entry, 'input_tokens');
  const output = auditNumber(entry, 'output_tokens');
  if (input != null && output != null) return formatNumber(input + output, locale);
  if (input != null) return formatNumber(input, locale);
  if (output != null) return formatNumber(output, locale);
  return '—';
}

function formatAuditCost(entry: AuditEntry, locale: string): string {
  const cost = auditNumber(entry, 'cost_usd');
  if (cost != null) return `$${cost.toFixed(4)}`;
  return auditScalar(entry, 'cost_usd', locale) ?? '—';
}

function formatAuditStatus(entry: AuditEntry, t: TFn, locale: string): string {
  const explicit = auditScalar(entry, 'status', locale);
  if (explicit) return explicit;
  const event = auditScalar(entry, 'event_type', locale) ?? auditScalar(entry, 'action', locale);
  const note = auditScalar(entry, 'note', locale)?.toLowerCase();
  if (event?.toLowerCase().includes('error') || note?.includes('error')) {
    return t('Settings_page.audit_status_error');
  }
  return event ? t('Settings_page.audit_status_recorded') : '—';
}
