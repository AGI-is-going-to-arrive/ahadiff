import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import ChallengeStepper from '../components/ChallengeStepper';
import { ApiError } from '../api/client';
import {
  abortChallenge,
  advanceChallenge,
  buildChallenge,
  getChallenge,
  getChallengeFeedback,
  isChallengeFeatureDisabled,
  submitReview,
  type ChallengeEnvelope,
  type ChallengeFeedback,
  type ChallengeManifest,
  type ChallengeStage,
  type ChallengeState,
} from '../api/challenge';
import { listRuns } from '../api/runs';
import type { RunSummary } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import '../styles/challenge.css';

const RUN_PAGE_SIZE = 25;

interface PageState {
  envelope: ChallengeEnvelope | null;
  feedback: ChallengeFeedback | null;
}

function stageOf(state: ChallengeState | null): ChallengeStage {
  return state?.stage ?? 'idle';
}

function deriveErrorKey(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.errorCode) {
      case 'RUN_NOT_FOUND':
        return 'Challenge.error_run_not_found';
      case 'CHALLENGE_RUN_NOT_QUALIFYING':
      case 'NOT_QUALIFYING':
        return 'Challenge.error_not_qualifying';
      case 'INVALID_TRANSITION':
      case 'CHALLENGE_INVALID_TRANSITION':
        return 'Challenge.error_invalid_transition';
      default:
        return 'Error.fetch_failed';
    }
  }
  return 'Error.fetch_failed';
}

