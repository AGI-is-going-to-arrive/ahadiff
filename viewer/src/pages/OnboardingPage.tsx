import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton from '../components/Skeleton';
import { useTranslation } from '../i18n/useTranslation';
import type { TranslateFn } from '../i18n/useTranslation';
import { fetchDbCheck, getDoctor } from '../api/config';
import type { DbCheckResult, DoctorCheck } from '../api/config';
import { mapDoctorMessage } from '../utils/doctor';
import {
  detectPlatform,
  getEnvVarCommand,
  getInstallCommand,
  getPlatformLabel,
  getShellHint,
  type Platform,
} from '../utils/platform';
import '../components/Onboarding.css';

const STEPS = [
  { key: '1', titleKey: 'Onboarding.step1_title', descKey: 'Onboarding.step1_desc' },
  { key: '2', titleKey: 'Onboarding.step2_title', descKey: 'Onboarding.step2_desc' },
  { key: '3', titleKey: 'Onboarding.step3_title', descKey: 'Onboarding.step3_desc' },
  { key: '4', titleKey: 'Onboarding.step4_title', descKey: 'Onboarding.step4_desc' },
] as const;

type StepNumber = 1 | 2 | 3 | 4;

/**
 * CopyButton — small clipboard button with brief "Copied!" feedback.
 *
 * Uses `navigator.clipboard.writeText()` when available and falls back to
 * the legacy `document.execCommand('copy')` path for environments where the
 * async clipboard API is gated (e.g. insecure contexts or some embedded
 * webviews). Failure is silent — copy is a non-essential affordance and the
 * underlying command text is always visible in the adjacent <pre>.
 */
function CopyButton({ text, label, copiedLabel }: { text: string; label: string; copiedLabel: string }) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const flashCopied = useCallback(() => {
    if (resetTimerRef.current !== null) {
      window.clearTimeout(resetTimerRef.current);
    }
    setCopied(true);
    resetTimerRef.current = window.setTimeout(() => {
      setCopied(false);
      resetTimerRef.current = null;
    }, 1400);
  }, []);

  const handleCopy = useCallback(() => {
    const clipboard: Clipboard | undefined = navigator.clipboard;
    if (clipboard && typeof clipboard.writeText === 'function') {
      clipboard.writeText(text).then(flashCopied, () => fallbackCopy(text, flashCopied));
      return;
    }
    fallbackCopy(text, flashCopied);
  }, [text, flashCopied]);

  return (
    <button
      type="button"
      className={`onboarding__copy-btn${copied ? ' onboarding__copy-btn--copied' : ''}`}
      aria-label={copied ? copiedLabel : label}
      aria-live="polite"
      onClick={handleCopy}
    >
      {copied ? `✓ ${copiedLabel}` : label}
    </button>
  );
}

/**
 * Legacy clipboard fallback using a hidden textarea + execCommand.
 * Kept entirely synchronous so it works inside the same user gesture frame.
 */
function fallbackCopy(text: string, onSuccess: () => void): void {
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'absolute';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(textarea);
    if (ok) onSuccess();
  } catch {
    // copy is a non-essential affordance — fail silently
  }
}

/** A reusable command block that pairs a <pre> with a CopyButton. */
function CommandBlock({ command, t }: { command: string; t: TranslateFn }) {
  return (
    <div className="onboarding__command-block">
      <pre className="onboarding__command-block-code">{command}</pre>
      <CopyButton text={command} label={t('Onboarding.copy')} copiedLabel={t('Onboarding.copied')} />
    </div>
  );
}

interface DoctorState {
  checks: DoctorCheck[];
  loading: boolean;
}

interface DbCheckState {
  result: DbCheckResult | null;
  loading: boolean;
}

/**
 * Compute the active onboarding step from doctor checks.
 *
 * - repo_root pass → step 2 done (we know we're inside an init'd repo)
 * - config_valid pass → step 3 done (provider config resolves)
 * - both pass → step 4 (or "complete" if the user has actually run learn)
 *
 * Step 1 (install) is implied by being able to load this page (the user is
 * looking at the React viewer, served by `ahadiff serve` — so the package
 * is installed). Step 4 completion is best-effort: we treat all-pass doctor
 * as ready for a learn run; we do NOT detect run history here because the
 * doctor endpoint is the only signal this page subscribes to.
 */
