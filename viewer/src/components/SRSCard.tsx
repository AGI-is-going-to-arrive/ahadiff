import { useState, useEffect, useCallback, useId, useMemo, useRef, type FormEvent } from 'react';
import { useTranslation, type MessageKey } from '../i18n/useTranslation';
import {
  hasChoices,
  hasQuizReviewCard,
  isQuizAnswerCorrect,
  type ExerciseErrorType,
  type ExerciseKind,
  type QuizChoice,
  type QuizChoiceLabel,
  type QuizItem,
  type QuizPrompt,
  type SelfAssessment,
} from '../utils/quiz-contract';
import './Practice.css';
import SourceAnchors from './SourceAnchors';

export type SrsRating = 'easy' | 'good' | 'hard' | 'wrong' | 'archive' | 'suspend';
export type SrsReviewRating = Exclude<SrsRating, 'archive' | 'suspend'>;
export interface ExerciseAssessment {
  selfAssessment: SelfAssessment;
  errorType: ExerciseErrorType;
}
export interface QuizRevealResult {
  question: QuizItem;
  correct: boolean | null;
  feedback_kind: 'choice_check' | 'reference_comparison' | 'semantic_self_assessment';
}

interface SRSCardProps {
  quiz: QuizPrompt | QuizItem;
  runId?: string;
  onReveal?: (selectedChoiceLabel: QuizChoiceLabel | null) => Promise<QuizRevealResult>;
  onAnswer: (questionId: string, answer: string, correct: boolean | null, revealed: QuizItem) => void;
  onRate: (rating: SrsRating, assessment?: ExerciseAssessment) => boolean | Promise<boolean>;
  disabledReviewRatings?: ReadonlySet<SrsReviewRating>;
}

type CardPhase = 'question' | 'reveal' | 'rate';
const PEEK_GUARD_MS = 1500;
const EMPTY_DISABLED_REVIEW_RATINGS = new Set<SrsReviewRating>();
const CHOICE_KEY_LABELS: Record<string, QuizChoiceLabel> = { a: 'A', b: 'B', c: 'C', d: 'D' };
const EXERCISE_KEYS: Record<ExerciseKind, MessageKey> = {
  prediction: 'Quiz.exercise_prediction',
  completion: 'Quiz.exercise_completion',
  error_reason: 'Quiz.exercise_error_reason',
};
const ERROR_KEYS: Record<Exclude<ExerciseErrorType, 'none'>, MessageKey> = {
  recall: 'Quiz.error_recall',
  application: 'Quiz.error_application',
  reasoning: 'Quiz.error_reasoning',
  boundary: 'Quiz.error_boundary',
};

function isReviewRating(rating: SrsRating): rating is SrsReviewRating {
  return rating === 'easy' || rating === 'good' || rating === 'hard' || rating === 'wrong';
}

