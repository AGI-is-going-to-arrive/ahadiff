import { useEffect, useState, useRef } from 'react';
import { useLearnStore } from '../state/learn-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { formatBytes, formatCompactNumber } from '../utils/format';
import { safeVerdict } from '../utils/verdict';
import './LearnTaskBanner.css';

const LLM_STEPS = new Set([5, 6, 7, 8]);
/** Show "running longer than usual" hint after this many seconds. */
const LONG_RUNNING_THRESHOLD_S = 300;

function useElapsed(startIso: string | undefined | null): number {
  const [elapsed, setElapsed] = useState(0);
  const rafRef = useRef(0);
  const startRef = useRef(0);

  useEffect(() => {
    if (!startIso) { setElapsed(0); return; }
    const t0 = new Date(startIso).getTime();
    if (Number.isNaN(t0)) { setElapsed(0); return; }
    startRef.current = t0;

    const tick = () => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [startIso]);

  return elapsed;
}

function formatElapsed(s: number): string {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}:${String(sec).padStart(2, '0')}` : `${sec}s`;
}

export default function LearnTaskBanner() {
  const { t, locale } = useTranslation();
  const phase = useLearnStore((s) => s.phase);
  const task = useLearnStore((s) => s.task);
  const estimate = useLearnStore((s) => s.estimate);
  const error = useLearnStore((s) => s.error);
  const errorCode = useLearnStore((s) => s.errorCode);
  const cancelLearn = useLearnStore((s) => s.cancelLearn);
  const confirmLearn = useLearnStore((s) => s.confirmLearn);
  const dismiss = useLearnStore((s) => s.dismiss);
  const retryLearn = useLearnStore((s) => s.retryLearn);
  const retryable = useLearnStore((s) => s.retryable);
  const recoverExistingTask = useLearnStore((s) => s.recoverExistingTask);

  useEffect(() => {
    void recoverExistingTask();
  }, [recoverExistingTask]);

  const progress = task?.progress;
  const stepStartedAt = progress?.step_started_at || null;
  const elapsed = useElapsed(
    phase === 'running' || phase === 'cancelling' ? stepStartedAt : null,
  );
  // Total task elapsed (since the backend marked the task as started).
  // Falls back to `created_at` for pending tasks so the banner has a clock
  // even before the worker picks it up. Used for the "long running" hint
  // and for computing remaining time against `deadline_at`.
  const taskStartedAt = task?.started_at || task?.created_at || null;
  const totalElapsed = useElapsed(
    phase === 'running' || phase === 'cancelling' ? taskStartedAt : null,
  );

  if (phase === 'idle') return null;

  const isPending = task?.status === 'pending';
  const pct = progress && progress.total > 0
    ? Math.max(0, Math.min(100, Math.round((progress.current / progress.total) * 100)))
    : 0;
  const resultSummary = task?.result_summary;
  const isTooManyTasks = errorCode === 'too_many_tasks';
  const isRateLimited = errorCode === 'rate_limited';
  const isPollConnectionLost = errorCode === 'poll_connection_lost' || errorCode === 'poll_server_error';
  const recoveryHint = task?.recovery_hint ?? null;
  const canRetry = retryable && (recoveryHint === null || recoveryHint === 'retry');
  const rateLimitSeconds = isRateLimited && error?.startsWith('rate_limited:')
    ? error.split(':')[1] ?? '60'
    : '60';
  const isLlmStep = progress ? LLM_STEPS.has(progress.current) : false;
  const isLongRunning =
    (phase === 'running' || phase === 'cancelling')
    && !isPending
    && totalElapsed >= LONG_RUNNING_THRESHOLD_S;
  // Compute remaining seconds from backend `deadline_at` when available.
  // Use `Date.parse` (cross-browser; both Chrome/Firefox/WebKit/Node parse
  // ISO 8601). Hide if deadline has passed or parsing fails.
  let remainingSeconds: number | null = null;
  if (task?.deadline_at && (phase === 'running' || phase === 'cancelling')) {
    const deadlineMs = Date.parse(task.deadline_at);
    if (Number.isFinite(deadlineMs)) {
      const remaining = Math.floor((deadlineMs - Date.now()) / 1000);
      if (remaining > 0) remainingSeconds = remaining;
    }
  }

  return (
    <div
      className={`learn-banner learn-banner--${phase}`}
      role="status"
      aria-live="polite"
    >
      {/* ---- Estimating ---- */}
      {phase === 'estimating' && (
        <div className="learn-banner__body">
          <span className="learn-banner__spinner" aria-hidden="true" />
          <span>{t('Learn.estimating')}</span>
        </div>
      )}

      {/* ---- Confirming (preflight warning) ---- */}
      {phase === 'confirming' && estimate && (
        <div className="learn-banner__body learn-banner__confirm">
          <div className="learn-banner__confirm-header">
            <span className={`learn-banner__risk learn-banner__risk--${estimate.risk_level}`}>
              {estimate.risk_level === 'danger' ? '⚠' : '△'}
            </span>
            <strong>{t('Learn.preflight_title')}</strong>
          </div>
          <div className="learn-banner__confirm-stats">
            <span>{t('Learn.preflight_files', { count: estimate.file_count })}</span>
            <span>{t('Learn.preflight_size', { size: formatBytes(estimate.patch_bytes, locale) })}</span>
            <span>{t('Learn.preflight_tokens', {
              estimated: formatCompactNumber(estimate.estimated_tokens, locale),
              limit: formatCompactNumber(estimate.provider_context_window, locale),
            })}</span>
          </div>
          {estimate.warnings.length > 0 && (
            <ul className="learn-banner__confirm-warnings">
              {estimate.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
          <div className="learn-banner__confirm-actions">
            <button type="button" className="learn-banner__btn learn-banner__btn--primary" onClick={() => void confirmLearn()}>
              {t('Learn.preflight_continue')}
            </button>
            <button type="button" className="learn-banner__btn" onClick={dismiss}>
              {t('Learn.preflight_cancel')}
            </button>
          </div>
        </div>
      )}

      {/* ---- Submitting ---- */}
      {phase === 'submitting' && (
        <div className="learn-banner__body">
          <span className="learn-banner__spinner" aria-hidden="true" />
          <span>{t('Learn.submitting')}</span>
        </div>
      )}

      {/* ---- Running / Cancelling ---- */}
      {(phase === 'running' || phase === 'cancelling') && (
        <>
          <div className="learn-banner__body">
            <div className="learn-banner__info">
              {isLlmStep && (
                <span className="learn-banner__pulse" aria-hidden="true" />
              )}
              <span className="learn-banner__step">
                {isPending
                  ? t('Learn.pending')
                  : progress
                    ? t('Learn.step_progress', {
                        current: progress.current,
                        total: progress.total,
                      })
                    : t('Learn.running')}
              </span>
              {progress?.message && (
                <span className="learn-banner__msg">{progress.message}</span>
              )}
              {!isPending && elapsed > 0 && (
                <span className="learn-banner__elapsed" aria-hidden="true">
                  {formatElapsed(elapsed)}
                </span>
              )}
              {!isPending && totalElapsed > 0 && (
                <span className="learn-banner__total-elapsed">
                  {t('Learn.elapsed_time')}: {formatElapsed(totalElapsed)}
                  {remainingSeconds !== null && (
                    <> · {t('Learn.remaining_time', { time: formatElapsed(remainingSeconds) })}</>
                  )}
                </span>
              )}
            </div>
            {isLlmStep && !isPending && (
              <div className="learn-banner__hint">
                {t(`Learn.step_hint_${progress!.current}` as MessageKey)}
              </div>
            )}
            {isLongRunning && (
              <div className="learn-banner__hint learn-banner__hint--long-running">
                {t('Learn.long_running_hint')}
              </div>
            )}
            {!isPending && (
              <div
                className={`learn-banner__bar-track${isLlmStep ? ' learn-banner__bar-track--active' : ''}`}
                role="progressbar"
                aria-valuenow={pct}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={progress
                  ? t('Learn.step_progress', { current: progress.current, total: progress.total })
                  : t('Learn.running')}
              >
                <div
                  className="learn-banner__bar-fill"
                  style={{ width: `${pct}%` }}
                />
              </div>
            )}
          </div>
          <div className="learn-banner__actions">
            <button
              type="button"
              className="learn-banner__btn learn-banner__btn--cancel"
              onClick={() => void cancelLearn()}
              disabled={phase === 'cancelling'}
            >
              {phase === 'cancelling' ? t('Learn.cancelling') : t('Learn.cancel')}
            </button>
            {phase === 'cancelling' && (
              <button
                type="button"
                className="learn-banner__btn learn-banner__btn--dismiss"
                onClick={dismiss}
              >
                {t('Learn.dismiss')}
              </button>
            )}
          </div>
        </>
      )}

      {/* ---- Completed ---- */}
      {(phase === 'completed' || phase === 'cancelled') && (
        <>
          <div className="learn-banner__body">
            <span className="learn-banner__icon" aria-hidden="true">
              {phase === 'cancelled' ? '⊘' : '✓'}
            </span>
            <div className="learn-banner__info">
              <span className="learn-banner__step">
                {phase === 'cancelled'
                  ? t('Learn.cancelled')
                  : t('Learn.completed')}
              </span>
              {resultSummary && resultSummary.run_id && (
                <span className="learn-banner__result">
                  {resultSummary.verdict && (() => {
                    const v = safeVerdict(resultSummary.verdict);
                    return (
                      <span className={`verdict-badge verdict-badge--${v}`}>
                        {t(`Verdict.${v}` as MessageKey)}
                      </span>
                    );
                  })()}
                  {resultSummary.overall != null && (
                    <span className="learn-banner__score">
                      {t('Learn.score', { score: resultSummary.overall })}
                    </span>
                  )}
                </span>
              )}
            </div>
          </div>
          <div className="learn-banner__actions">
            {phase === 'completed' && resultSummary?.run_id && (
              <a
                className="learn-banner__btn learn-banner__btn--view"
                href={`#/run/${resultSummary.run_id}/lesson`}
              >
                {t('Learn.view_run')}
              </a>
            )}
            <button
              type="button"
              className="learn-banner__btn learn-banner__btn--dismiss"
              onClick={dismiss}
            >
              {t('Learn.dismiss')}
            </button>
          </div>
        </>
      )}

      {/* ---- Failed ---- */}
      {phase === 'failed' && (
        <>
          <div className="learn-banner__body">
            <span className={`learn-banner__icon${isTooManyTasks || isRateLimited || isPollConnectionLost ? '' : ' learn-banner__icon--error'}`} aria-hidden="true">
              {isTooManyTasks || isRateLimited ? '⏳' : isPollConnectionLost ? '⚠' : '✕'}
            </span>
            <div className="learn-banner__info">
              <span className="learn-banner__step">
                {isTooManyTasks
                  ? t('Learn.too_many_tasks')
                  : isRateLimited
                    ? t('Learn.rate_limited', { seconds: rateLimitSeconds })
                    : isPollConnectionLost
                      ? t('Learn.poll_connection_lost')
                      : t('Learn.failed')}
              </span>
              {errorCode && !isTooManyTasks && !isRateLimited && !isPollConnectionLost && (
                <code className="learn-banner__error-code">{errorCode}</code>
              )}
              {error && !isTooManyTasks && !isRateLimited && !isPollConnectionLost && (
                <span className="learn-banner__msg">{error}</span>
              )}
            </div>
          </div>
          <div className="learn-banner__actions">
            {canRetry && (
              <button
                type="button"
                className="learn-banner__btn learn-banner__btn--retry"
                onClick={() => void retryLearn()}
              >
                {t('Learn.retry')}
              </button>
            )}
            <button
              type="button"
              className="learn-banner__btn learn-banner__btn--dismiss"
              onClick={dismiss}
            >
              {t('Learn.dismiss')}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
