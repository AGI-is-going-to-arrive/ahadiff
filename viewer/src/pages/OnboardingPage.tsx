import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import AppShell from '../components/AppShell';
import Skeleton from '../components/Skeleton';
import { CommandBlock } from '../components/CommandBlock';
import { DiagnosticRow } from '../components/DiagnosticRow';
import type { DiagnosticStatus } from '../components/DiagnosticRow';
import { useTranslation } from '../i18n/useTranslation';
import type { MessageKey, TranslateFn } from '../i18n/useTranslation';
import { fetchDbCheck, getConfig, getDoctor, getProviders } from '../api/config';
import { useRunsStore } from '../state/runs-store';
import { useLearnStore } from '../state/learn-store';
import type { ConfigResponse, DbCheckResult, DoctorCheck, ProviderSummary } from '../api/config';
import type { RunSummary } from '../api/types';
import LearnSourcePicker, { type LearnSource } from '../components/LearnSourcePicker';
import { safeVerdict } from '../utils/verdict';
import { isProviderOnlySensitiveCheck, mapDoctorMessage } from '../utils/doctor';
import {
  detectPlatform,
  getEnvVarCommand,
  getInstallCommand,
  getPlatformLabel,
  getShellHint,
  type Platform,
} from '../utils/platform';
import '../components/Onboarding.css';

const LearnModeDialog = lazy(() => import('../components/LearnModeDialog'));

interface StepDef {
  id: string;
  titleKey: MessageKey;
  descKey: MessageKey;
}

const STEPS: ReadonlyArray<StepDef> = [
  { id: '1', titleKey: 'Onboarding.step1_title', descKey: 'Onboarding.step1_desc' },
  { id: '2', titleKey: 'Onboarding.step2_title', descKey: 'Onboarding.step2_desc' },
  { id: '3', titleKey: 'Onboarding.step3_title', descKey: 'Onboarding.step3_desc' },
  { id: '4', titleKey: 'Onboarding.step4_title', descKey: 'Onboarding.step4_desc' },
];

type StepNumber = 1 | 2 | 3 | 4;
type StepState = 'done' | 'current' | 'pending';

interface DoctorState {
  checks: DoctorCheck[];
  loading: boolean;
}

interface DbCheckState {
  result: DbCheckResult | null;
  loading: boolean;
}

interface NavTarget {
  id: string;
  labelKey: MessageKey;
  alwaysVisible: boolean;
}

const NAV_TARGETS: ReadonlyArray<NavTarget> = [
  { id: 'steps', labelKey: 'Onboarding.nav_steps', alwaysVisible: true },
  { id: 'diagnostics', labelKey: 'Onboarding.nav_diagnostics', alwaysVisible: true },
  { id: 'preview', labelKey: 'Onboarding.nav_preview', alwaysVisible: true },
  { id: 'completion', labelKey: 'Onboarding.nav_completion', alwaysVisible: false },
];

/**
 * Compute the active onboarding step from local diagnostics and provider configuration.
 *
 * - workspace state missing -> step 1 needs folder setup
 * - valid TOML alone does not establish a selected generation provider
 * - provider selection plus valid diagnostics -> step 4
 *
 * Step 3 is the optional agent guidance install. It links to the real
 * Settings write flow rather than pretending doctor can validate it.
 */
export type ProviderSetupStatus = 'loading' | 'error' | 'missing' | 'select' | 'missing_key' | 'configured';

const PROVIDER_SETUP_MESSAGES: Record<ProviderSetupStatus, MessageKey> = {
  loading: 'Onboarding.provider_loading',
  error: 'Onboarding.provider_load_failed',
  missing: 'Onboarding.provider_missing',
  select: 'Onboarding.provider_select',
  missing_key: 'Onboarding.provider_key_missing',
  configured: 'Onboarding.provider_configured',
};

