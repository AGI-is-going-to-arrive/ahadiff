import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import SRSCard from '../components/SRSCard';
import type { SrsRating, SrsReviewRating } from '../components/SRSCard';
import { getRunArtifact } from '../api/runs';
import { updateReviewQueueState } from '../api/review';
import { quizAnswer, srsReview } from '../api/signals';
import type { MisconceptionCardItem, ReviewAnswer } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import {
  hasQuizReviewCard,
  parseQuizJsonl,
  type QuizItem,
} from '../utils/quiz-contract';
import '../components/Quiz.css';

interface AnswerRecord {
  answer: string;
  correct: boolean;
  peekAt: number;
}

function parseMisconceptionJsonl(content: string): MisconceptionCardItem[] {
  const items: MisconceptionCardItem[] = [];
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed) as Partial<MisconceptionCardItem>;
      if (
        typeof parsed.card_id === 'string' &&
        typeof parsed.concept === 'string' &&
        typeof parsed.misconception === 'string' &&
        typeof parsed.correction === 'string' &&
        typeof parsed.evidence_ref === 'string' &&
        (parsed.severity === 'low' || parsed.severity === 'medium' || parsed.severity === 'high') &&
        Array.isArray(parsed.safety_tags) &&
        parsed.safety_tags.every((tag) => typeof tag === 'string') &&
        typeof parsed.run_id === 'string'
      ) {
        items.push(parsed as MisconceptionCardItem);
      }
    } catch {
      // skip malformed lines
    }
  }
  return items;
}

function makeStableKey(runId: string, prefix: string, id: string, action: string): string {
  return `${runId}-${prefix}-${id}-${action}`;
}

function isReviewRating(rating: SrsRating): rating is ReviewAnswer {
  return rating === 'easy' || rating === 'good' || rating === 'hard' || rating === 'wrong';
}

const QUIZ_REVIEW_PEEKED_THIS_SESSION = true;
const PEEKED_REVIEW_RATING_BLOCKLIST = new Set<SrsReviewRating>(['easy', 'good']);
const PEEKED_REVIEW_RATING_ERROR = 'peeked cards cannot be reviewed as good or easy; use hard or wrong';

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function formatEvidenceAnchor(file: string, line: number): string {
  return `${file}:L${line}`;
}

