import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import LanguageSwitcher from '../components/LanguageSwitcher';
import ProviderCard from '../components/ProviderCard';
import {
  getConfig, getDoctor, getProviders, getUsage, getAudit, getInstallTargets,
  putConfig,
} from '../api/config';
import {
  createProvider, updateProvider, deleteProvider, probeProvider,
} from '../api/providers';
import type {
  AuditEntry, CaptureConfig, ConfigResponse, DoctorCheck, LlmConfig, ProviderSummary,
  UsageResponse, AuditResponse, InstallTarget,
} from '../api/config';
import type { ProviderCreateInput, ProviderUpdateInput } from '../api/types';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { mapDoctorMessage } from '../utils/doctor';
import '../components/Settings.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));

type TabId = 'account' | 'provider' | 'capture' | 'privacy' | 'audit' | 'preferences' | 'integrations';

const TAB_IDS: TabId[] = [
  'account', 'provider', 'capture', 'privacy',
  'audit', 'preferences', 'integrations',
];

const TAB_EN: Record<TabId, string> = {
  account: 'account', provider: 'provider', capture: 'capture', privacy: 'privacy',
  audit: 'audit', preferences: 'preferences', integrations: 'integrations',
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

type SettingsResource = 'config' | 'doctor' | 'providers' | 'usage' | 'audit' | 'installTargets';

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

export default function SettingsPage() {
  const { t, locale } = useTranslation();
  const [active, setActive] = useState<TabId>('privacy');
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
        getUsage(s), getAudit(s), getInstallTargets(s),
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

  useEffect(() => {
    void fetchAll();
    return () => abortRef.current?.abort();
  }, [fetchAll]);

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
                onClick={() => setActive(id)}
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
                  setActive(TAB_IDS[next]);
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
                tabIndex={active === id ? 0 : -1}
                aria-hidden={active !== id}
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
            {checks.map(check => (
              <div className="doctor-check" key={check.name}>
                <div className={`doctor-check__icon doctor-check__icon--${check.status}`} aria-hidden="true">
                  {check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '✗'}
                </div>
                <div className="doctor-check__text">{mapDoctorMessage(check, t)}</div>
                <div className="doctor-check__status">
                  {t(CHECK_STATUS_KEY[check.status])}
                </div>
              </div>
            ))}
            {checks.length === 0 && (
              <div className="u-muted-sm">{t('Settings_page.doctor_running')}</div>
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
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Provider (merged Keys + Models + model config + LLM settings) */
/* ------------------------------------------------------------------ */

interface ProviderForm {
  generate_provider: string;
  generate_model: string;
  judge_provider: string;
  judge_model: string;
  llm: LlmConfig;
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

  const dirty = config && form && (
    form.generate_provider !== (config.generate_provider ?? '')
    || form.generate_model !== (config.generate_model ?? '')
    || form.judge_provider !== (config.judge_provider ?? '')
    || form.judge_model !== (config.judge_model ?? '')
    || form.llm.input_token_budget !== config.llm.input_token_budget
    || form.llm.output_token_budget !== config.llm.output_token_budget
    || form.llm.request_timeout_seconds !== config.llm.request_timeout_seconds
    || form.llm.max_concurrent !== config.llm.max_concurrent
    || form.llm.retry_attempts !== config.llm.retry_attempts
  );

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await putConfig({
        generate_provider: form.generate_provider,
        generate_model: form.generate_model,
        judge_provider: form.judge_provider,
        judge_model: form.judge_model,
        llm: form.llm,
      });
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
                const selectedProvider = providers.find(p => p.alias === selectedAlias);
                const modelOptions = selectedProvider?.available_models?.length
                  ? selectedProvider.available_models
                  : selectedProvider
                    ? [selectedProvider.model_name]
                    : [];
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
                        value={selectedAlias}
                        onChange={e => {
                          const alias = e.target.value;
                          setField(providerKey, alias as ProviderForm[typeof providerKey]);
                          const p = providers.find(p => p.alias === alias);
                          if (p) {
                            const firstModel = p.available_models?.length ? p.available_models[0] : p.model_name;
                            setField(modelKey, firstModel as ProviderForm[typeof modelKey]);
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
                          value={modelOptions.includes(currentModel) ? currentModel : ''}
                          onChange={e => setField(modelKey, e.target.value as ProviderForm[typeof modelKey])}
                        >
                          {!modelOptions.includes(currentModel) && currentModel && (
                            <option value="">{currentModel}</option>
                          )}
                          {modelOptions.map(m => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          className="settings-input settings-input--model"
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
  if (audit.entries.length === 0) {
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
        <span className="u-muted-sm">{t('Settings_page.audit_last_n', { count: String(audit.entries.length) })}</span>
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
              {audit.entries.map((entry, i) => (
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

interface PreferencesForm {
  output_lang: string;
  learnability_threshold: number;
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
      setForm({
        output_lang: config.llm.output_lang ?? 'auto',
        learnability_threshold: config.learn.learnability_threshold ?? 0.3,
      });
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

  const dirty = config && form && (
    form.output_lang !== (config.llm.output_lang ?? 'auto')
    || form.learnability_threshold !== (config.learn.learnability_threshold ?? 0.3)
  );

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    setSaveError(null);
    setSaveOk(false);
    try {
      await putConfig({
        llm: { output_lang: form.output_lang },
        learn: { learnability_threshold: form.learnability_threshold },
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

function CaptureTab({
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
  const capture = config?.capture;
  const [form, setForm] = useState<CaptureConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (capture) setForm({ ...capture });
  }, [capture]);

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

  const dirty = capture && (
    form.max_files !== capture.max_files
    || form.hard_limit !== capture.hard_limit
    || form.max_patch_bytes !== capture.max_patch_bytes
    || form.file_ranking !== capture.file_ranking
    || form.symbol_extractor !== capture.symbol_extractor
  );

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

          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.capture_max_files')}</h3>
              <p>{t('Settings_page.capture_max_files_desc')}</p>
            </div>
            <input
              type="number"
              className="settings-input"
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
            </div>
            <input
              type="number"
              className="settings-input"
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
            </div>
            <input
              type="number"
              className="settings-input"
              min={10000}
              max={100000000}
              step={100000}
              value={form.max_patch_bytes}
              onChange={e => setField('max_patch_bytes', Math.max(10000, Math.min(100000000, Number(e.target.value) || 10000)))}
            />
            <span className="u-muted-sm settings-field__suffix">
              ({(form.max_patch_bytes / 1_000_000).toFixed(1)} MB)
            </span>
          </div>

          <div className="settings-field">
            <div className="settings-field__label">
              <h3>{t('Settings_page.capture_file_ranking')}</h3>
              <p>{t('Settings_page.capture_file_ranking_desc')}</p>
            </div>
            <select
              className="settings-select"
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
}: {
  targets: InstallTarget[];
  failed: boolean;
  showGraphify: boolean;
  t: TFn;
  onRetry: () => void;
}) {
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
        <div className="settings-card__header"><h2>{t('Settings_page.section_integrations')}</h2></div>
        <div className="settings-card__body">
          {targets.length === 0 && <div className="u-muted-sm">{t('Settings_page.integration_empty')}</div>}
          {targets.map(target => {
            const statusKey = INTEGRATION_STATUS_KEY[target.status];
            const badgeVariant = target.status === 'installed'
              ? 'configured'
              : target.status === 'available'
                ? 'unknown'
                : 'missing';
            return (
              <div className="settings-field" key={target.name}>
                <div className="settings-field__label">
                  <h3>{target.display_name}</h3>
                  <p>{target.description}</p>
                </div>
                <span className={`settings-field__badge settings-field__badge--${badgeVariant}`}>
                  {t(statusKey)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */
/*  Shared sub-components                                              */
/* ------------------------------------------------------------------ */

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
    return value.toLocaleString(locale || 'en');
  } catch {
    return value.toLocaleString('en');
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
