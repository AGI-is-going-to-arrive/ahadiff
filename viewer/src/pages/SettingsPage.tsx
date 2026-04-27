import { useCallback, useEffect, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton, { SkeletonGroup } from '../components/Skeleton';
import { getConfig, getDoctor } from '../api/config';
import type { ConfigResponse, DoctorCheck } from '../api/config';
import { useTranslation } from '../i18n/useTranslation';
import { mapDoctorMessage } from '../utils/doctor';
import '../components/Settings.css';

export default function SettingsPage() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [checks, setChecks] = useState<DoctorCheck[]>([]);
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
      const [cfgRes, docRes] = await Promise.all([
        getConfig({ signal: controller.signal }),
        getDoctor({ signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setConfig(cfgRes);
      setChecks(docRes.checks);
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
          <Skeleton variant="card" height="150px" />
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

        {/* Configuration */}
        <div className="settings-card">
          <div className="settings-card__header">
            <h3>{t('Settings_page.section_config')}</h3>
          </div>
          <div className="settings-card__body">
            {config && (
              <>
                <ConfigField label={t('Settings.language')} value={config.lang ?? 'en'} />
                <ConfigField label={t('Settings_page.privacy_mode')} value={config.privacy_mode ?? 'strict_local'} />
                <ConfigField label={t('Settings_page.generate_model')} value={config.generate_model ?? '-'} />
                <ConfigField label={t('Settings_page.judge_model')} value={config.judge_model ?? '-'} />
                <ConfigField label={t('Settings_page.serve_port')} value={config.serve_port ? String(config.serve_port) : '8384'} />
                {config.key_status && Object.entries(config.key_status).map(([provider, status]) => (
                  <div className="settings-field" key={provider}>
                    <div className="settings-field__label">
                      <h4>{t('Settings_page.provider_api_key', { provider })}</h4>
                    </div>
                    <span className={`settings-field__badge settings-field__badge--${status === 'configured' ? 'configured' : 'missing'}`}>
                      {status === 'configured' ? t('Settings_page.key_configured') : t('Settings_page.key_missing')}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Doctor Checks */}
        <div className="settings-card">
          <div className="settings-card__header">
            <h3>{t('Settings_page.section_doctor')}</h3>
          </div>
          <div className="settings-card__body">
            {checks.map((check) => (
              <div className="doctor-check" key={check.name}>
                <div className={`doctor-check__icon doctor-check__icon--${check.status}`}>
                  {check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '✗'}
                </div>
                <div className="doctor-check__text">{mapDoctorMessage(check, t)}</div>
                <div className="doctor-check__status">{t(`Settings_page.check_${check.status}` as 'Settings_page.check_pass')}</div>
              </div>
            ))}
            {checks.length === 0 && (
              <div className="u-muted-sm">{t('Settings_page.doctor_running')}</div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}

function ConfigField({ label, value }: { label: string; value: string }) {
  return (
    <div className="settings-field">
      <div className="settings-field__label">
        <h4>{label}</h4>
      </div>
      <div className="settings-field__value">{value}</div>
    </div>
  );
}
