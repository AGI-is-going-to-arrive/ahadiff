import { useEffect, useState, useRef } from 'react';
import { useLearnStore } from '../state/learn-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { safeVerdict } from '../utils/verdict';
import './LearnTaskBanner.css';

const LLM_STEPS = new Set([5, 6, 7, 8]);

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
  const { t } = useTranslation();
  const phase = useLearnStore((s) => s.phase);
  const task = useLearnStore((s) => s.task);
  const error = useLearnStore((s) => s.error);
  const errorCode = useLearnStore((s) => s.errorCode);
  const cancelLearn = useLearnStore((s) => s.cancelLearn);
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

  if (phase === 'idle') return null;

  const isPending = task?.status === 'pending';
  const pct = progress && progress.total > 0
    ? Math.max(0, Math.min(100, Math.round((progress.current / progress.total) * 100)))
    : 0;
  const resultSummary = task?.result_summary;
  const isTooManyTasks = errorCode === 'too_many_tasks';
  const isRateLimited = errorCode === 'rate_limited';
  const recoveryHint = task?.recovery_hint ?? null;
  const canRetry = retryable && (recoveryHint === null || recoveryHint === 'retry');
  const rateLimitSeconds = isRateLimited && error?.startsWith('rate_limited:')
    ? error.split(':')[1] ?? '60'
    : '60';
  const isLlmStep = progress ? LLM_STEPS.has(progress.current) : false;

  return (
    <div
      className={`learn-banner learn-banner--${phase}`}
      role="status"
      aria-live="polite"
    >
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
            </div>
            {isLlmStep && !isPending && (
              <div className="learn-banner__hint">
                {t(`Learn.step_hint_${progress!.current}` as MessageKey)}
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
            <span className={`learn-banner__icon${isTooManyTasks || isRateLimited ? '' : ' learn-banner__icon--error'}`} aria-hidden="true">
              {isTooManyTasks || isRateLimited ? '⏳' : '✕'}
            </span>
            <div className="learn-banner__info">
              <span className="learn-banner__step">
                {isTooManyTasks
                  ? t('Learn.too_many_tasks')
                  : isRateLimited
                    ? t('Learn.rate_limited', { seconds: rateLimitSeconds })
                    : t('Learn.failed')}
              </span>
              {errorCode && !isTooManyTasks && !isRateLimited && (
                <code className="learn-banner__error-code">{errorCode}</code>
              )}
              {error && !isTooManyTasks && !isRateLimited && (
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