function computeCurrentStep(checks: DoctorCheck[]): StepNumber {
  const repoOk = checks.find((c) => c.name === 'repo_root')?.status === 'pass';
  const configOk = checks.find((c) => c.name === 'config_valid')?.status === 'pass';
  if (!repoOk) return 2;
  if (!configOk) return 3;
  return 4;
}

export default function OnboardingPage() {
  const { t } = useTranslation();
  const [doctor, setDoctor] = useState<DoctorState>({ checks: [], loading: true });
  const [dbCheck, setDbCheck] = useState<DbCheckState>({ result: null, loading: true });
  const [activeStep, setActiveStep] = useState<StepNumber>(1);
  const [activeStepTouched, setActiveStepTouched] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const platform = useMemo<Platform>(() => detectPlatform(), []);

  const installCmd = getInstallCommand(platform);
  const initCmd = 'cd your-repo && ahadiff init';
  const learnCmd = 'ahadiff learn HEAD~1..HEAD';
  const envCmd = getEnvVarCommand(platform, 'OPENAI_API_KEY', 'sk-...');
  const shellHint = getShellHint(platform);
  const platformLabel = getPlatformLabel(platform);

  const fetchDoctor = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setDoctor((prev) => ({ ...prev, loading: true }));
    setDbCheck((prev) => ({ ...prev, loading: true }));

    void getDoctor({ signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        setDoctor({ checks: res.checks, loading: false });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setDoctor({ checks: [], loading: false });
      });

    void fetchDbCheck({ signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        setDbCheck({ result: res, loading: false });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setDbCheck({ result: null, loading: false });
      });
  }, []);

  useEffect(() => {
    void fetchDoctor();
    return () => abortRef.current?.abort();
  }, [fetchDoctor]);

  const computedStep = computeCurrentStep(doctor.checks);
  const isComplete = computedStep === 4 && doctor.checks.length > 0
    && doctor.checks.every((c) => c.status === 'pass');

  // Auto-track the doctor-derived step until the user manually navigates.
  useEffect(() => {
    if (!activeStepTouched && !doctor.loading) {
      setActiveStep(computedStep);
    }
  }, [computedStep, activeStepTouched, doctor.loading]);

  const handleNext = useCallback(() => {
    setActiveStepTouched(true);
    setActiveStep((s) => (s < 4 ? ((s + 1) as StepNumber) : s));
  }, []);

  const handleBack = useCallback(() => {
    setActiveStepTouched(true);
    setActiveStep((s) => (s > 1 ? ((s - 1) as StepNumber) : s));
  }, []);

  const handleSkip = useCallback(() => {
    setActiveStepTouched(true);
    setActiveStep(computedStep);
  }, [computedStep]);

  // "Next" is enabled only when the doctor confirms the current step is done,
  // OR when we're on a step earlier than the doctor-derived step (the user
  // is just paging forward through already-done steps).
  const canAdvance = activeStep < computedStep;
  const canGoBack = activeStep > 1;

  return (
    <AppShell>
      <div className="onboarding">
        <div className="review__eyebrow">§ {t('Onboarding.title')}</div>
        <h1 className="onboarding__title">{t('Onboarding.title')}</h1>
        <div className="onboarding__sub">{t('Onboarding.subtitle')}</div>
        <div className="onboarding__platform-hint" aria-live="polite">
          {t('Onboarding.platform_hint', { platform: platformLabel })}
        </div>

        {/* Stepper — visual progress indicator + click-to-jump for completed steps. */}
        <ol className="stepper" role="list" aria-label={t('Onboarding.title')}>
          {STEPS.map((step, i) => {
            const stepNum = (i + 1) as StepNumber;
            const isDone = stepNum < computedStep || isComplete;
            const isActive = stepNum === activeStep;
            const stateClasses = [
              isDone ? 'stepper__step--done' : '',
              isActive ? 'stepper__step--current' : '',
            ].filter(Boolean).join(' ');
            return (
              <li
                key={step.key}
                className={`stepper__step${stateClasses ? ` ${stateClasses}` : ''}`}
                aria-current={isActive ? 'step' : undefined}
              >
                <button
                  type="button"
                  className="stepper__jump"
                  onClick={() => {
                    setActiveStepTouched(true);
                    setActiveStep(stepNum);
                  }}
                  aria-label={`${t(step.titleKey)} — ${t(step.descKey)}`}
                >
                  <span className="stepper__number" aria-hidden="true">
                    {isDone ? '✓' : step.key}
                  </span>
                  <span className="stepper__label">
                    <span className="stepper__title">{t(step.titleKey)}</span>
                    <span className="stepper__desc">{t(step.descKey)}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        {/* Active step body */}
        <div className="onboarding__active-step">
          {activeStep === 1 && (
            <Step1Install installCmd={installCmd} shellHint={shellHint} t={t} />
          )}
          {activeStep === 2 && <Step2Init initCmd={initCmd} t={t} />}
          {activeStep === 3 && <Step3Configure envCmd={envCmd} platformLabel={platformLabel} t={t} />}
          {activeStep === 4 && (
            <Step4Learn
              learnCmd={learnCmd}
              t={t}
              loading={doctor.loading}
              checks={doctor.checks}
              isComplete={isComplete}
            />
          )}
        </div>

        {/* Step actions */}
        <div className="onboarding__actions">
          <button
            type="button"
            className="onboarding__btn onboarding__btn--ghost"
            onClick={handleBack}
            disabled={!canGoBack}
          >
            {t('Onboarding.back_step')}
          </button>
          {!isComplete && computedStep > activeStep && (
            <button
              type="button"
              className="onboarding__btn onboarding__btn--ghost"
              onClick={handleSkip}
            >
              {t('Onboarding.skip_setup')}
            </button>
          )}
          {!isComplete && (
            <button
              type="button"
              className="onboarding__btn onboarding__btn--primary"
              onClick={handleNext}
              disabled={!canAdvance}
            >
              {t('Onboarding.next_step')}
            </button>
          )}
          {isComplete && (
            <a href="#/" className="onboarding__btn onboarding__btn--primary">
              {t('Onboarding.complete_cta')}
            </a>
          )}
        </div>

        {/* Doctor card — always shown so the user can re-check status. */}
        <div className="settings-card onboarding__doctor">
          <div className="settings-card__header">
            <h2>{t('Settings_page.section_doctor')}</h2>
          </div>
          <div className="settings-card__body">
            {doctor.loading ? (
              <Skeleton variant="card" height="100px" />
            ) : doctor.checks.length > 0 ? (
              doctor.checks.map((check) => (
                <div className="doctor-check" key={check.name}>
                  <div className={`doctor-check__icon doctor-check__icon--${check.status}`}>
                    {check.status === 'pass' ? '✓' : check.status === 'warn' ? '!' : '✗'}
                  </div>
                  <div className="doctor-check__text">{mapDoctorMessage(check, t)}</div>
                </div>
              ))
            ) : (
              <div className="u-muted-sm">{t('Onboarding.step2_desc')}</div>
            )}
          </div>
        </div>

        {/*
         * Database health card — surfaces /api/db/check so the user can see
         * review.sqlite schema version, integrity quick_check, and counts of
         * accumulated events / cards. Independent of /api/doctor so a flaky
         * sub-endpoint never hides the rest of the page.
         */}
        <div className="settings-card onboarding__db-check">
          <div className="settings-card__header">
            <h2>{t('Doctor.db_title')}</h2>
          </div>
          <div className="settings-card__body">
            {dbCheck.loading ? (
              <Skeleton variant="card" height="80px" />
            ) : dbCheck.result ? (
              <>
                <div className="doctor-check">
                  <div
                    className={`doctor-check__icon doctor-check__icon--${
                      dbCheck.result.healthy ? 'pass' : 'fail'
                    }`}
                  >
                    {dbCheck.result.healthy ? '✓' : '✗'}
                  </div>
                  <div className="doctor-check__text">
                    {dbCheck.result.healthy
                      ? t('Doctor.db_healthy')
                      : t('Doctor.db_unhealthy')}
                  </div>
                </div>
                <div className="doctor-check">
                  <div className="doctor-check__icon doctor-check__icon--pass">i</div>
                  <div className="doctor-check__text">
                    {t('Doctor.db_schema', { version: String(dbCheck.result.schema_version) })}
                    {' · '}
                    {dbCheck.result.quick_check}
                  </div>
                </div>
                <div className="doctor-check">
                  <div className="doctor-check__icon doctor-check__icon--pass">i</div>
                  <div className="doctor-check__text">
                    {t('Doctor.db_events', { count: String(dbCheck.result.event_count) })}
                    {' · '}
                    {t('Doctor.db_cards', { count: String(dbCheck.result.card_count) })}
                  </div>
                </div>
              </>
            ) : (
              <div className="u-muted-sm">{t('Doctor.db_unhealthy')}</div>
            )}
          </div>
        </div>

        {/*
         * Phase 4G: Step 4 preview card. Mirrors V6 "first learn run" panel.
         * Numbers below are illustrative; real data plugs in once the user runs
         * `ahadiff learn`.
         */}
        <div className="settings-card onboarding__preview">
          <div className="settings-card__header">
            <h2>{t('Onboarding.step4_preview_title')}</h2>
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

        {/* Completion banner — only shown when doctor confirms all-pass. */}
        {isComplete && (
          <div className="settings-card onboarding__complete" role="status">
            <div className="settings-card__body">
              <h2 className="onboarding__complete-title">{t('Onboarding.complete_title')}</h2>
              <p className="onboarding__complete-desc">{t('Onboarding.complete_desc')}</p>
              <a href="#/" className="onboarding__btn onboarding__btn--primary">
                {t('Onboarding.complete_cta')}
              </a>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

/* ----------------------------- Step bodies ----------------------------- */

function Step1Install({
  installCmd, shellHint, t,
}: { installCmd: string; shellHint: string; t: TranslateFn }) {
  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <h2>{t('Onboarding.step1_title')}</h2>
        <span className="ratchet-card__meta">
          {t('Onboarding.install_shell_hint', { shell: shellHint })}
        </span>
      </div>
      <div className="settings-card__body">
        <CommandBlock command={installCmd} t={t} />
      </div>
    </div>
  );
}

function Step2Init({ initCmd, t }: { initCmd: string; t: TranslateFn }) {
  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <h2>{t('Onboarding.step2_title')}</h2>
      </div>
      <div className="settings-card__body">
        <p className="onboarding__step-desc">{t('Onboarding.init_desc')}</p>
        <CommandBlock command={initCmd} t={t} />
      </div>
    </div>
  );
}

function Step3Configure({
  envCmd, platformLabel, t,
}: { envCmd: string; platformLabel: string; t: TranslateFn }) {
  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <h2>{t('Onboarding.step3_title')}</h2>
        <span className="ratchet-card__meta">{platformLabel}</span>
      </div>
      <div className="settings-card__body">
        <p className="onboarding__step-desc">{t('Onboarding.configure_hint')}</p>
        <CommandBlock command={envCmd} t={t} />
        <a
          href="#/settings?tab=provider"
          className="onboarding__btn onboarding__btn--primary onboarding__deep-link"
        >
          {t('Onboarding.configure_link')}
        </a>
      </div>
    </div>
  );
}

function Step4Learn({
  learnCmd, t, loading, checks, isComplete,
}: {
  learnCmd: string;
  t: TranslateFn;
  loading: boolean;
  checks: DoctorCheck[];
  isComplete: boolean;
}) {
  return (
    <div className="settings-card">
      <div className="settings-card__header">
        <h2>{t('Onboarding.step4_title')}</h2>
      </div>
      <div className="settings-card__body">
        <p className="onboarding__step-desc">{t('Onboarding.learn_desc')}</p>
        <CommandBlock command={learnCmd} t={t} />
        {loading && <Skeleton variant="card" height="60px" />}
        {!loading && isComplete && checks.length > 0 && (
          <div className="onboarding__step-ready">
            <span className="onboarding__step-ready-icon" aria-hidden="true">✓</span>
            <span>{t('Onboarding.complete_desc')}</span>
          </div>
        )}
      </div>
    </div>
  );
}
