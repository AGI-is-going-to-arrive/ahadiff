import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useParams } from 'react-router-dom';
import AppShell from '../components/AppShell';
import SRSCard from '../components/SRSCard';
import type { QuizItem, SrsRating } from '../components/SRSCard';
import { getRunArtifact } from '../api/runs';
import { quizAnswer, srsReview } from '../api/signals';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Quiz.css';

interface AnswerRecord {
  choice: number;
  correct: boolean;
  peekAt: number;
}

function parseQuizJsonl(content: string): QuizItem[] {
  const items: QuizItem[] = [];
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const parsed = JSON.parse(trimmed) as QuizItem;
      const choicesValid =
        Array.isArray(parsed.choices) && parsed.choices.every((c) => typeof c === 'string');
      const idValid = typeof parsed.quiz_id === 'string' && parsed.quiz_id.length > 0;
      const qValid = typeof parsed.question === 'string' && parsed.question.length > 0;
      const answerValid =
        typeof parsed.answer_index === 'number' &&
        Number.isInteger(parsed.answer_index) &&
        parsed.answer_index >= 0 &&
        parsed.answer_index < (parsed.choices?.length ?? 0);
      if (idValid && qValid && choicesValid && answerValid) {
        items.push(parsed);
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

export default function QuizPage() {
  const { runId } = useParams<{ runId: string }>();
  const { t } = useTranslation();

  const [quizzes, setQuizzes] = useState<QuizItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answered, setAnswered] = useState<Record<string, AnswerRecord>>({});
  // `rated` gates the Next button — users must invoke onRate (good/hard/wrong
  // for SRS-tracked review, or archive/suspend) before advancing. Only
  // good/hard/wrong actually emit the SRS signal; archive/suspend still mark
  // the card as rated so the user can move on.
  const [rated, setRated] = useState<Record<string, boolean>>({});
  const abortRef = useRef<AbortController | null>(null);

  const fetchQuiz = useCallback(() => {
    if (!runId) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);

    getRunArtifact(runId, 'quiz', { signal: controller.signal })
      .then((envelope) => {
        if (controller.signal.aborted) return;
        const items = parseQuizJsonl(envelope.content);
        setQuizzes(items);
        setCurrentIndex(0);
        setAnswered({});
        setRated({});
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
    (quizId: string, choice: number, correct: boolean) => {
      setAnswered((prev) => ({
        ...prev,
        [quizId]: { choice, correct, peekAt: Date.now() },
      }));

      // Fire quiz-answer signal (fire-and-forget)
      if (runId) {
        void quizAnswer({
          idempotency_key: makeStableKey(runId, 'qa', quizId, `choice-${choice}`),
          quiz_id: quizId,
          choice: String(choice),
          correct,
        }).catch(() => {
          // signal failure is non-blocking
        });
      }
    },
    [runId],
  );

  const handleRate = useCallback(
    (rating: SrsRating) => {
      if (!currentQuiz || !runId) return;

      const qid = currentQuiz.quiz_id;

      // Map quiz rating to SRS answer for the review signal
      if (rating === 'good' || rating === 'hard' || rating === 'wrong') {
        const answerMap = { good: 'good', hard: 'hard', wrong: 'wrong' } as const;
        void srsReview({
          idempotency_key: makeStableKey(runId, 'srs', qid, answerMap[rating]),
          card_id: qid,
          answer: answerMap[rating],
        }).catch(() => {
          // signal failure is non-blocking
        });
      }

      // Mark this card as rated so the Next button can appear; the user
      // must explicitly tap Next so they aren't auto-advanced past the
      // explanation panel.
      setRated((prev) => ({ ...prev, [qid]: true }));
    },
    [currentQuiz, runId],
  );

  const ratedCount = Object.keys(rated).length;

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
          <>
            {currentQuiz && (
              <SRSCard
                key={currentQuiz.quiz_id}
                quiz={currentQuiz}
                onAnswer={handleAnswer}
                onRate={handleRate}
              />
            )}

            {/* Next button when on current card and already rated.
                Gating on `rated` (not `answered`) ensures the SRS signal
                has been recorded before advancing — selecting a choice alone
                is not enough. */}
            {currentIndex < quizzes.length - 1 && rated[currentQuiz?.quiz_id ?? ''] && (
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
                {t('Quiz.correct')}: {Object.values(answered).filter((a) => a.correct).length} / {quizzes.length}
              </p>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
