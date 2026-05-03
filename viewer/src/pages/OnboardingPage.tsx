import AppShell from '../components/AppShell';
import { useTranslation } from '../i18n/useTranslation';
import { getDoctor } from '../api/config';
import type { DoctorCheck } from '../api/config';
import { useCallback, useEffect, useRef, useState } from 'react';
import Skeleton from '../components/Skeleton';
import { mapDoctorMessage } from '../utils/doctor';
import '../components/Onboarding.css';

const STEPS = [
  { key: '1', titleKey: 'Onboarding.step1_title', descKey: 'Onboarding.step1_desc' },
  { key: '2', titleKey: 'Onboarding.step2_title', descKey: 'Onboarding.step2_desc' },
  { key: '3', titleKey: 'Onboarding.step3_title', descKey: 'Onboarding.step3_desc' },
  { key: '4', titleKey: 'Onboarding.step4_title', descKey: 'Onboarding.step4_desc' },
] as const;

export default function OnboardingPage() {
  const { t } = useTranslation();
  const [checks, setChecks] = useState<DoctorCheck[]>([]);
  const [loading, setLoading] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  const currentStep = (() => {
    const repoOk = checks.find((c) => c.name === 'repo_root')?.status === 'pass';
    const configOk = checks.find((c) => c.name === 'config_valid')?.status === 'pass';
    if (!repoOk) return 2;
    if (!configOk) return 3;
    return 4;
  })();

  const fetchDoctor = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    try {
      const res = await getDoctor({ signal: controller.signal });
      if (!controller.signal.aborted) setChecks(res.checks);
    } catch {
      // doctor is optional, proceed with empty checks
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDoctor();
    return () => abortRef.current?.abort();
  }, [fetchDoctor]);

  return (
    <AppShell>
      <div className="onboarding">
        <div className="review__eyebrow">§ {t('Onboarding.title')}</div>
        <h1 className="onboarding__title">{t('Onboarding.title')}</h1>
        <div className="onboarding__sub">{t('Onboarding.subtitle')}</div>

        {/* Stepper */}
        <div className="stepper">
          {STEPS.map((step, i) => {
            const stepNum = i + 1;
            const state = stepNum < currentStep ? 'done' : stepNum === currentStep ? 'current' : '';
            return (
              <div
                key={step.key}
                className={`stepper__step${state ? ` stepper__step--${state}` : ''}`}
              >
                <div className="stepper__number">
                  {state === 'done' ? '✓' : step.key}
                </div>
                <div>
                  <h2 className="stepper__title">{t(step.titleKey)}</h2>
                  <p>{t(step.descKey)}</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Content grid */}
        <div className="onboarding__grid">
          <div className="settings-card">
            <div className="settings-card__header">
              <h3>{t('Onboarding.cli_commands')}</h3>
            </div>
            <div className="settings-card__body">
              <pre style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                background: 'var(--subtle)',
                padding: 16,
                borderRadius: 'var(--r-md, 8px)',
                margin: 0,
                whiteSpace: 'pre-wrap',
              }}>
{`pip install ahadiff
cd your-repo
ahadiff init
ahadiff doctor
ahadiff learn HEAD~1..HEAD`}
              </pre>
            </div>
          </div>

          <div className="settings-card">
            <div className="settings-card__header">
              <h3>{t('Settings_page.section_doctor')}</h3>
            </div>
            <div className="settings-card__body">
              {loading ? (
                <Skeleton variant="card" height="100px" />
              ) : checks.length > 0 ? (
                checks.map((check) => (
                  <div className="doctor-check" key={check.name}>
                    <div className={`doctor-check__icon doctor-check__icon--${check.status}`}>
                      {check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '✗'}
                    </div>
                    <div className="doctor-check__text">{mapDoctorMessage(check, t)}</div>
                  </div>
                ))
              ) : (
                <div className="u-muted-sm">
                  {t('Onboarding.step2_desc')}
                </div>
              )}
            </div>
          </div>
        </div>

        {/*
         * Phase 4G: Step 4 preview card.
         * Mirrors V6 (AhaDiff Warm v6.html L2452-2475) "first learn run"
         * preview — three columns showing what AhaDiff produces from a SPEC
         * + diff: the SPEC anchor, the diff stats, the resulting verdict.
         * Numbers below are illustrative; real data plugs in once the user
         * runs `ahadiff learn`.
         */}
        <div className="settings-card onboarding__preview">
          <div className="settings-card__header">
            <h3>{t('Onboarding.step4_preview_title')}</h3>
            <span className="ratchet-card__meta">{t('Onboarding.step4_preview_meta')}</span>
          </div>
          <div className="settings-card__body">
            <div className="onboarding__preview-grid">
              <div className="onboarding__preview-cell">
                <div className="eyebrow">{t('Onboarding.preview_spec_label')}</div>
                <div className="onboarding__preview-text mono">
                  {t('Onboarding.preview_spec_body')}
                </div>
              </div>
              <div className="onboarding__preview-cell">
                <div className="eyebrow">{t('Onboarding.preview_diff_label')}</div>
                <div className="onboarding__preview-text mono">
                  {t('Onboarding.preview_diff_body')}
                </div>
              </div>
              <div className="onboarding__preview-cell">
                <div className="eyebrow">{t('Onboarding.preview_verdict_label')}</div>
                <div className="onboarding__preview-verdict">
                  <span className="verdict-badge verdict-badge--CAUTION">
                    {t('Verdict.CAUTION')} · 78
                  </span>
                  <p className="onboarding__preview-text">
                    {t('Onboarding.preview_verdict_body')}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
