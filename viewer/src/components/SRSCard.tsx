import { useState, useEffect, useCallback, useId, type FormEvent } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import {
  hasQuizReviewCard,
  isQuizAnswerCorrect,
  type QuizItem,
} from '../utils/quiz-contract';

export type SrsRating = 'easy' | 'good' | 'hard' | 'wrong' | 'archive' | 'suspend';
export type SrsReviewRating = Exclude<SrsRating, 'archive' | 'suspend'>;

interface SRSCardProps {
  quiz: QuizItem;
  onAnswer: (questionId: string, answer: string, correct: boolean) => void;
  onRate: (rating: SrsRating) => boolean | Promise<boolean>;
  disabledReviewRatings?: ReadonlySet<SrsReviewRating>;
}

type CardPhase = 'question' | 'reveal' | 'rate';

const PEEK_GUARD_MS = 1500;
const EMPTY_DISABLED_REVIEW_RATINGS = new Set<SrsReviewRating>();

function isReviewRating(rating: SrsRating): rating is SrsReviewRating {
  return rating === 'easy' || rating === 'good' || rating === 'hard' || rating === 'wrong';
}

export default function SRSCard({
  quiz,
  onAnswer,
  onRate,
  disabledReviewRatings,
}: SRSCardProps) {
  const { t } = useTranslation();
  const questionId = useId();
  const answerId = useId();
  const disabledRatings = disabledReviewRatings ?? EMPTY_DISABLED_REVIEW_RATINGS;
  const reviewable = hasQuizReviewCard(quiz);

  const [answerText, setAnswerText] = useState('');
  const [submittedAnswer, setSubmittedAnswer] = useState('');
  const [phase, setPhase] = useState<CardPhase>('question');
  const [peekReady, setPeekReady] = useState(false);
  const [ratingPending, setRatingPending] = useState(false);

  // Reset state when quiz changes
  useEffect(() => {
    setAnswerText('');
    setSubmittedAnswer('');
    setPhase('question');
    setPeekReady(false);
    setRatingPending(false);
  }, [quiz.question_id]);

  // Peek guard timer: starts when entering reveal phase
  useEffect(() => {
    if (phase !== 'reveal') return;
    setPeekReady(false);
    const timer = setTimeout(() => {
      setPeekReady(true);
    }, PEEK_GUARD_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  const handleShowAnswer = useCallback(() => {
    const submitted = answerText.trim();
    if (!submitted) return;
    const correct = isQuizAnswerCorrect(submitted, quiz.expected_answer);
    setSubmittedAnswer(submitted);
    onAnswer(quiz.question_id, submitted, correct);
    setPhase('reveal');
  }, [answerText, quiz.expected_answer, quiz.question_id, onAnswer]);

  const handleSubmit = useCallback(
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      handleShowAnswer();
    },
    [handleShowAnswer],
  );

  const handleRate = useCallback(
    async (rating: SrsRating) => {
      if (ratingPending) return;
      if (isReviewRating(rating) && (!reviewable || !peekReady || disabledRatings.has(rating))) {
        return;
      }
      setRatingPending(true);
      try {
        const accepted = await onRate(rating);
        if (accepted !== false) setPhase('rate');
      } finally {
        setRatingPending(false);
      }
    },
    [disabledRatings, peekReady, ratingPending, reviewable, onRate],
  );

  const isCorrect =
    submittedAnswer.length > 0 && isQuizAnswerCorrect(submittedAnswer, quiz.expected_answer);
  const isRevealed = phase === 'reveal' || phase === 'rate';
  const isReviewButtonDisabled = (rating: SrsReviewRating) =>
    !reviewable || !peekReady || ratingPending || disabledRatings.has(rating);

  return (
    <div className="srs-card">
      <p className="srs-card__question" id={questionId}>{quiz.question}</p>

      {!isRevealed && (
        <form className="srs-card__answer-form" onSubmit={handleSubmit}>
          <label className="srs-card__answer-label" htmlFor={answerId}>
            {t('Quiz.answer_label')}
          </label>
          <textarea
            id={answerId}
            className="srs-card__answer-input"
            value={answerText}
            onChange={(event) => setAnswerText(event.target.value)}
            rows={3}
          />
          <button
            type="button"
            className="srs-card__btn srs-card__btn--primary"
            disabled={answerText.trim().length === 0}
            onClick={handleShowAnswer}
          >
            {t('Quiz.show_answer')}
          </button>
        </form>
      )}

      {/* Revealed: explanation + rating */}
      {isRevealed && (
        <>
          {/* Correct/Wrong indicator */}
          <p
            className={`srs-card__result ${isCorrect ? 'srs-card__result--correct' : 'srs-card__result--wrong'}`}
          >
            {isCorrect ? t('Quiz.correct') : t('Quiz.wrong')}
          </p>

          <div className="srs-card__explanation">
            <p className="srs-card__explanation-title">{t('Quiz.expected_answer')}</p>
            <p className="srs-card__explanation-body">{quiz.expected_answer}</p>
            <p className="srs-card__answer-meta">
              {t('Quiz.your_answer')}: {submittedAnswer}
            </p>
          </div>

          {quiz.explanation && (
            <div className="srs-card__explanation">
              <p className="srs-card__explanation-title">{t('Quiz.explanation_title')}</p>
              <p className="srs-card__explanation-body">{quiz.explanation}</p>
            </div>
          )}

          {quiz.evidence.length > 0 && (
            <div className="srs-card__evidence">
              <p className="srs-card__evidence-title">{t('Quiz.evidence_label')}</p>
              <p className="srs-card__evidence-body">
                {quiz.evidence.map((item) => `${item.file}:${item.line}`).join(', ')}
              </p>
            </div>
          )}

          {/* Rating buttons with peek guard */}
          {phase === 'reveal' && reviewable && (
            <>
              <div className="srs-card__rating">
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--easy"
                  disabled={isReviewButtonDisabled('easy')}
                  onClick={() => void handleRate('easy')}
                >
                  {t('SRS.easy')}
                </button>
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--good"
                  disabled={isReviewButtonDisabled('good')}
                  onClick={() => void handleRate('good')}
                >
                  {t('SRS.good')}
                </button>
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--hard"
                  disabled={isReviewButtonDisabled('hard')}
                  onClick={() => void handleRate('hard')}
                >
                  {t('SRS.hard')}
                </button>
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--wrong"
                  disabled={isReviewButtonDisabled('wrong')}
                  onClick={() => void handleRate('wrong')}
                >
                  {t('SRS.again')}
                </button>
              </div>

              {!peekReady && (
                <p className="srs-card__peek-hint">{t('Quiz.peek_guard_hint')}</p>
              )}

              <div className="srs-card__secondary">
                <button
                  type="button"
                  className="srs-card__secondary-btn"
                  disabled={ratingPending}
                  onClick={() => void handleRate('archive')}
                >
                  {t('SRS.archive')}
                </button>
                <button
                  type="button"
                  className="srs-card__secondary-btn"
                  disabled={ratingPending}
                  onClick={() => void handleRate('suspend')}
                >
                  {t('SRS.suspend')}
                </button>
              </div>
            </>
          )}

          {phase === 'reveal' && !reviewable && (
            <p className="srs-card__peek-hint">{t('Quiz.no_review_hint')}</p>
          )}
        </>
      )}
    </div>
  );
}