export default function QuizPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useTranslation();

  const [quizzes, setQuizzes] = useState<QuizItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answered, setAnswered] = useState<Record<string, AnswerRecord>>({});
  const [misconceptions, setMisconceptions] = useState<MisconceptionCardItem[]>([]);
  const [signalError, setSignalError] = useState<string | null>(null);
  // `rated` gates the Next button. SRS-tracked quiz rows require a rating; legacy
  // no-review rows are marked rated after answer reveal so they do not depend on
  // review.sqlite cards that were never generated.
  const [rated, setRated] = useState<Record<string, boolean>>({});
  const abortRef = useRef<AbortController | null>(null);

  const fetchQuiz = useCallback(() => {
    if (!runId) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);

    Promise.allSettled([
      getRunArtifact(runId, 'quiz', { signal: controller.signal }),
      getRunArtifact(runId, 'misconceptions', { signal: controller.signal }),
    ])
      .then(([quizResult, misconceptionResult]) => {
        if (controller.signal.aborted) return;
        if (quizResult.status !== 'fulfilled') {
          throw quizResult.reason;
        }
        const items = parseQuizJsonl(quizResult.value.content);
        setQuizzes(items);
        setCurrentIndex(0);
        setAnswered({});
        setRated({});
        setSignalError(null);
        if (misconceptionResult.status === 'fulfilled') {
          setMisconceptions(parseMisconceptionJsonl(misconceptionResult.value.content));
        } else {
          setMisconceptions([]);
        }
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        if (controller.signal.aborted) return;
        // Store a stable flag rather than the raw error string; the user-facing
        // copy is rendered via t('Error.fetch_failed', {...}) below.
        setError('fetch_failed');
        // eslint-disable-next-line no-console
        if (import.meta.env.DEV) console.error('[QuizPage] fetch error:', err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
  }, [runId]);

  useEffect(() => {
    fetchQuiz();
    return () => abortRef.current?.abort();
  }, [fetchQuiz]);

  const currentQuiz = useMemo(
    () => (quizzes.length > 0 ? quizzes[currentIndex] ?? null : null),
    [quizzes, currentIndex],
  );

  const handleAnswer = useCallback(
    (questionId: string, answer: string, correct: boolean) => {
      setAnswered((prev) => ({
        ...prev,
        [questionId]: { answer, correct, peekAt: Date.now() },
      }));
      if (
        currentQuiz &&
        currentQuiz.question_id === questionId &&
        !hasQuizReviewCard(currentQuiz)
      ) {
        setRated((prev) => ({ ...prev, [questionId]: true }));
      }
      setSignalError(null);

      if (runId) {
        void quizAnswer({
          idempotency_key: makeStableKey(runId, 'qa', questionId, answer),
          quiz_id: questionId,
          choice: answer,
          correct,
        }).catch((err: unknown) => {
          setSignalError(errorMessage(err));
        });
      }
    },
    [currentQuiz, runId],
  );

  const handleRate = useCallback(
    async (rating: SrsRating): Promise<boolean> => {
      if (!currentQuiz || !runId) return false;
      setSignalError(null);

      const qid = currentQuiz.question_id;

      if (rating === 'archive' || rating === 'suspend') {
        if (!hasQuizReviewCard(currentQuiz)) {
          return false;
        }
        try {
          await updateReviewQueueState({
            card_id: currentQuiz.review_card_id,
            state: rating === 'archive' ? 'archived' : 'suspended',
          });
        } catch (err: unknown) {
          setSignalError(errorMessage(err));
          return false;
        }
      }

      if (isReviewRating(rating)) {
        if (!hasQuizReviewCard(currentQuiz)) {
          setRated((prev) => ({ ...prev, [qid]: true }));
          return true;
        }

        if (QUIZ_REVIEW_PEEKED_THIS_SESSION && PEEKED_REVIEW_RATING_BLOCKLIST.has(rating)) {
          setSignalError(PEEKED_REVIEW_RATING_ERROR);
          return false;
        }

        try {
          const cardId = currentQuiz.review_card_id;
          await srsReview({
            idempotency_key: makeStableKey(runId, 'srs', cardId, rating),
            card_id: cardId,
            answer: rating,
            peeked_this_session: QUIZ_REVIEW_PEEKED_THIS_SESSION,
          });
        } catch (err: unknown) {
          setSignalError(errorMessage(err));
          return false;
        }
      }

      // Mark this card as rated so the Next button can appear; the user
      // must explicitly tap Next so they aren't auto-advanced past the
      // explanation panel.
      setRated((prev) => ({ ...prev, [qid]: true }));
      return true;
    },
    [currentQuiz, runId],
  );

  const ratedCount = Object.keys(rated).length;
  const correctCount = Object.values(answered).filter((answer) => answer.correct).length;
  const currentAnswer = currentQuiz ? answered[currentQuiz.question_id] : null;
  const currentEvidence = currentQuiz?.evidence ?? [];
  const currentConcepts = currentQuiz?.concepts ?? [];
  const currentSourceClaims = currentQuiz?.source_claims ?? [];
  const progressPercent = quizzes.length > 0 ? ((currentIndex + 1) / quizzes.length) * 100 : 0;

  /**
   * Phase 4C: 1/2/3/4 keyboard shortcuts to rate the current quiz card.
   * Mirrors ReviewPage so muscle-memory transfers between the two surfaces.
   *
   * The shortcut delegates to the actual rating buttons via `.click()` so
   * we inherit `SRSCard`'s `peekReady` / `PEEK_GUARD_MS` (1.5 s) gating —
   * shortcuts must not bypass the anti-peek guard that the buttons enforce
   * on revealed cards.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!currentQuiz) return;
      if (rated[currentQuiz.question_id]) return;
      if (!answered[currentQuiz.question_id]) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      let rating: SrsReviewRating | null = null;
      if (event.key === '1') rating = 'wrong';
      else if (event.key === '2') rating = 'hard';
      else if (event.key === '3') rating = 'good';
      else if (event.key === '4') rating = 'easy';
      if (!rating) return;
      event.preventDefault();
      const btn = document.querySelector<HTMLButtonElement>(
        `.srs-card__rating-btn--${rating}`,
      );
      if (btn && !btn.disabled) {
        btn.click();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [answered, currentQuiz, rated]);

  return (
    <AppShell>
      <div className="quiz-page">
        <div className="quiz-page__header">
          <h1 className="quiz-page__title">{t('Quiz.title')}</h1>
          {quizzes.length > 0 && (
            <span
              className="quiz-page__progress"
              role="status"
              aria-live="polite"
            >
              {t('Quiz.progress', {
                current: String(currentIndex + 1),
                total: String(quizzes.length),
              })}
            </span>
          )}
        </div>

        {loading ? (
          <p className="quiz-page__empty" role="status" aria-live="polite">
            <span className="loading-spinner" />{t('Serve.loading')}
          </p>
        ) : error ? (
          <div className="quiz-page__empty" role="alert">
            <p>{t('Error.fetch_failed', { resource: t('Nav.quiz') })}</p>
            <button type="button" className="retry-btn" onClick={fetchQuiz}>
              {t('Error.retry')}
            </button>
          </div>
        ) : quizzes.length === 0 ? (
          <p className="quiz-page__empty">{t('Serve.empty')}</p>
        ) : (
          <div className="quiz-page__learning-grid">
            <div className="quiz-page__quiz-column">
              <div
                className="quiz-page__progress-bar"
                role="progressbar"
                aria-valuenow={currentIndex + 1}
                aria-valuemin={1}
                aria-valuemax={quizzes.length}
                aria-label={t('Quiz.progress', {
                  current: String(currentIndex + 1),
                  total: String(quizzes.length),
                })}
              >
                <span
                  className="quiz-page__progress-fill"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>

              {currentQuiz && (
                <SRSCard
                  key={currentQuiz.question_id}
                  quiz={currentQuiz}
                  onAnswer={handleAnswer}
                  onRate={handleRate}
                  disabledReviewRatings={
                    hasQuizReviewCard(currentQuiz) ? PEEKED_REVIEW_RATING_BLOCKLIST : undefined
                  }
                />
              )}

              {signalError && (
                <div className="quiz-page__signal-error" role="alert">
                  {t('Quiz.signal_error', { message: signalError })}
                </div>
              )}

              {/* Next button when on current card and already rated.
                  Gating on `rated` (not `answered`) ensures the SRS signal
                  has been recorded before advancing — selecting a choice alone
                  is not enough. */}
              {currentIndex < quizzes.length - 1 && rated[currentQuiz?.question_id ?? ''] && (
                <div className="quiz-page__nav">
                  <button
                    type="button"
                    className="srs-card__btn srs-card__btn--primary"
                    onClick={() => setCurrentIndex((prev) => prev + 1)}
                  >
                    {t('Quiz.next')}
                  </button>
                </div>
              )}

              {/* Summary when every card has been rated */}
              {ratedCount === quizzes.length && currentIndex === quizzes.length - 1 && (
                <p className="quiz-page__progress quiz-page__progress--summary">
                  {t('Quiz.correct')}: {correctCount} / {quizzes.length}
                </p>
              )}
            </div>

            <aside className="quiz-page__side-panel" aria-label={t('Quiz.sidebar_label')}>
              <section className="quiz-panel quiz-panel--evidence">
                <div className="quiz-panel__header">
                  <h2>{t('Quiz.evidence_panel_title')}</h2>
                  <span className="quiz-panel__meta">{t('Quiz.evidence_panel_meta')}</span>
                </div>
                <div className="quiz-panel__body">
                  {currentAnswer ? (
                    <>
                      <ul className="quiz-evidence" aria-label={t('Quiz.evidence_label')}>
                        {currentEvidence.map((item) => (
                          <li
                            key={`${item.file}:${item.line}`}
                            className="quiz-evidence__item"
                          >
                            <div className="quiz-evidence__ref">
                              {formatEvidenceAnchor(item.file, item.line)}
                            </div>
                            <pre className="quiz-evidence__code">
                              <code>{formatEvidenceAnchor(item.file, item.line)}</code>
                            </pre>
                          </li>
                        ))}
                      </ul>
                      {(currentSourceClaims.length > 0 || currentConcepts.length > 0) && (
                        <dl className="quiz-evidence__meta">
                          {currentSourceClaims.length > 0 && (
                            <>
                              <dt>{t('Quiz.source_claims_label')}</dt>
                              <dd>{currentSourceClaims.join(', ')}</dd>
                            </>
                          )}
                          {currentConcepts.length > 0 && (
                            <>
                              <dt>{t('Quiz.concepts_label')}</dt>
                              <dd>{currentConcepts.join(', ')}</dd>
                            </>
                          )}
                        </dl>
                      )}
                    </>
                  ) : (
                    <p className="quiz-evidence__empty">{t('Quiz.evidence_locked')}</p>
                  )}
                </div>
              </section>

              <section className="quiz-panel">
                <div className="quiz-panel__header">
                  <h2>{t('Quiz.progress_panel_title')}</h2>
                  <span className="quiz-panel__meta">
                    {t('Quiz.progress_panel_meta', { count: quizzes.length })}
                  </span>
                </div>
                <div className="quiz-panel__body">
                  <ol className="quiz-progress-list">
                    {quizzes.map((quiz, index) => {
                      const isDone = Boolean(rated[quiz.question_id]);
                      const isCurrent = index === currentIndex && !isDone;
                      const statusKey = isDone
                        ? 'Quiz.progress_status_done'
                        : isCurrent
                          ? 'Quiz.progress_status_now'
                          : 'Quiz.progress_status_pending';
                      return (
                        <li
                          key={quiz.question_id}
                          className={[
                            'quiz-progress-list__item',
                            isDone ? 'quiz-progress-list__item--done' : '',
                            isCurrent ? 'quiz-progress-list__item--current' : '',
                          ].filter(Boolean).join(' ')}
                        >
                          <span className="quiz-progress-list__qid">
                            {t('Quiz.question_short', { number: index + 1 })}
                          </span>
                          <span className="quiz-progress-list__concept">
                            {quiz.concepts[0] ?? quiz.question_id}
                          </span>
                          <span className="quiz-progress-list__status">
                            {t(statusKey)}
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                </div>
              </section>

              {misconceptions.length > 0 && (
                <section
                  className="quiz-panel quiz-page__misconceptions"
                  aria-label={t('Quiz.misconceptions_title')}
                >
                  <div className="quiz-panel__header">
                    <h2>{t('Quiz.misconceptions_title')}</h2>
                    <span className="quiz-panel__meta">{misconceptions.length}</span>
                  </div>
                  <div className="quiz-panel__body">
                    {misconceptions.map((card) => (
                      <div key={card.card_id} className="quiz-page__misconception">
                        <strong>{card.concept}</strong>
                        <p>
                          {t('Quiz.misconception_label')}: {card.misconception}
                        </p>
                        <p>
                          {t('Quiz.correction_label')}: {card.correction}
                        </p>
                        <p>
                          {t('Quiz.evidence_label')}: {card.evidence_ref} ({card.severity})
                        </p>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </aside>
          </div>
        )}
      </div>
    </AppShell>
  );
}