export function resolveProviderSetupStatus(
  config: Pick<ConfigResponse, 'generate_provider'>,
  providers: ReadonlyArray<ProviderSummary>,
): Exclude<ProviderSetupStatus, 'loading' | 'error'> {
  if (providers.length === 0) return 'missing';
  const alias = config.generate_provider?.trim() ?? '';
  const selected = alias
    ? providers.find(provider => provider.alias === alias)
    : providers.length === 1 ? providers[0] : undefined;
  if (!selected) return 'select';
  if (!selected.provider_class.trim() || !selected.model_name.trim() || !selected.base_url.trim()) {
    return 'missing';
  }
  if (selected.key_status === 'missing') return 'missing_key';
  // A saved selection is not evidence of authentication or a successful model call.
  return 'configured';
}

function computeCurrentStep(checks: DoctorCheck[], providerSetup: ProviderSetupStatus): StepNumber {
  const repoOk = checks.find((c) => c.name === 'repo_root')?.status === 'pass';
  const configOk = checks.find((c) => c.name === 'config_valid')?.status === 'pass';
  if (!repoOk) return 1;
  if (!configOk || providerSetup !== 'configured') return 2;
  return 4;
}

export default function OnboardingPage() {
  const { t } = useTranslation();
  const runs = useRunsStore((s) => s.runs);
  const loadRuns = useRunsStore((s) => s.loadRuns);
  const runsLoading = useRunsStore((s) => s.loading);
  const runsError = useRunsStore((s) => s.error);
  const runsLoadedAt = useRunsStore((s) => s.lastLoadedAt);
  const completedRunId = useLearnStore((s) =>
    s.phase === 'completed' ? s.task?.result_summary?.run_id ?? null : null,
  );
  const [doctor, setDoctor] = useState<DoctorState>({ checks: [], loading: true });
  const [dbCheck, setDbCheck] = useState<DbCheckState>({ result: null, loading: true });
  const [activeStep, setActiveStep] = useState<StepNumber>(1);
  const [activeStepTouched, setActiveStepTouched] = useState(false);
  const [learnSource, setLearnSource] = useState<LearnSource | null>(null);
  const [providerSetup, setProviderSetup] = useState<ProviderSetupStatus>('loading');
  const abortRef = useRef<AbortController | null>(null);

  const platform = useMemo<Platform>(() => detectPlatform(), []);

  const installCmd = getInstallCommand(platform);
  const initCmd = platform === 'windows'
    ? 'Set-Location .\\your-folder\nahadiff serve'
    : 'cd your-folder\nahadiff serve';
  const envCmd = getEnvVarCommand(platform, 'OPENAI_API_KEY', '<your-key>');
  const shellHint = getShellHint(platform);
  const platformLabel = getPlatformLabel(platform);

  const fetchDoctor = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setDoctor((prev) => ({ ...prev, loading: true }));
    setDbCheck((prev) => ({ ...prev, loading: true }));
    setProviderSetup('loading');

    void Promise.all([
      getConfig({ signal: controller.signal }),
      getProviders({ signal: controller.signal }),
    ]).then(([config, providers]) => {
      if (controller.signal.aborted) return;
      setProviderSetup(resolveProviderSetupStatus(config, providers.providers));
    }).catch(() => {
      if (!controller.signal.aborted) setProviderSetup('error');
    });

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

  useEffect(() => {
    void loadRuns().catch(() => {
      // The store retains the failure; PreviewSection renders a generic error.
    });
  }, [loadRuns]);

  useEffect(() => {
    if (!completedRunId) return undefined;
    const controller = new AbortController();
    void loadRuns(undefined, { signal: controller.signal }).catch(() => {
      // The task banner still links to the finished run if refreshing fails.
    });
    return () => controller.abort();
  }, [completedRunId, loadRuns]);

  const refreshPreview = useCallback(() => {
    // A manual retry must reach the server even if an earlier list is still cached.
    useRunsStore.setState({ lastLoadedAt: null });
    void loadRuns().catch(() => {
      // Preserve the previous run with an explicit refresh-failed state.
    });
  }, [loadRuns]);

  const latestPreviewRun = useMemo<RunSummary | null>(() => {
    if (runs.length === 0) return null;
    return [...runs].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )[0];
  }, [runs]);
  const computedStep = computeCurrentStep(doctor.checks, providerSetup);
  const isComplete =
    computedStep === 4 &&
    doctor.checks.length > 0 &&
    doctor.checks.every((c) => c.status === 'pass');

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

  const jumpTo = useCallback((stepNum: StepNumber) => {
    setActiveStepTouched(true);
    setActiveStep(stepNum);
  }, []);

  const canAdvance = activeStep < computedStep;
  const canGoBack = activeStep > 1;

  const stepStateFor = (stepNum: StepNumber): StepState => {
    // Doctor proves setup readiness, not an agent install or a completed lesson.
    if (stepNum === 3 || (stepNum === 4 && latestPreviewRun === null)) {
      return stepNum === activeStep ? 'current' : 'pending';
    }
    if (stepNum < computedStep || isComplete) return 'done';
    if (stepNum === activeStep) return 'current';
    return 'pending';
  };

  return (
    <AppShell globalShortcutsDisabled={learnSource !== null}>
      <div className="page active onboarding" data-page="onboarding" data-testid="onboarding-page">
        <header className="onboarding__head">
          <p className="onboarding__eyebrow review__eyebrow">{t('Onboarding.eyebrow')}</p>
          <h1 className="onboarding__title">{t('Onboarding.title')}</h1>
          <p className="onboarding__subtitle">{t('Onboarding.subtitle')}</p>
          <p className="onboarding__platform-hint" aria-live="polite">
            {t('Onboarding.platform_hint', { platform: platformLabel })}
          </p>
        </header>

        <SectionNav t={t} showCompletion={isComplete} />

        <section
          id="steps"
          className="onboarding-section"
          aria-label={t('Onboarding.nav_steps')}
        >
          <ol
            className="onboarding-steps"
            data-testid="onboarding-stepper"
            aria-label={t('Onboarding.steps_aria')}
          >
            {STEPS.map((step, i) => {
              const stepNum = (i + 1) as StepNumber;
              const state = stepStateFor(stepNum);
              return state === 'current' ? (
                <li
                  key={step.id}
                  className="onboarding-steps__item"
                  data-state={state}
                  aria-current="step"
                  data-testid={`onboarding-step-${stepNum}`}
                >
                  <button
                    type="button"
                    className="onboarding-steps__jump"
                    onClick={() => jumpTo(stepNum)}
                    aria-label={`${t(step.titleKey)} - ${t(step.descKey)}`}
                    data-testid={`onboarding-step-jump-${stepNum}`}
                  >
                    <span className="onboarding-steps__number" aria-hidden="true">
                      {stepNum}
                    </span>
                    <span className="onboarding-steps__label">
                      <span className="onboarding-steps__title">{t(step.titleKey)}</span>
                      <span className="onboarding-steps__desc">{t(step.descKey)}</span>
                    </span>
                  </button>
                </li>
              ) : (
                <li
                  key={step.id}
                  className="onboarding-steps__item"
                  data-state={state}
                  data-testid={`onboarding-step-${stepNum}`}
                >
                  <button
                    type="button"
                    className="onboarding-steps__jump"
                    onClick={() => jumpTo(stepNum)}
                    aria-label={`${t(step.titleKey)} - ${t(step.descKey)}`}
                    data-testid={`onboarding-step-jump-${stepNum}`}
                  >
                    <span className="onboarding-steps__number" aria-hidden="true">
                      {state === 'done' ? (
                        <CheckCircle2 size={12} aria-hidden="true" />
                      ) : (
                        stepNum
                      )}
                    </span>
                    <span className="onboarding-steps__label">
                      <span className="onboarding-steps__title">{t(step.titleKey)}</span>
                      <span className="onboarding-steps__desc">{t(step.descKey)}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>

          <p
            className="onboarding__step-desc"
            role={providerSetup === 'error' ? 'alert' : 'status'}
            data-testid="onboarding-provider-status"
          >
            {t(PROVIDER_SETUP_MESSAGES[providerSetup])}
          </p>

          <div
            className="onboarding-active surface-card"
            data-testid="onboarding-active-card"
          >
            <header className="surface-card__header">
              <h2 id="onboarding-active-title">
                {t(STEPS[activeStep - 1].titleKey)}
              </h2>
              {activeStep === 1 && (
                <span className="onboarding-active__meta">
                  {t('Onboarding.install_shell_hint', { shell: shellHint })}
                </span>
              )}
              {activeStep === 2 && (
                <span className="onboarding-active__meta">{platformLabel}</span>
              )}
              {activeStep === 4 && (
                <span className="onboarding-active__meta">
                  {t('Onboarding.step4_preview_meta')}
                </span>
              )}
            </header>
            <div className="surface-card__body">
              {activeStep === 1 && (
                <Step1PickRepo installCmd={installCmd} initCmd={initCmd} t={t} />
              )}
              {activeStep === 2 && <Step2ProviderKey envCmd={envCmd} t={t} />}
              {activeStep === 3 && <Step3InstallAgent t={t} />}
              {activeStep === 4 && (
                <Step4Learn
                  onSelectSource={setLearnSource}
                  t={t}
                  loading={doctor.loading}
                  isComplete={isComplete}
                  hasChecks={doctor.checks.length > 0}
                />
              )}
            </div>
          </div>

          {!isComplete && (
            <div
              className="onboarding-actions"
              role="group"
              aria-label={t('Onboarding.actions_label')}
              data-testid="onboarding-actions"
            >
              <button
                type="button"
                className="onboarding__btn onboarding__btn--ghost"
                onClick={handleBack}
                disabled={!canGoBack}
                data-testid="onboarding-cta-back"
              >
                {t('Onboarding.back_step')}
              </button>
              {computedStep > activeStep && (
                <button
                  type="button"
                  className="onboarding__btn onboarding__btn--ghost"
                  onClick={handleSkip}
                  data-testid="onboarding-cta-skip"
                >
                  {t('Onboarding.skip_setup')}
                </button>
              )}
              <button
                type="button"
                className="onboarding__btn onboarding__btn--primary onboarding-actions__next"
                onClick={handleNext}
                disabled={!canAdvance}
                data-testid="onboarding-cta-next"
              >
                {t('Onboarding.next_step')}
                <ArrowRight size={14} aria-hidden="true" />
              </button>
            </div>
          )}
        </section>

        <DiagnosticsSection
          t={t}
          doctor={doctor}
          dbCheck={dbCheck}
          onRefresh={fetchDoctor}
        />

        <PreviewSection
          t={t}
          run={latestPreviewRun}
          loading={runsLoading || (runsLoadedAt === null && runsError === null)}
          failed={runsError !== null}
          onRetry={refreshPreview}
        />

        {isComplete && (
          <section
            id="completion"
            className="onboarding-completion"
            role="status"
            aria-live="polite"
            aria-labelledby="onboarding-completion-title"
            data-testid="onboarding-completion"
          >
            <p className="onboarding-completion__eyebrow review__eyebrow">
              {t('Onboarding.completion_eyebrow')}
            </p>
            <h2
              id="onboarding-completion-title"
              className="onboarding-completion__title"
            >
              {t('Onboarding.complete_title')}
            </h2>
            <p className="onboarding-completion__desc">
              {t('Onboarding.complete_desc')}
            </p>
            <a
              href="#/"
              className="onboarding-completion__cta"
              data-testid="onboarding-cta-complete"
            >
              <Sparkles size={14} aria-hidden="true" />
              {t('Onboarding.complete_cta')}
            </a>
          </section>
        )}
      </div>
      {learnSource && (
        <Suspense fallback={null}>
          <LearnModeDialog open initialSource={learnSource} onClose={() => setLearnSource(null)} />
        </Suspense>
      )}
    </AppShell>
  );
}

/* ------------------------------- Sections ------------------------------- */

function SectionNav({
  t,
  showCompletion,
}: {
  t: TranslateFn;
  showCompletion: boolean;
}) {
  const handleJump = useCallback((sectionId: string) => {
    const target = document.getElementById(sectionId);
    if (!target) return;
    const prefersReduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({
      behavior: prefersReduced ? 'auto' : 'smooth',
      block: 'start',
    });
  }, []);

  const visibleTargets = NAV_TARGETS.filter(
    (target) => target.alwaysVisible || showCompletion,
  );

  return (
    <nav
      className="onboarding-nav"
      aria-label={t('Onboarding.nav_label')}
      data-testid="onboarding-nav"
    >
      <ul className="onboarding-nav__list" role="list">
        {visibleTargets.map((target, index) => {
          const label = t(target.labelKey);
          return (
            <li className="onboarding-nav__item" key={target.id}>
              <button
                type="button"
                className="onboarding-nav__chip"
                data-section={target.id}
                data-testid={`onboarding-nav-chip-${target.id}`}
                aria-label={t('Onboarding.nav_jump_to', { section: label })}
                onClick={(e) => {
                  e.preventDefault();
                  handleJump(target.id);
                }}
              >
                <span className="onboarding-nav__chip-index" aria-hidden="true">
                  0{index + 1}.
                </span>
                {label}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function DiagnosticsSection({
  t,
  doctor,
  dbCheck,
  onRefresh,
}: {
  t: TranslateFn;
  doctor: DoctorState;
  dbCheck: DbCheckState;
  onRefresh: () => void;
}) {
  const isLoading = doctor.loading || dbCheck.loading;

  return (
    <section
      id="diagnostics"
      className="onboarding-diag onboarding-section"
      aria-labelledby="onboarding-diag-title"
      data-testid="onboarding-diagnostics"
    >
      <header className="onboarding-diag__head">
        <div className="onboarding-diag__heading-text">
          <h2 id="onboarding-diag-title" className="onboarding-diag__title">
            <ShieldCheck
              className="onboarding-diag__title-icon"
              aria-hidden="true"
              size={18}
            />
            {t('Onboarding.diagnostics_title')}
          </h2>
          <p className="onboarding-diag__subtitle">
            {t('Onboarding.diagnostics_subtitle')}
          </p>
        </div>
        <button
          type="button"
          className="onboarding-diag__retry"
          onClick={onRefresh}
          disabled={isLoading}
          data-testid="onboarding-diag-retry"
        >
          <RefreshCw size={14} aria-hidden="true" />
          {t('Onboarding.diagnostics_retry')}
        </button>
      </header>
      <div className="onboarding-diag__grid">
        <article
          className="surface-card onboarding-diag__card"
          data-testid="onboarding-doctor-card"
        >
          <header className="surface-card__header">
            <h3 className="onboarding-diag__card-title">
              <ListChecks size={14} aria-hidden="true" />
              {t('Settings_page.section_doctor')}
            </h3>
          </header>
          <div className="surface-card__body">
            {doctor.loading ? (
              <Skeleton variant="card" height="100px" />
            ) : doctor.checks.length > 0 ? (
              doctor.checks.map((check) => (
                <DiagnosticRow
                  key={check.name}
                  status={check.status as DiagnosticStatus}
                  text={mapDoctorMessage(check, t)}
                  remedy={
                    isProviderOnlySensitiveCheck(check)
                      ? t('Doctor.config_sensitive_remedy')
                      : undefined
                  }
                  data-testid="onboarding-doctor-row"
                />
              ))
            ) : (
              <p className="onboarding-diag__empty">
                {t('Onboarding.diagnostics_empty')}
              </p>
            )}
          </div>
        </article>
        <article
          className="surface-card onboarding-diag__card"
          data-testid="onboarding-db-card"
        >
          <header className="surface-card__header">
            <h3 className="onboarding-diag__card-title">
              <ShieldCheck size={14} aria-hidden="true" />
              {t('Doctor.db_title')}
            </h3>
          </header>
          <div className="surface-card__body">
            {dbCheck.loading ? (
              <Skeleton variant="card" height="80px" />
            ) : dbCheck.result ? (
              <>
                <DiagnosticRow
                  status={dbCheck.result.healthy ? 'pass' : 'fail'}
                  text={
                    dbCheck.result.healthy
                      ? t('Doctor.db_healthy')
                      : t('Doctor.db_unhealthy')
                  }
                  data-testid="onboarding-db-row-health"
                />
                <DiagnosticRow
                  status="info"
                  text={`${t('Doctor.db_schema', {
                    version: String(dbCheck.result.schema_version),
                  })} · ${dbCheck.result.quick_check}`}
                  data-testid="onboarding-db-row-schema"
                />
                <DiagnosticRow
                  status="info"
                  text={`${t('Doctor.db_events', {
                    count: String(dbCheck.result.event_count),
                  })} · ${t('Doctor.db_cards', {
                    count: String(dbCheck.result.card_count),
                  })}`}
                  data-testid="onboarding-db-row-counts"
                />
              </>
            ) : (
              <p className="onboarding-diag__empty">{t('Onboarding.db_check_unavailable')}</p>
            )}
          </div>
        </article>
      </div>
    </section>
  );
}

function PreviewSection({ t, run, loading, failed, onRetry }: {
  t: TranslateFn;
  run: RunSummary | null;
  loading: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  const { locale } = useTranslation();
  const verdict = run ? safeVerdict(run.verdict) : null;
  const runPath = run ? `#/run/${encodeURIComponent(run.run_id)}` : null;
  const sourceKey: MessageKey = run?.source_kind === 'document' ? 'LearnDialog.source_document' : run?.source_kind === 'file_compare'
    ? 'LearnDialog.source_files'
    : run?.source_kind.startsWith('git_')
      ? 'LearnDialog.source_git'
      : 'LearnDialog.source_patch';
  const score = run && Number.isFinite(run.overall)
    ? new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(run.overall)
    : '—';
  const metaKey: MessageKey = loading
    ? 'Onboarding.preview_loading_meta'
    : failed
      ? run ? 'Onboarding.preview_stale_meta' : 'Onboarding.preview_error_meta'
      : run ? 'Onboarding.step4_preview_meta_live' : 'Onboarding.preview_empty_meta';
  return (
    <section
      id="preview"
      className="onboarding-preview onboarding-section"
      aria-labelledby="onboarding-preview-title"
      data-testid="onboarding-preview"
      aria-busy={loading}
    >
      <header className="onboarding-preview__head">
        <h2 id="onboarding-preview-title" className="onboarding-preview__title">
          <BookOpen className="onboarding-preview__title-icon" aria-hidden="true" size={18} />
          {t(loading || failed ? 'Onboarding.preview_unconfirmed_title' : 'Onboarding.step4_preview_title')}
        </h2>
        <span className="onboarding-preview__meta">
          {t(metaKey)}
        </span>
        <button
          type="button"
          className="onboarding__btn onboarding__btn--ghost"
          onClick={onRetry}
          disabled={loading}
          aria-busy={loading}
          data-testid="onboarding-preview-refresh"
        >
          <RefreshCw size={12} aria-hidden="true" />
          {t(failed ? 'Onboarding.preview_retry' : 'Onboarding.preview_refresh')}
        </button>
      </header>
      {loading && <p className="onboarding__step-desc" role="status">{t('Onboarding.preview_loading')}</p>}
      {failed && !loading && (
        <p className="onboarding__step-desc" role="alert">
          {t(run ? 'Onboarding.preview_refresh_failed' : 'Onboarding.preview_load_failed')}
        </p>
      )}
      {run && verdict && runPath ? (
        <div className="onboarding-preview__grid">
          <article className="surface-card onboarding-preview__card" data-testid="onboarding-preview-source">
            <header className="surface-card__header"><h3 className="onboarding-preview__card-title">{t('Onboarding.preview_source')}</h3></header>
            <div className="surface-card__body">
              <p className="onboarding__preview-text">{t(sourceKey)}</p>
              <p className="onboarding__preview-text mono">{run.run_id}</p>
            </div>
          </article>
          <article className="surface-card onboarding-preview__card" data-testid="onboarding-preview-diff">
            <header className="surface-card__header"><h3 className="onboarding-preview__card-title">{t('Onboarding.preview_learning')}</h3></header>
            <div className="surface-card__body">
              <p className="onboarding__preview-text">{t('Onboarding.preview_open_hint')}</p>
              <a className="onboarding__btn onboarding__btn--ghost" href={runPath}>{t('Onboarding.preview_open_run')}</a>
            </div>
          </article>
          <article className="surface-card onboarding-preview__card" data-testid="onboarding-preview-verdict">
            <header className="surface-card__header"><h3 className="onboarding-preview__card-title">{t('Onboarding.preview_verdict_label')}</h3></header>
            <div className="surface-card__body">
              <span className={`verdict-badge verdict-badge--${verdict}`} data-testid="onboarding-preview-verdict-badge">
                {t(`Verdict.${verdict}`)} · {score}
              </span>
              <p className="onboarding__preview-text">{t('Onboarding.preview_quality_hint')}</p>
            </div>
          </article>
        </div>
      ) : !loading && !failed && <p className="onboarding__step-desc">{t('Onboarding.preview_empty')}</p>}
    </section>
  );
}

/* ----------------------------- Step bodies ----------------------------- */

function Step1PickRepo({
  installCmd,
  initCmd,
  t,
}: {
  installCmd: string;
  initCmd: string;
  t: TranslateFn;
}) {
  return (
    <>
      <p className="onboarding__step-desc">{t('Onboarding.pick_repo_hint')}</p>
      <div className="onboarding-command-pair">
        <CommandBlock
          command={installCmd}
          copyLabel={t('Onboarding.copy')}
          copiedLabel={t('Onboarding.copied')}
        />
        <CommandBlock
          command={initCmd}
          copyLabel={t('Onboarding.copy')}
          copiedLabel={t('Onboarding.copied')}
        />
      </div>
    </>
  );
}

function Step2ProviderKey({
  envCmd,
  t,
}: {
  envCmd: string;
  t: TranslateFn;
}) {
  return (
    <>
      <p className="onboarding__step-desc">{t('Onboarding.configure_hint')}</p>
      <CommandBlock
        command={envCmd}
        copyLabel={t('Onboarding.copy')}
        copiedLabel={t('Onboarding.copied')}
      />
      <a
        href="#/settings?tab=provider"
        className="onboarding__btn onboarding__btn--primary onboarding__deep-link"
      >
        {t('Onboarding.configure_link')}
      </a>
    </>
  );
}

function Step3InstallAgent({ t }: { t: TranslateFn }) {
  return (
    <>
      <p className="onboarding__step-desc">{t('Onboarding.agent_install_hint')}</p>
      <div className="onboarding-agent-grid">
        {['claude', 'cursor', 'codex'].map((name) => (
          <div className="onboarding-agent-card" key={name}>
            <span className="onboarding-agent-card__mark">{name.slice(0, 2).toUpperCase()}</span>
            <span className="onboarding-agent-card__name">{name}</span>
            <CommandBlock
              command={`ahadiff install ${name} --dry-run`}
              copyLabel={t('Onboarding.copy')}
              copiedLabel={t('Onboarding.copied')}
            />
          </div>
        ))}
      </div>
      <a
        href="#/settings?tab=integrations"
        className="onboarding__btn onboarding__btn--primary onboarding__deep-link"
      >
        {t('Onboarding.agent_install_link')}
      </a>
    </>
  );
}

function Step4Learn({
  onSelectSource,
  t,
  loading,
  isComplete,
  hasChecks,
}: {
  onSelectSource: (source: LearnSource) => void;
  t: TranslateFn;
  loading: boolean;
  isComplete: boolean;
  hasChecks: boolean;
}) {
  return (
    <>
      <p className="onboarding__step-desc">{t('Onboarding.learn_desc')}</p>
      <LearnSourcePicker onSelect={onSelectSource} />
      <p className="onboarding__step-desc">{t('Onboarding.learn_steps')}</p>
      {loading && <Skeleton variant="card" height="60px" />}
      {!loading && isComplete && hasChecks && (
        <div className="onboarding__step-ready" role="status" aria-live="polite">
          <CheckCircle2
            className="onboarding__step-ready-icon"
            aria-hidden="true"
            size={14}
          />
          <span>{t('Onboarding.complete_desc')}</span>
        </div>
      )}
    </>
  );
}