export default function SRSCard({ quiz, runId, onReveal, onAnswer, onRate, disabledReviewRatings }: SRSCardProps) {
  const { t } = useTranslation();
  const questionId = useId();
  const answerId = useId();
  const choicesId = useId();
  const errorId = useId();
  const disabledRatings = disabledReviewRatings ?? EMPTY_DISABLED_REVIEW_RATINGS;
  const reviewable = hasQuizReviewCard(quiz);
  const activeExercise = quiz.exercise_kind != null;
  const choiceMode = hasChoices(quiz);
  const [answerText, setAnswerText] = useState('');
  const [submittedAnswer, setSubmittedAnswer] = useState('');
  const [selectedLabel, setSelectedLabel] = useState<QuizChoiceLabel | null>(null);
  const [revealed, setRevealed] = useState<QuizItem | null>(null);
  const [correct, setCorrect] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<CardPhase>('question');
  const [peekReady, setPeekReady] = useState(false);
  const [ratingPending, setRatingPending] = useState(false);
  const [revealPending, setRevealPending] = useState(false);
  const [revealError, setRevealError] = useState(false);
  const [errorType, setErrorType] = useState<Exclude<ExerciseErrorType, 'none'>>('application');
  const epochRef = useRef(0);
  const revealBusyRef = useRef(false);
  const ratingBusyRef = useRef(false);
  const choices = revealed?.choices ?? (choiceMode ? quiz.choices : []);
  const correctChoice = useMemo<QuizChoice | null>(
    () => revealed?.choices?.find((choice) => choice.is_correct) ?? null,
    [revealed],
  );

  useEffect(() => {
    epochRef.current += 1;
    setAnswerText('');
    setSubmittedAnswer('');
    setSelectedLabel(null);
    setRevealed(null);
    setCorrect(null);
    setPhase('question');
    setPeekReady(false);
    setRatingPending(false);
    setRevealPending(false);
    setRevealError(false);
    setErrorType('application');
    revealBusyRef.current = false;
    ratingBusyRef.current = false;
    return () => { epochRef.current += 1; };
  }, [quiz.question_id]);

  useEffect(() => {
    if (phase !== 'reveal') return;
    const timer = setTimeout(() => setPeekReady(true), PEEK_GUARD_MS);
    return () => clearTimeout(timer);
  }, [phase]);

  const revealAnswer = useCallback(async (label: QuizChoiceLabel | null) => {
    if (phase !== 'question' || revealBusyRef.current) return;
    const submitted = label ?? answerText.trim();
    if (!submitted) return;
    const epoch = epochRef.current;
    revealBusyRef.current = true;
    setRevealPending(true);
    setRevealError(false);
    try {
      let result: QuizRevealResult;
      if (onReveal) {
        result = await onReveal(label);
      } else if ('expected_answer' in quiz) {
        // Compatibility for explicit local artifact consumers, not public API prompts.
        result = {
          question: quiz,
          correct: activeExercise ? null : label
            ? quiz.choices?.find((choice) => choice.label === label)?.is_correct ?? false
            : isQuizAnswerCorrect(submitted, quiz.expected_answer),
          feedback_kind: activeExercise ? 'semantic_self_assessment' : label ? 'choice_check' : 'reference_comparison',
        };
      } else {
        throw new Error('Answer reveal unavailable');
      }
      if (epoch !== epochRef.current) return;
      if (result.question.question_id !== quiz.question_id || result.question.question !== quiz.question ||
        (result.question.review_card_id ?? null) !== (quiz.review_card_id ?? null) ||
        (result.question.exercise_kind ?? null) !== (quiz.exercise_kind ?? null)) {
        throw new Error('Wrong question reveal');
      }
      const answerCorrect = activeExercise ? null : label !== null ? result.correct
        : isQuizAnswerCorrect(submitted, result.question.expected_answer);
      setRevealed(result.question);
      setCorrect(answerCorrect);
      setSelectedLabel(label);
      setSubmittedAnswer(label ? result.question.choices?.find((choice) => choice.label === label)?.text ?? label : submitted);
      onAnswer(quiz.question_id, submitted, answerCorrect, result.question);
      setPhase('reveal');
    } catch {
      if (epoch === epochRef.current) setRevealError(true);
    } finally {
      if (epoch === epochRef.current) {
        revealBusyRef.current = false;
        setRevealPending(false);
      }
    }
  }, [activeExercise, answerText, onAnswer, onReveal, phase, quiz]);

  const handleSubmit = useCallback((event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void revealAnswer(null);
  }, [revealAnswer]);

  useEffect(() => {
    if (!choiceMode || phase !== 'question') return;
    const onKey = (event: KeyboardEvent) => {
      if (event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) return;
      const label = CHOICE_KEY_LABELS[event.key.toLowerCase()];
      if (!label || !choices.some((choice) => choice.label === label)) return;
      event.preventDefault();
      void revealAnswer(label);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [choiceMode, choices, phase, revealAnswer]);

  const handleRate = useCallback(async (rating: SrsRating, selfAssessment?: SelfAssessment) => {
    if (ratingBusyRef.current || !peekReady || phase !== 'reveal') return;
    if (!activeExercise && isReviewRating(rating) && (!reviewable || disabledRatings.has(rating))) return;
    ratingBusyRef.current = true;
    setRatingPending(true);
    try {
      const assessment = selfAssessment ? {
        selfAssessment, errorType: selfAssessment === 'independent' ? 'none' as const : errorType,
      } : undefined;
      const accepted = await onRate(rating, assessment);
      if (accepted !== false) setPhase('rate');
    } finally {
      ratingBusyRef.current = false;
      setRatingPending(false);
    }
  }, [activeExercise, disabledRatings, errorType, onRate, peekReady, phase, reviewable]);

  const isRevealed = revealed !== null && phase !== 'question';
  const isReviewButtonDisabled = (rating: SrsReviewRating): boolean =>
    !reviewable || !peekReady || ratingPending || disabledRatings.has(rating);

  return (
    <div className="srs-card" aria-busy={revealPending || ratingPending}>
      {quiz.exercise_kind && <p className="srs-card__choice-prompt">{t(EXERCISE_KEYS[quiz.exercise_kind])}</p>}
      <p className="srs-card__question" id={questionId}>{quiz.question}</p>
      {activeExercise && <p className="srs-card__peek-hint">{t('Quiz.exercise_instruction')}</p>}
      {!isRevealed && choiceMode && <>
        <p className="srs-card__choice-prompt" id={choicesId}>{t('Quiz.select_prompt')}</p>
        <div className="srs-card__choices" role="radiogroup" aria-labelledby={`${questionId} ${choicesId}`}>
          {choices.map((choice) => (
            <button key={choice.label} type="button" role="radio" aria-checked={false}
              aria-label={t('Quiz.choice_a11y', { label: choice.label, text: choice.text })}
              className="srs-card__choice" disabled={revealPending} onClick={() => void revealAnswer(choice.label)}>
              <span className="srs-card__choice-letter" aria-hidden="true">{choice.label}</span>
              <span className="srs-card__choice-content"><span className="srs-card__choice-text">{choice.text}</span></span>
            </button>
          ))}
        </div>
      </>}
      {!isRevealed && !choiceMode && (
        <form className="srs-card__answer-form" onSubmit={handleSubmit}>
          <label className="srs-card__answer-label" htmlFor={answerId}>{t('Quiz.answer_label')}</label>
          <textarea id={answerId} className="srs-card__answer-input" value={answerText} rows={4}
            maxLength={16000} disabled={revealPending} onChange={(event) => setAnswerText(event.target.value)} />
          <button type="submit" className="srs-card__btn srs-card__btn--primary"
            disabled={answerText.trim().length === 0 || revealPending}>{t('Quiz.show_answer')}</button>
        </form>
      )}
      {revealError && <p className="quiz-page__signal-error" role="alert">{t('Quiz.reveal_failed')}</p>}
      {revealPending && <p className="srs-card__peek-hint" role="status">{t('Serve.loading')}</p>}
      {isRevealed && revealed && <>
        {choiceMode && (
          <div className="srs-card__choices srs-card__choices--revealed" role="radiogroup" aria-label={t('Quiz.select_prompt')}>
            {(revealed.choices ?? []).map((choice) => {
              const selected = selectedLabel === choice.label;
              const state = choice.is_correct ? ' srs-card__choice--correct' : selected ? ' srs-card__choice--wrong' : '';
              return <button key={choice.label} type="button" role="radio" aria-checked={selected} disabled
                aria-label={t('Quiz.choice_a11y', { label: choice.label, text: choice.text })}
                className={`srs-card__choice srs-card__choice--disabled${state}${selected ? ' srs-card__choice--selected' : ''}`}>
                <span className="srs-card__choice-letter" aria-hidden="true">{choice.label}</span>
                <span className="srs-card__choice-content"><span className="srs-card__choice-text">{choice.text}</span></span>
              </button>;
            })}
          </div>
        )}
        {activeExercise ? <p className="srs-card__peek-hint" role="status">{t('Quiz.semantic_feedback')}</p> : (
          <p className={`srs-card__result ${correct ? 'srs-card__result--correct' : 'srs-card__result--wrong'}`}>
            {choiceMode ? (correct ? t('Quiz.correct') : t('Quiz.wrong'))
              : (correct ? t('Quiz.text_matches') : t('Quiz.text_differs'))}
          </p>
        )}
        <div className="srs-card__explanation">
          <p className="srs-card__explanation-title">{choiceMode ? t('Quiz.correct_answer_is') : t('Quiz.expected_answer')}</p>
          <p className="srs-card__explanation-body">{choiceMode && correctChoice
            ? `${correctChoice.label}. ${correctChoice.text}` : revealed.expected_answer}</p>
          <p className="srs-card__answer-meta">{choiceMode ? t('Quiz.selected_choice') : t('Quiz.your_answer')}: {submittedAnswer}</p>
        </div>
        {revealed.explanation && <div className="srs-card__explanation">
          <p className="srs-card__explanation-title">{t('Quiz.explanation_title')}</p>
          <p className="srs-card__explanation-body">{revealed.explanation}</p>
        </div>}
        {(revealed.evidence.length > 0 || (revealed.source_anchors?.length ?? 0) > 0) && <div className="srs-card__evidence">
          <p className="srs-card__evidence-title">{t('Quiz.evidence_label')}</p>
          <p className="srs-card__evidence-body">{revealed.evidence.map((item, index) => <span key={`${item.file}:${item.line}`}>
            {index > 0 ? ', ' : ''}{runId ? <a className="srs-card__evidence-link"
              href={`#/run/${encodeURIComponent(runId)}/diff?focus=${encodeURIComponent(`${item.file}:${item.line}`)}`}>
              {item.file}:{item.line}
            </a> : `${item.file}:${item.line}`}
          </span>)}</p>
          {revealed.concepts.length > 0 && <p className="srs-card__evidence-body">{t('Quiz.concepts_label')}: {revealed.concepts.join(', ')}</p>}
          <SourceAnchors anchors={revealed.source_anchors ?? []} onJump={runId ? (anchor) => {
            window.location.hash = `/run/${encodeURIComponent(runId)}/diff?anchor=${encodeURIComponent(anchor.anchor_id)}`;
          } : undefined} />
        </div>}
        {phase === 'reveal' && activeExercise && <>
          <label className="srs-card__answer-label" htmlFor={errorId}>{t('Quiz.error_type_label')}</label>
          <select id={errorId} className="practice-error-select" value={errorType} disabled={ratingPending}
            onChange={(event) => {
              const value = event.target.value;
              if (value === 'recall' || value === 'application' || value === 'reasoning' || value === 'boundary') setErrorType(value);
            }}>
            {(Object.keys(ERROR_KEYS) as Exclude<ExerciseErrorType, 'none'>[]).map((kind) =>
              <option key={kind} value={kind}>{t(ERROR_KEYS[kind])}</option>)}
          </select>
          <div className="srs-card__rating">
            <button type="button" className="srs-card__rating-btn srs-card__rating-btn--good" disabled={!peekReady || ratingPending}
              onClick={() => void handleRate('good', 'independent')}>{t('Quiz.assess_independent')}</button>
            <button type="button" className="srs-card__rating-btn srs-card__rating-btn--hard" disabled={!peekReady || ratingPending}
              onClick={() => void handleRate('hard', 'assisted')}>{t('Quiz.assess_assisted')}</button>
            <button type="button" className="srs-card__rating-btn srs-card__rating-btn--wrong" disabled={!peekReady || ratingPending}
              onClick={() => void handleRate('wrong', 'not_yet')}>{t('Quiz.assess_not_yet')}</button>
          </div>
          <p className="srs-card__peek-hint">{t('Quiz.exercise_privacy')}</p>
        </>}
        {phase === 'reveal' && reviewable && !activeExercise && <div className="srs-card__rating">
          {(['good', 'hard', 'wrong'] as const).map((rating) => <button key={rating} type="button"
            className={`srs-card__rating-btn srs-card__rating-btn--${rating}`} disabled={isReviewButtonDisabled(rating)}
            onClick={() => void handleRate(rating)}>{t(rating === 'good' ? 'SRS.good' : rating === 'hard' ? 'SRS.hard' : 'SRS.again')}</button>)}
        </div>}
        {phase === 'reveal' && (reviewable || activeExercise) && !peekReady && <p className="srs-card__peek-hint">{t('Quiz.peek_guard_hint')}</p>}
        {phase === 'reveal' && !reviewable && !activeExercise && <p className="srs-card__peek-hint">{t('Quiz.no_review_hint')}</p>}
      </>}
    </div>
  );
}
