import { useState, useEffect, useCallback, useId, useMemo, type FormEvent } from 'react';
import { useTranslation } from '../i18n/useTranslation';
import {
  hasChoices,
  hasQuizReviewCard,
  isQuizAnswerCorrect,
  type QuizChoice,
  type QuizChoiceLabel,
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
const CHOICE_KEY_LABELS: Record<string, QuizChoiceLabel> = {
  a: 'A',
  b: 'B',
  c: 'C',
  d: 'D',
};

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
  const choicesId = useId();
  const disabledRatings = disabledReviewRatings ?? EMPTY_DISABLED_REVIEW_RATINGS;
  const reviewable = hasQuizReviewCard(quiz);
  const choiceMode = hasChoices(quiz);
  const choices: QuizChoice[] = choiceMode ? quiz.choices : [];
  const correctChoice = useMemo<QuizChoice | null>(() => {
    if (!choiceMode) return null;
    return choices.find((choice) => choice.is_correct) ?? null;
  }, [choiceMode, choices]);

  const [answerText, setAnswerText] = useState('');
  const [submittedAnswer, setSubmittedAnswer] = useState('');
  const [selectedLabel, setSelectedLabel] = useState<QuizChoiceLabel | null>(null);
  const [phase, setPhase] = useState<CardPhase>('question');
  const [peekReady, setPeekReady] = useState(false);
  const [ratingPending, setRatingPending] = useState(false);

  // Reset state when quiz changes
  useEffect(() => {
    setAnswerText('');
    setSubmittedAnswer('');
    setSelectedLabel(null);
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

  const handleSelectChoice = useCallback(
    (choice: QuizChoice) => {
      if (phase !== 'question') return;
      const correct = choice.is_correct;
      setSelectedLabel(choice.label);
      setSubmittedAnswer(choice.text);
      onAnswer(quiz.question_id, choice.label, correct);
      setPhase('reveal');
    },
    [onAnswer, phase, quiz.question_id],
  );

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

  // A/B/C/D keyboard shortcuts: question phase only, choices required.
  // Skips when typing into a text field so other shortcuts are unaffected.
  useEffect(() => {
    if (!choiceMode) return;
    if (phase !== 'question') return;
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      const label = CHOICE_KEY_LABELS[event.key.toLowerCase()];
      if (!label) return;
      const choice = choices.find((c) => c.label === label);
      if (!choice) return;
      event.preventDefault();
      handleSelectChoice(choice);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [choiceMode, choices, handleSelectChoice, phase]);

  const handleRate = useCallback(
    async (rating: SrsRating) => {
      if (ratingPending) return;
      if (reviewable && !peekReady) return;
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

  const isCorrect = choiceMode
    ? selectedLabel !== null && correctChoice?.label === selectedLabel
    : submittedAnswer.length > 0 && isQuizAnswerCorrect(submittedAnswer, quiz.expected_answer);
  const isRevealed = phase === 'reveal' || phase === 'rate';
  const isReviewButtonDisabled = (rating: SrsReviewRating) =>
    !reviewable || !peekReady || ratingPending || disabledRatings.has(rating);

  return (
    <div className="srs-card">
      <p className="srs-card__question" id={questionId}>{quiz.question}</p>

      {!isRevealed && choiceMode && (
        <>
          <p className="srs-card__choice-prompt" id={choicesId}>
            {t('Quiz.select_prompt')}
          </p>
          <div
            className="srs-card__choices"
            role="radiogroup"
            aria-labelledby={`${questionId} ${choicesId}`}
          >
            {choices.map((choice) => {
              const ariaLabel = t('Quiz.choice_a11y', {
                label: choice.label,
                text: choice.text,
              });
              return (
                <button
                  key={choice.label}
                  type="button"
                  role="radio"
                  aria-checked={selectedLabel === choice.label}
                  aria-label={ariaLabel}
                  className={`srs-card__choice${
                    selectedLabel === choice.label ? ' srs-card__choice--selected' : ''
                  }`}
                  onClick={() => handleSelectChoice(choice)}
                >
                  <span className="srs-card__choice-letter" aria-hidden="true">
                    {choice.label}
                  </span>
                  <span className="srs-card__choice-content">
                    <span className="srs-card__choice-text">{choice.text}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}

      {!isRevealed && !choiceMode && (
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
          {/* In choice mode, show all options with correct/wrong markers. */}
          {choiceMode && (
            <div
              className="srs-card__choices srs-card__choices--revealed"
              role="radiogroup"
              aria-label={t('Quiz.select_prompt')}
            >
              {choices.map((choice) => {
                const isThisCorrect = choice.is_correct;
                const isThisSelected = selectedLabel === choice.label;
                const isThisWrong = isThisSelected && !isThisCorrect;
                const stateClass = isThisCorrect
                  ? ' srs-card__choice--correct'
                  : isThisWrong
                    ? ' srs-card__choice--wrong'
                    : '';
                const ariaLabel = t('Quiz.choice_a11y', {
                  label: choice.label,
                  text: choice.text,
                });
                return (
                  <button
                    key={choice.label}
                    type="button"
                    role="radio"
                    aria-checked={isThisSelected}
                    aria-label={ariaLabel}
                    className={`srs-card__choice srs-card__choice--disabled${stateClass}${
                      isThisSelected ? ' srs-card__choice--selected' : ''
                    }`}
                    disabled
                  >
                    <span className="srs-card__choice-letter" aria-hidden="true">
                      {choice.label}
                    </span>
                    <span className="srs-card__choice-content">
                      <span className="srs-card__choice-text">{choice.text}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Correct/Wrong indicator */}
          <p
            className={`srs-card__result ${isCorrect ? 'srs-card__result--correct' : 'srs-card__result--wrong'}`}
          >
            {isCorrect ? t('Quiz.correct') : t('Quiz.wrong')}
          </p>

          <div className="srs-card__explanation">
            <p className="srs-card__explanation-title">
              {choiceMode ? t('Quiz.correct_answer_is') : t('Quiz.expected_answer')}
            </p>
            <p className="srs-card__explanation-body">
              {choiceMode && correctChoice
                ? `${correctChoice.label}. ${correctChoice.text}`
                : quiz.expected_answer}
            </p>
            <p className="srs-card__answer-meta">
              {choiceMode ? t('Quiz.selected_choice') : t('Quiz.your_answer')}: {submittedAnswer}
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

          {/* Rating buttons with peek guard.
              v0.1: only Good / Hard / Wrong are shown. Easy / Archive / Suspend
              are intentionally hidden (kept in the SrsRating type for future
              compatibility but not rendered). */}
          {phase === 'reveal' && reviewable && (
            <>
              <div className="srs-card__rating">
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
