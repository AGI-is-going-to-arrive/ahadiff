import { useLearnStore } from '../state/learn-store';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import { safeVerdict } from '../utils/verdict';
import './LearnTaskBanner.css';

export default function LearnTaskBanner() {
  const { t } = useTranslation();
  const phase = useLearnStore((s) => s.phase);
  const task = useLearnStore((s) => s.task);
  const error = useLearnStore((s) => s.error);
  const errorCode = useLearnStore((s) => s.errorCode);
  const cancelLearn = useLearnStore((s) => s.cancelLearn);
  const dismiss = useLearnStore((s) => s.dismiss);
  const submitLearn = useLearnStore((s) => s.submitLearn);

  if (phase === 'idle') return null;

  const progress = task?.progress;
  const pct = progress && progress.total > 0
    ? Math.max(0, Math.min(100, Math.round((progress.current / progress.total) * 100)))
    : 0;
  const resultSummary = task?.result_summary;

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
              <span className="learn-banner__step">
                {progress
                  ? t('Learn.step_progress', {
                      current: progress.current,
                      total: progress.total,
                    })
                  : t('Learn.running')}
              </span>
              {progress?.message && (
                <span className="learn-banner__msg">{progress.message}</span>
              )}
            </div>
            <div
              className="learn-banner__bar-track"
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
          </div>
        </>
      )}

      {/* ---- Completed ---- */}
      {phase === 'completed' && (
        <>
          <div className="learn-banner__body">
            <span className="learn-banner__icon" aria-hidden="true">
              {task?.status === 'cancelled' ? '⊘' : '✓'}
            </span>
            <div className="learn-banner__info">
              <span className="learn-banner__step">
                {task?.status === 'cancelled'
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
            {resultSummary?.run_id && (
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
            <span className="learn-banner__icon learn-banner__icon--error" aria-hidden="true">
              ✕
            </span>
            <div className="learn-banner__info">
              <span className="learn-banner__step">{t('Learn.failed')}</span>
              {errorCode && (
                <code className="learn-banner__error-code">{errorCode}</code>
              )}
              {error && <span className="learn-banner__msg">{error}</span>}
            </div>
          </div>
          <div className="learn-banner__actions">
            <button
              type="button"
              className="learn-banner__btn learn-banner__btn--retry"
              onClick={() => void submitLearn()}
            >
              {t('Learn.retry')}
            </button>
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
