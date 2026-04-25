import { useState, useEffect, useCallback, useId } from 'react';
import { useTranslation } from '../i18n/useTranslation';

export type SrsRating = 'good' | 'hard' | 'wrong' | 'archive' | 'suspend';

export interface QuizItem {
  quiz_id: string;
  question: string;
  choices: string[];
  answer_index: number;
  explanation?: string;
  claim_ref?: string;
}

interface SRSCardProps {
  quiz: QuizItem;
  onAnswer: (quizId: string, choice: number, correct: boolean) => void;
  onRate: (rating: SrsRating) => void;
}

type CardPhase = 'question' | 'select' | 'reveal' | 'rate';

const PEEK_GUARD_MS = 1500;

export default function SRSCard({ quiz, onAnswer, onRate }: SRSCardProps) {
  const { t } = useTranslation();
  const questionId = useId();

  const [selected, setSelected] = useState<number | null>(null);
  const [phase, setPhase] = useState<CardPhase>('question');
  const [peekReady, setPeekReady] = useState(false);

  // Reset state when quiz changes
  useEffect(() => {
    setSelected(null);
    setPhase('question');
    setPeekReady(false);
  }, [quiz.quiz_id]);

  // Peek guard timer: starts when entering reveal phase
  useEffect(() => {
    if (phase !== 'reveal') return;
    setPeekReady(false);
    const timer = setTimeout(() => {
      setPeekReady(true);
    }, PEEK_GUARD_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  const handleSelect = useCallback(
    (index: number) => {
      if (phase === 'reveal' || phase === 'rate') return;
      setSelected(index);
      if (phase === 'question') setPhase('select');
    },
    [phase],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && phase === 'select' && selected !== null) {
        e.preventDefault();
        const correct = selected === quiz.answer_index;
        onAnswer(quiz.quiz_id, selected, correct);
        setPhase('reveal');
      }
    },
    [phase, selected, quiz.quiz_id, quiz.answer_index, onAnswer],
  );

  const handleShowAnswer = useCallback(() => {
    if (selected === null) return;
    const correct = selected === quiz.answer_index;
    onAnswer(quiz.quiz_id, selected, correct);
    setPhase('reveal');
  }, [selected, quiz.quiz_id, quiz.answer_index, onAnswer]);

  const handleRate = useCallback(
    (rating: SrsRating) => {
      if (!peekReady && rating !== 'archive' && rating !== 'suspend') return;
      setPhase('rate');
      onRate(rating);
    },
    [peekReady, onRate],
  );

  const isCorrect = selected !== null && selected === quiz.answer_index;
  const isRevealed = phase === 'reveal' || phase === 'rate';

  return (
    <div className="srs-card">
      <p className="srs-card__question" id={questionId}>{quiz.question}</p>

      <div
        className="srs-card__choices"
        role="radiogroup"
        aria-labelledby={questionId}
        onKeyDown={handleKeyDown}
      >
        {quiz.choices.map((choice, idx) => {
          let choiceClass = 'srs-card__choice';
          if (selected === idx && !isRevealed) choiceClass += ' srs-card__choice--selected';
          if (isRevealed) {
            choiceClass += ' srs-card__choice--disabled';
            if (idx === quiz.answer_index) choiceClass += ' srs-card__choice--correct';
            if (idx === selected && idx !== quiz.answer_index)
              choiceClass += ' srs-card__choice--wrong';
          }

          return (
            <label key={`${quiz.quiz_id}-${idx}-${choice}`} className={choiceClass}>
              <input
                type="radio"
                name={`quiz-${quiz.quiz_id}`}
                value={idx}
                checked={selected === idx}
                disabled={isRevealed}
                onChange={() => handleSelect(idx)}
              />
              {choice}
            </label>
          );
        })}
      </div>

      {/* Show Answer button */}
      {!isRevealed && (
        <div className="srs-card__actions">
          <button
            type="button"
            className="srs-card__btn srs-card__btn--primary"
            disabled={selected === null}
            onClick={handleShowAnswer}
          >
            {t('Quiz.show_answer')}
          </button>
        </div>
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

          {quiz.explanation && (
            <div className="srs-card__explanation">
              <p className="srs-card__explanation-title">{t('Quiz.explanation_title')}</p>
              <p className="srs-card__explanation-body">{quiz.explanation}</p>
            </div>
          )}

          {/* Rating buttons with peek guard */}
          {phase === 'reveal' && (
            <>
              <div className="srs-card__rating">
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--good"
                  disabled={!peekReady}
                  onClick={() => handleRate('good')}
                >
                  {t('SRS.good')}
                </button>
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--hard"
                  disabled={!peekReady}
                  onClick={() => handleRate('hard')}
                >
                  {t('SRS.hard')}
                </button>
                <button
                  type="button"
                  className="srs-card__rating-btn srs-card__rating-btn--wrong"
                  disabled={!peekReady}
                  onClick={() => handleRate('wrong')}
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
                  onClick={() => handleRate('archive')}
                >
                  {t('SRS.archive')}
                </button>
                <button
                  type="button"
                  className="srs-card__secondary-btn"
                  onClick={() => handleRate('suspend')}
                >
                  {t('SRS.suspend')}
                </button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