export default function ChallengePage() {
  const { t } = useTranslation();
  const { challengeId: routeChallengeId } = useParams<{ challengeId?: string }>();

  const [featureUnavailable, setFeatureUnavailable] = useState(false);
  const [page, setPage] = useState<PageState>({ envelope: null, feedback: null });
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>('');
  const [learnerDiff, setLearnerDiff] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [initializing, setInitializing] = useState(true);
  const [statusKey, setStatusKey] = useState<string | null>(null);
  const [abortDialogOpen, setAbortDialogOpen] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const abortCancelRef = useRef<HTMLButtonElement | null>(null);
  const abortDialogRef = useRef<HTMLDivElement | null>(null);

  const state = page.envelope?.state ?? null;
  const manifest: ChallengeManifest | null = page.envelope?.manifest ?? null;
  const stage = stageOf(state);

  const replaceController = useCallback(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    return controller;
  }, []);

  const handleApiError = useCallback((err: unknown) => {
    if (err instanceof DOMException && err.name === 'AbortError') return false;
    if (isChallengeFeatureDisabled(err)) {
      setFeatureUnavailable(true);
      return true;
    }
    setErrorKey(deriveErrorKey(err));
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('[ChallengePage]', err);
    }
    return true;
  }, []);

  /**
   * Load a deep-linked challenge when `/#/challenge/:id` is present; otherwise
   * load recent runs for a new challenge. The 501 FEATURE_UNAVAILABLE check
   * happens lazily when the challenge API is touched.
   */
  useEffect(() => {
    const controller = replaceController();
    setInitializing(true);
    setErrorKey(null);
    const loadInitial = async () => {
      if (routeChallengeId) {
        const envelope = await getChallenge(routeChallengeId, { signal: controller.signal });
        const feedbackEnvelope = await getChallengeFeedback(routeChallengeId, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setPage({ envelope, feedback: feedbackEnvelope.feedback });
        setSelectedRunId(envelope.state.source_run_id);
        setStatusKey('Challenge.status_loaded');
        return;
      }
      const res = await listRuns({ page_size: RUN_PAGE_SIZE }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setRuns(res.runs);
      if (res.runs.length > 0) setSelectedRunId(res.runs[0].run_id);
    };
    loadInitial()
      .catch((err: unknown) => {
        handleApiError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setInitializing(false);
      });
    return () => controller.abort();
  }, [handleApiError, replaceController, routeChallengeId]);

  useEffect(() => {
    if (!abortDialogOpen) return undefined;
    const previousActive = document.activeElement;
    abortCancelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAbortDialogOpen(false);
      if (event.key !== 'Tab') return;
      const focusable = Array.from(
        abortDialogRef.current?.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((node) => !node.hasAttribute('disabled'));
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      if (previousActive instanceof HTMLElement) previousActive.focus();
    };
  }, [abortDialogOpen]);

  const onSelectRun = useCallback((event: ChangeEvent<HTMLSelectElement>) => {
    setSelectedRunId(event.target.value);
  }, []);

  const onLearnerDiffChange = useCallback(
    (event: ChangeEvent<HTMLTextAreaElement>) => {
      setLearnerDiff(event.target.value);
    },
    [],
  );

  const onBuild = useCallback(async () => {
    if (!selectedRunId) return;
    setBusy(true);
    setErrorKey(null);
    try {
      const envelope = await buildChallenge(selectedRunId);
      setPage({ envelope, feedback: null });
      setLearnerDiff('');
      setStatusKey('Challenge.status_built');
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  }, [handleApiError, selectedRunId]);

  const onAdvance = useCallback(
    async (target?: ChallengeStage) => {
      if (!state) return;
      setBusy(true);
      setErrorKey(null);
      try {
        const next = await advanceChallenge(state.challenge_id, target);
        // After advance, re-fetch the full envelope so manifest stays in sync.
        const full = await getChallenge(state.challenge_id);
        setPage((prev) => ({
          ...prev,
          envelope: full ?? { state: next.state, manifest: prev.envelope?.manifest ?? null },
        }));
        setStatusKey('Challenge.status_advanced');
      } catch (err) {
        handleApiError(err);
      } finally {
        setBusy(false);
      }
    },
    [handleApiError, state],
  );

  const onSubmitReview = useCallback(async () => {
    if (!state) return;
    if (learnerDiff.trim().length === 0) return;
    setBusy(true);
    setErrorKey(null);
    try {
      // Capture feedback FIRST. The backend transitions CHALLENGE → REVIEW →
      // ADAPT → IDLE inside this single call, so a subsequent getChallenge()
      // would show an idle envelope and erase the results panel if we let it
      // overwrite the feedback. Persist feedback eagerly, then refresh the
      // envelope without dropping it.
      const feedback = await submitReview(state.challenge_id, learnerDiff);
      let envelope: ChallengeEnvelope | null = page.envelope;
      try {
        envelope = await getChallenge(state.challenge_id);
      } catch (refreshErr) {
        if (import.meta.env.DEV) {
          // eslint-disable-next-line no-console
          console.warn('[ChallengePage] envelope refresh failed', refreshErr);
        }
      }
      setPage({ envelope, feedback });
      setStatusKey('Challenge.status_reviewed');
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  }, [handleApiError, learnerDiff, page.envelope, state]);

  const onLoadFeedback = useCallback(async () => {
    if (!state) return;
    try {
      const envelope = await getChallengeFeedback(state.challenge_id);
      if (envelope.feedback) {
        setPage((prev) => ({ ...prev, feedback: envelope.feedback }));
      }
    } catch (err) {
      handleApiError(err);
    }
  }, [handleApiError, state]);

  useEffect(() => {
    // When we enter review/adapt and feedback hasn't been loaded yet, fetch it
    // so the user can see results even if they reloaded mid-session. The idle
    // case is intentionally excluded: idle without feedback is the build screen,
    // while idle WITH feedback (post-submit) is rendered via the results panel.
    if (!state) return;
    if (page.feedback) return;
    if (stage === 'review' || stage === 'adapt') {
      void onLoadFeedback();
    }
  }, [onLoadFeedback, page.feedback, stage, state]);

  const onConfirmAbort = useCallback(async () => {
    if (!state) return;
    setAbortDialogOpen(false);
    setBusy(true);
    setErrorKey(null);
    try {
      await abortChallenge(state.challenge_id);
      setPage({ envelope: null, feedback: null });
      setLearnerDiff('');
      setStatusKey('Challenge.status_aborted');
    } catch (err) {
      handleApiError(err);
    } finally {
      setBusy(false);
    }
  }, [handleApiError, state]);

  const onComplete = useCallback(() => {
    setPage({ envelope: null, feedback: null });
    setLearnerDiff('');
  }, []);

  const feedback = page.feedback;
  const missingFiles = feedback?.missing_files ?? [];
  const extraFiles = feedback?.extra_files ?? [];
  const hunkCoverage = feedback?.hunk_coverage ?? [];
  const gapClaimIds = feedback?.gap_claim_ids ?? [];
  const allClaimIds = feedback?.all_canonical_claim_ids ?? [];
  const adaptSummary = feedback?.adapt ?? null;
  const totalCanonicalHunks = hunkCoverage.reduce(
    (sum, row) => sum + row.canonical_hunks,
    0,
  );
  const matchedHunks = hunkCoverage.reduce(
    (sum, row) => sum + row.matched_hunks,
    0,
  );
  const perfectCoverage =
    feedback !== null &&
    missingFiles.length === 0 &&
    gapClaimIds.length === 0 &&
    (totalCanonicalHunks === 0 || matchedHunks === totalCanonicalHunks);
  const showResults = feedback !== null;

  const metaRow = useMemo(() => {
    if (!state) return null;
    const displayStage =
      stage === 'idle' ? (showResults ? 'adapt' : 'build') : stage;
    return (
      <div className="challenge-panel__meta">
        <span>
          <strong>{t('Challenge.source_run')}:</strong>
          {state.source_run_id}
        </span>
        <span>
          <strong>{t('Challenge.current_stage')}:</strong>
          {t(`Challenge.stage_${displayStage}`)}
        </span>
      </div>
    );
  }, [showResults, stage, state, t]);

  if (featureUnavailable) {
    return (
      <AppShell>
        <section className="challenge-page" aria-labelledby="challenge-page-title">
          <header className="challenge-page__header">
            <h1 className="challenge-page__title" id="challenge-page-title">
              {t('Challenge.title')}
            </h1>
          </header>
          <p className="challenge-page__notice">{t('Challenge.not_enabled')}</p>
        </section>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <section className="challenge-page" aria-labelledby="challenge-page-title">
        <header className="challenge-page__header">
          <h1 className="challenge-page__title" id="challenge-page-title">
            {t('Challenge.title')}
          </h1>
        </header>

        <ChallengeStepper current={stage === 'idle' ? (showResults ? 'adapt' : 'build') : stage} />

        <div className="challenge-page__sr-only" role="status" aria-live="polite">
          {statusKey ? t(statusKey) : ''}
        </div>

        {errorKey ? (
          <div className="challenge-page__error" role="alert">
            {t(errorKey)}
          </div>
        ) : null}

        {metaRow}

        {stage === 'idle' && !showResults ? (
          <div className="challenge-panel">
            <h2 className="challenge-panel__heading">{t('Challenge.stage_build')}</h2>
            <p className="challenge-panel__hint">{t('Challenge.build_prompt')}</p>
            <label className="challenge-panel__hint" htmlFor="challenge-run-select">
              {t('Challenge.select_run')}
            </label>
            <select
              id="challenge-run-select"
              className="challenge-panel__select"
              value={selectedRunId}
              onChange={onSelectRun}
              disabled={initializing || runs.length === 0 || busy}
            >
              {runs.length === 0 ? (
                <option value="">—</option>
              ) : null}
              {runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {run.source_ref || run.run_id}
                </option>
              ))}
            </select>
            <div className="challenge-panel__actions">
              <button
                type="button"
                className="challenge-button"
                onClick={onBuild}
                disabled={!selectedRunId || busy}
              >
                {t('Challenge.build_button')}
              </button>
            </div>
          </div>
        ) : null}

        {stage === 'build' ? (
          <div className="challenge-panel">
            <h2 className="challenge-panel__heading">{t('Challenge.stage_build')}</h2>
            <p className="challenge-panel__hint">{t('Challenge.build_prompt')}</p>
            <div className="challenge-panel__actions">
              <button
                type="button"
                className="challenge-button"
                onClick={() => void onAdvance('tour')}
                disabled={busy}
              >
                {t('Challenge.tour_ready')}
              </button>
            </div>
          </div>
        ) : null}

        {stage === 'tour' ? (
          <div className="challenge-panel">
            <h2 className="challenge-panel__heading">{t('Challenge.tour_header')}</h2>
            <p className="challenge-panel__hint">{t('Challenge.canonical_diff')}</p>
            <pre
              className="challenge-panel__diff"
              tabIndex={0}
              aria-label={t('Challenge.canonical_diff')}
            >
              {manifest?.canonical_patch ?? ''}
            </pre>
            <div className="challenge-panel__actions">
              <button
                type="button"
                className="challenge-button"
                onClick={() => void onAdvance('challenge')}
                disabled={busy}
              >
                {t('Challenge.tour_ready')}
              </button>
            </div>
          </div>
        ) : null}

        {stage === 'challenge' ? (
          <div className="challenge-panel">
            <h2 className="challenge-panel__heading">{t('Challenge.challenge_header')}</h2>
            <label className="challenge-panel__hint" htmlFor="challenge-learner-diff">
              {t('Challenge.learner_diff')}
            </label>
            <textarea
              id="challenge-learner-diff"
              className="challenge-panel__textarea"
              value={learnerDiff}
              onChange={onLearnerDiffChange}
              placeholder={t('Challenge.challenge_placeholder')}
              spellCheck={false}
              disabled={busy}
            />
            <div className="challenge-panel__actions">
              <button
                type="button"
                className="challenge-button"
                onClick={() => void onSubmitReview()}
                disabled={busy || learnerDiff.trim().length === 0}
              >
                {t('Challenge.challenge_submit')}
              </button>
            </div>
          </div>
        ) : null}

        {showResults && feedback ? (
          <div className="challenge-panel challenge-panel--results">
            <h2 className="challenge-panel__heading">
              {t('Challenge.feedback_results_header')}
            </h2>

            {perfectCoverage ? (
              <p className="challenge-panel__hint">{t('Challenge.perfect_coverage')}</p>
            ) : null}

            {hunkCoverage.length > 0 ? (
              <section className="challenge-panel__section">
                <h3 className="challenge-panel__subheading">
                  {t('Challenge.hunk_coverage_header')}
                </h3>
                <ul className="challenge-panel__list">
                  {hunkCoverage.map((row) => (
                    <li key={row.path}>
                      <code className="challenge-panel__path">{row.path}</code>{' '}
                      {t('Challenge.hunk_coverage_row', {
                        matched: row.matched_hunks,
                        total: row.canonical_hunks,
                        missing: row.missing_hunks,
                      })}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {missingFiles.length > 0 ? (
              <section className="challenge-panel__section">
                <h3 className="challenge-panel__subheading">
                  {t('Challenge.missing_files_header')}
                </h3>
                <ul className="challenge-panel__list">
                  {missingFiles.map((path) => (
                    <li key={`missing-${path}`}>
                      <code className="challenge-panel__path">{path}</code>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {extraFiles.length > 0 ? (
              <section className="challenge-panel__section">
                <h3 className="challenge-panel__subheading">
                  {t('Challenge.extra_files_header')}
                </h3>
                <ul className="challenge-panel__list">
                  {extraFiles.map((path) => (
                    <li key={`extra-${path}`}>
                      <code className="challenge-panel__path">{path}</code>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {allClaimIds.length > 0 ? (
              <section className="challenge-panel__section">
                <h3 className="challenge-panel__subheading">
                  {t('Challenge.gap_claims_header')}
                </h3>
                <p className="challenge-panel__hint">
                  {t('Challenge.gap_claims_summary', {
                    matched: allClaimIds.length - gapClaimIds.length,
                    total: allClaimIds.length,
                  })}
                </p>
                {gapClaimIds.length > 0 ? (
                  <ul className="challenge-panel__list">
                    {gapClaimIds.map((cid) => (
                      <li key={`gap-${cid}`}>
                        <code className="challenge-panel__claim">{cid}</code>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </section>
            ) : null}

            <section className="challenge-panel__section">
              <h3 className="challenge-panel__subheading">
                {t('Challenge.adapt_header')}
              </h3>
              <p className="challenge-panel__hint">
                {adaptSummary && adaptSummary.signal_count > 0
                  ? t('Challenge.adapt_signals_inserted', {
                      count: adaptSummary.signal_count,
                    })
                  : t('Challenge.adapt_signals_none')}
              </p>
            </section>

            <div className="challenge-panel__actions">
              <button
                type="button"
                className="challenge-button"
                onClick={onComplete}
                disabled={busy}
              >
                {t('Challenge.results_dismiss')}
              </button>
            </div>
          </div>
        ) : null}

        {stage !== 'idle' ? (
          <div className="challenge-page__footer">
            <button
              type="button"
              className="challenge-button challenge-button--danger"
              onClick={() => setAbortDialogOpen(true)}
              disabled={busy}
            >
              {t('Challenge.abort')}
            </button>
          </div>
        ) : null}

        {abortDialogOpen ? (
          <div className="challenge-dialog-backdrop" role="presentation">
            <div
              ref={abortDialogRef}
              className="challenge-dialog"
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="challenge-abort-title"
              aria-describedby="challenge-abort-desc"
            >
              <h2 id="challenge-abort-title">{t('Challenge.abort')}</h2>
              <p id="challenge-abort-desc">{t('Challenge.abort_confirm')}</p>
              <div className="challenge-dialog__actions">
                <button
                  ref={abortCancelRef}
                  type="button"
                  className="challenge-button"
                  onClick={() => setAbortDialogOpen(false)}
                >
                  {t('Challenge.abort_cancel')}
                </button>
                <button
                  type="button"
                  className="challenge-button challenge-button--danger"
                  onClick={() => void onConfirmAbort()}
                >
                  {t('Challenge.abort')}
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </section>
    </AppShell>
  );
}
