import { useCallback, useEffect, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import LanguageSwitcher from '../components/LanguageSwitcher';
import {
  getConfig, getDoctor, getProviders, getUsage, getAudit, getInstallTargets,
} from '../api/config';
import type {
  AuditEntry, ConfigResponse, DoctorCheck, ProviderSummary,
  UsageResponse, AuditResponse, InstallTarget,
} from '../api/config';
import { useTranslation, type MessageKey, type TranslateFn } from '../i18n/useTranslation';
import { mapDoctorMessage } from '../utils/doctor';
import '../components/Settings.css';

type TabId = 'account' | 'keys' | 'models' | 'privacy' | 'audit' | 'language' | 'appearance' | 'integrations';

const TAB_IDS: TabId[] = [
  'account', 'keys', 'models', 'privacy',
  'audit', 'language', 'appearance', 'integrations',
];

const TAB_EN: Record<TabId, string> = {
  account: 'account', keys: 'keys', models: 'models', privacy: 'privacy',
  audit: 'audit', language: 'language', appearance: 'appearance', integrations: 'integrations',
};

const TAB_LABEL_KEY: Record<TabId, MessageKey> = {
  account: 'Settings_page.tab_account',
  keys: 'Settings_page.tab_keys',
  models: 'Settings_page.tab_models',
  privacy: 'Settings_page.tab_privacy',
  audit: 'Settings_page.tab_audit',
  language: 'Settings_page.tab_language',
  appearance: 'Settings_page.tab_appearance',
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
  const { t } = useTranslation();
  const [active, setActive] = useState<TabId>('privacy');
  const [data, setData] = useState<SettingsData>(EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
            onRetry={retry}
          />
        );
      case 'keys':
        return (
          <KeysTab
            config={data.config}
            failed={Boolean(data.failed.config)}
            t={t}
            onRetry={retry}
          />
        );
      case 'models':
        return (
          <ModelsTab
            providers={data.providers}
            failed={Boolean(data.failed.providers)}
            t={t}
            onRetry={retry}
          />
        );
      case 'privacy':
        return (
          <PrivacyTab
            config={data.config}
            failed={Boolean(data.failed.config)}
            t={t}
            onRetry={retry}
          />
        );
      case 'audit':
        return (
          <AuditTab
            audit={data.audit}
            failed={Boolean(data.failed.audit)}
            t={t}
            onRetry={retry}
          />
        );
      case 'language':
        return <LanguageTab t={t} />;
      case 'appearance':
        return <AppearanceTab t={t} />;
      case 'integrations':
        return (
          <IntegrationsTab
            targets={data.installTargets}
            failed={Boolean(data.failed.installTargets)}
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
                className="settings-content"
                role="tabpanel"
                aria-labelledby={`stab-${id}`}
                hidden={active !== id}
                tabIndex={active === id ? 0 : -1}
              >
                {active === id ? renderTabPanel(id) : null}
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
  onRetry,
}: {
  checks: DoctorCheck[];
  usage: UsageResponse | null;
  doctorFailed: boolean;
  usageFailed: boolean;
  t: TFn;
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
          <div className="settings-card__header"><h3>{t('Settings_page.section_doctor')}</h3></div>
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
          <div className="settings-card__header"><h3>{t('Settings_page.usage_title')}</h3></div>
          <div className="settings-card__body">
            <div className="mode-grid">
              <ModeCell eyebrow={t('Settings_page.usage_total_calls')} value={usage.total_calls.toLocaleString()} />
              <ModeCell
                eyebrow={t('Settings_page.usage_total_tokens')}
                value={(usage.total_input_tokens + usage.total_output_tokens).toLocaleString()}
              />
              <ModeCell eyebrow={t('Settings_page.usage_total_cost')} value={`$${usage.total_cost_usd.toFixed(4)}`} />
              <ModeCell
                eyebrow={t('Settings_page.usage_cache_hits')}
                value={String(usage.cache_hits)}
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
/*  Tab: Keys                                                          */
/* ------------------------------------------------------------------ */

function KeysTab({
  config,
  failed,
  t,
  onRetry,
}: {
  config: ConfigResponse | null;
  failed: boolean;
  t: TFn;
  onRetry: () => void;
}) {
  if (failed || !config) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_keys')}
        message={t('Settings_page.config_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }
  const entries = Object.entries(config.key_status);
  return (
    <div className="settings-card">
      <div className="settings-card__header"><h3>{t('Settings_page.section_keys')}</h3></div>
      <div className="settings-card__body">
        {entries.length === 0 && <div className="u-muted-sm">{t('Settings_page.provider_empty')}</div>}
        {entries.map(([provider, status]) => (
          <div className="settings-field" key={provider}>
            <div className="settings-field__label"><h4>{t('Settings_page.provider_api_key', { provider })}</h4></div>
            <span className={`settings-field__badge settings-field__badge--${status === 'configured' ? 'configured' : 'missing'}`}>
              {status === 'configured' ? t('Settings_page.key_configured') : t('Settings_page.key_missing')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Models (Provider Grid)                                        */
/* ------------------------------------------------------------------ */

function ModelsTab({
  providers,
  failed,
  t,
  onRetry,
}: {
  providers: ProviderSummary[];
  failed: boolean;
  t: TFn;
  onRetry: () => void;
}) {
  if (failed) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_providers')}
        message={t('Settings_page.provider_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }
  return (
    <div className="settings-card">
      <div className="settings-card__header"><h3>{t('Settings_page.section_providers')}</h3></div>
      <div className="settings-card__body">
        {providers.length === 0 && <div className="u-muted-sm">{t('Settings_page.provider_empty')}</div>}
        <div className="provider-grid">
          {providers.map(p => (
            <div className="provider-cell" key={p.alias}>
              <div className="provider-cell__eyebrow">{p.role ?? p.provider_kind}</div>
              <div className="provider-cell__name">
                {p.alias}
                <span
                  className={`settings-field__badge settings-field__badge--${p.key_status === 'configured' ? 'configured' : p.key_status === 'unknown' ? 'unknown' : 'missing'}`}
                >
                  {p.key_status === 'configured' ? t('Settings_page.key_configured')
                    : p.key_status === 'unknown' ? t('Settings_page.key_unknown')
                    : t('Settings_page.key_missing')}
                </span>
              </div>
              <dl className="provider-cell__meta">
                <dt>{t('Settings_page.provider_model')}</dt>
                <dd className="provider-cell__hl">{p.model_name}</dd>
                <dt>{t('Settings_page.provider_role')}</dt>
                <dd>{p.role ?? '—'}</dd>
                {p.probed_max_context != null && (
                  <>
                    <dt>{t('Settings_page.provider_context')}</dt>
                    <dd>{(p.probed_max_context / 1000).toFixed(0)}K</dd>
                  </>
                )}
                <dt>{t('Settings_page.provider_probed_label')}</dt>
                <dd>{p.probed ? t('Settings_page.provider_probed') : t('Settings_page.provider_not_probed')}</dd>
              </dl>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Privacy                                                       */
/* ------------------------------------------------------------------ */

function PrivacyTab({
  config,
  failed,
  t,
  onRetry,
}: {
  config: ConfigResponse | null;
  failed: boolean;
  t: TFn;
  onRetry: () => void;
}) {
  if (failed || !config) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_config')}
        message={t('Settings_page.config_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }
  const privacyMode = config.privacy_mode ?? 'strict_local';
  return (
    <>
      <div className="mode-summary">
        <div className="mode-grid">
          <ModeCell eyebrow={t('Settings_page.mode_generate')} value={config.generate_model ?? '—'} />
          <ModeCell eyebrow={t('Settings_page.mode_judge')} value={config.judge_model ?? '—'} />
          <ModeCell eyebrow={t('Settings_page.privacy_mode')} value={privacyMode} />
          <ModeCell eyebrow={t('Settings_page.serve_port')} value={config.serve_port ? String(config.serve_port) : '8384'} />
        </div>
        <div className="mode-summary__footer">{t('Settings_page.mode_offline_note')}</div>
      </div>

      <div className="settings-card">
        <div className="settings-card__header"><h3>{t('Settings_page.section_privacy_controls')}</h3></div>
        <div className="settings-card__body">
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
          <PrivacyControl
            title={t('Settings_page.privacy_raw_remote')}
            description={t('Settings_page.privacy_raw_remote_desc')}
            checked={privacyMode === 'explicit_remote'}
            t={t}
          />
        </div>
      </div>

      <div className="settings-card">
        <div className="settings-card__header"><h3>{t('Settings_page.section_config')}</h3></div>
        <div className="settings-card__body">
          <FieldRow label={t('Settings.language')} value={config.lang ?? 'en'} />
          <FieldRow label={t('Settings_page.privacy_mode')} value={privacyMode} />
          <FieldRow label={t('Settings_page.generate_model')} value={config.generate_model ?? '—'} />
          <FieldRow label={t('Settings_page.judge_model')} value={config.judge_model ?? '—'} />
          <FieldRow label={t('Settings_page.serve_port')} value={config.serve_port ? String(config.serve_port) : '8384'} />
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
  onRetry,
}: {
  audit: AuditResponse | null;
  failed: boolean;
  t: TFn;
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
        <div className="settings-card__header"><h3>{t('Settings_page.section_audit')}</h3></div>
        <div className="settings-card__body">
          <div className="u-muted-sm">{t('Settings_page.audit_empty')}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <h3>{t('Settings_page.section_audit')}</h3>
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
                    const display = formatAuditCell(entry, col, t);
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
/*  Tab: Language                                                      */
/* ------------------------------------------------------------------ */

function LanguageTab({ t }: { t: TFn }) {
  return (
    <div className="settings-card">
      <div className="settings-card__header"><h3>{t('Settings_page.section_language')}</h3></div>
      <div className="settings-card__body">
        <div className="settings-field">
          <div className="settings-field__label"><h4>{t('Settings.language')}</h4></div>
          <LanguageSwitcher />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Appearance                                                    */
/* ------------------------------------------------------------------ */

function AppearanceTab({ t }: { t: TFn }) {
  return (
    <div className="settings-card">
      <div className="settings-card__header"><h3>{t('Settings_page.section_appearance')}</h3></div>
      <div className="settings-card__body">
        <div className="u-muted-sm">{t('Settings_page.appearance_coming_soon')}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Tab: Integrations                                                  */
/* ------------------------------------------------------------------ */

function IntegrationsTab({
  targets,
  failed,
  t,
  onRetry,
}: {
  targets: InstallTarget[];
  failed: boolean;
  t: TFn;
  onRetry: () => void;
}) {
  if (failed) {
    return (
      <UnavailableCard
        title={t('Settings_page.section_integrations')}
        message={t('Settings_page.integration_unavailable')}
        t={t}
        onRetry={onRetry}
      />
    );
  }
  return (
    <div className="settings-card">
      <div className="settings-card__header"><h3>{t('Settings_page.section_integrations')}</h3></div>
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
                <h4>{target.display_name}</h4>
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
      <div className="settings-card__header"><h3>{title}</h3></div>
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
        <h4>{title}</h4>
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
  const stateLabel = checked ? t('Settings_page.switch_on') : t('Settings_page.switch_off');
  return (
    <span
      className={`settings-toggle${checked ? ' is-on' : ''}`}
      role="switch"
      aria-checked={checked}
      aria-label={`${label}: ${stateLabel}`}
      aria-readonly="true"
    >
      <span className="settings-toggle__knob" aria-hidden="true" />
      <span className="u-sr-only">{stateLabel}</span>
    </span>
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

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="settings-field">
      <div className="settings-field__label"><h4>{label}</h4></div>
      <div className="settings-field__value">{value}</div>
    </div>
  );
}

function formatAuditCell(entry: AuditEntry, col: AuditColumn, t: TFn): string {
  switch (col) {
    case 'time':
      return auditScalar(entry, 'timestamp') ?? auditScalar(entry, 'ts') ?? '—';
    case 'provider':
      return auditScalar(entry, 'provider_class') ?? auditScalar(entry, 'provider_kind') ?? '—';
    case 'model':
      return auditScalar(entry, 'model_id') ?? '—';
    case 'files_sent':
      return formatAuditFiles(entry);
    case 'tokens':
      return formatAuditTokens(entry);
    case 'cost':
      return formatAuditCost(entry);
    case 'purpose':
      return (
        auditScalar(entry, 'prompt_name')
        ?? auditScalar(entry, 'event_type')
        ?? auditScalar(entry, 'action')
        ?? auditScalar(entry, 'execution_origin')
        ?? '—'
      );
    case 'status':
      return formatAuditStatus(entry, t);
    default:
      return '—';
  }
}

function auditScalar(entry: AuditEntry, key: keyof AuditEntry): string | null {
  const value = entry[key];
  if (typeof value === 'string' && value.trim() !== '') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString();
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return null;
}

function auditNumber(entry: AuditEntry, key: keyof AuditEntry): number | null {
  const value = entry[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function formatAuditFiles(entry: AuditEntry): string {
  const explicit = auditScalar(entry, 'files_sent');
  if (explicit) return explicit;
  const fileCount = auditNumber(entry, 'file_count');
  if (fileCount != null) return fileCount.toLocaleString();
  if (Array.isArray(entry.files)) return entry.files.length.toLocaleString();
  return '—';
}

function formatAuditTokens(entry: AuditEntry): string {
  const input = auditNumber(entry, 'input_tokens');
  const output = auditNumber(entry, 'output_tokens');
  if (input != null && output != null) return (input + output).toLocaleString();
  if (input != null) return input.toLocaleString();
  if (output != null) return output.toLocaleString();
  return '—';
}

function formatAuditCost(entry: AuditEntry): string {
  const cost = auditNumber(entry, 'cost_usd');
  if (cost != null) return `$${cost.toFixed(4)}`;
  return auditScalar(entry, 'cost_usd') ?? '—';
}

function formatAuditStatus(entry: AuditEntry, t: TFn): string {
  const explicit = auditScalar(entry, 'status');
  if (explicit) return explicit;
  const event = auditScalar(entry, 'event_type') ?? auditScalar(entry, 'action');
  const note = auditScalar(entry, 'note')?.toLowerCase();
  if (event?.toLowerCase().includes('error') || note?.includes('error')) {
    return t('Settings_page.audit_status_error');
  }
  return event ? t('Settings_page.audit_status_recorded') : '—';
}
