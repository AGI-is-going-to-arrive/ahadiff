import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import CalendarHeatmap from '../components/CalendarHeatmap';
import type { HeatmapCell } from '../components/CalendarHeatmap';
import InfoHint from '../components/InfoHint';
import Skeleton from '../components/Skeleton';
import { fetchReviewHeatmap } from '../api/stats';
import { getReviewMastery, getWeakConcepts, updateReviewQueueState } from '../api/review';
import type {
  DueReviewCard,
  ReviewAnswer,
  ReviewChoice,
  ReviewMasteryItem,
  ReviewQueueState,
  WeakConceptItem,
} from '../api/types';
import { useReviewStore } from '../state/review-store';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Review.css';

type ReviewErrorKind = 'network' | 'auth' | 'unknown';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));

type RatingSummary = Record<ReviewAnswer, number>;

const REVIEW_RATING_ORDER: ReviewAnswer[] = ['wrong', 'hard', 'good', 'easy'];
const REVIEW_RATING_LABEL_KEYS: Record<ReviewAnswer, string> = {
  wrong: 'Review.rating_wrong',
  hard: 'Review.rating_hard',
  good: 'Review.rating_good',
  easy: 'Review.rating_easy',
};

const CHOICE_KEY_LABELS: Record<string, string> = {
  a: 'A',
  b: 'B',
  c: 'C',
  d: 'D',
};

function currentReviewCardParam(): string | null {
  const query = window.location.hash.split('?')[1] ?? '';
  return new URLSearchParams(query).get('card');
}

/**
 * A card renders as ABCD multiple choice when the backend explicitly says so
 * AND ships a non-empty `choices` array. Cards with `answer_mode === 'open'`
 * or no choices keep the existing flip-card flow unchanged.
 */
function isChoiceCard(
  card: DueReviewCard,
): card is DueReviewCard & { choices: ReviewChoice[] } {
  return (
    card.answer_mode === 'multiple_choice' &&
    Array.isArray(card.choices) &&
    card.choices.length > 0
  );
}

function classifyError(e: unknown): ReviewErrorKind {
  if (e instanceof TypeError) return 'network';
  if (e instanceof DOMException && e.name === 'AbortError') return 'network';
  if (
    e != null &&
    typeof e === 'object' &&
    'status' in e &&
    typeof (e as { status: unknown }).status === 'number'
  ) {
    const status = (e as { status: number }).status;
    if (status === 401 || status === 403) return 'auth';
  }
  return 'unknown';
}

function createRatingSummary(): RatingSummary {
  return {
    wrong: 0,
    hard: 0,
    good: 0,
    easy: 0,
  };
}

function countRatings(summary: RatingSummary): number {
  return REVIEW_RATING_ORDER.reduce((total, answer) => total + summary[answer], 0);
}

export default function ReviewPage() {
  const { t } = useTranslation();
  const cards = useReviewStore((s) => s.cards);
  const currentIndex = useReviewStore((s) => s.currentIndex);
  const loading = useReviewStore((s) => s.loading);
  const rating = useReviewStore((s) => s.rating);
  const error = useReviewStore((s) => s.error);
  const loadQueue = useReviewStore((s) => s.loadQueue);
  const rate = useReviewStore((s) => s.rate);
  const currentCard = useReviewStore((s) => s.currentCard);
  const selectCard = useReviewStore((s) => s.selectCard);

  const [flipped, setFlipped] = useState(false);
  const [selectedChoiceLabel, setSelectedChoiceLabel] = useState<string | null>(null);
  const [sessionRatings, setSessionRatings] = useState<RatingSummary>(() => createRatingSummary());
  const [heatmapCells, setHeatmapCells] = useState<HeatmapCell[]>([]);
  const [mastery, setMastery] = useState<ReviewMasteryItem[]>([]);
  const [weakConcepts, setWeakConcepts] = useState<WeakConceptItem[]>([]);
  const [newConcepts, setNewConcepts] = useState<WeakConceptItem[]>([]);
  const [summaryOpen, setSummaryOpen] = useState(true);
  const [queueStateBusy, setQueueStateBusy] = useState(false);
  const [queueStateMessage, setQueueStateMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const refreshAbortRef = useRef<AbortController | null>(null);
  const queueStateAbortRef = useRef<AbortController | null>(null);
  const queueStateBusyRef = useRef(false);
  const deepLinkCardRef = useRef<string | null>(currentReviewCardParam());
  const flipBtnRef = useRef<HTMLButtonElement | null>(null);
  const firstRatingRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    void loadQueue({ signal: controller.signal });
    return () => {
      controller.abort();
      // Also abort any in-flight post-rating refresh requests on unmount
      refreshAbortRef.current?.abort();
    };
  }, [loadQueue]);

  const fetchOverviewData = useCallback((signal: AbortSignal) => {
    Promise.allSettled([
      fetchReviewHeatmap({ signal }),
      getReviewMastery({ signal }),
      getWeakConcepts({ signal }),
    ]).then(([heatRes, masteryRes, weakRes]) => {
      if (signal.aborted) return;
      if (heatRes.status === 'fulfilled') {
        setHeatmapCells(
          heatRes.value.entries.map((e) => ({
            iso_date: e.date,
            count: e.review_count,
          })),
        );
      }
      if (masteryRes.status === 'fulfilled') setMastery(masteryRes.value.mastery);
      if (weakRes.status === 'fulfilled') {
        setWeakConcepts(weakRes.value.concepts);
        setNewConcepts(weakRes.value.new_concepts ?? []);
      }

    });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchOverviewData(ctrl.signal);
    return () => ctrl.abort();
  }, [fetchOverviewData]);

  useEffect(() => {
    const syncCardDeepLink = () => {
      deepLinkCardRef.current = currentReviewCardParam();
      const cardId = deepLinkCardRef.current;
      if (cardId) selectCard(cardId);
    };
    window.addEventListener('hashchange', syncCardDeepLink);
    return () => window.removeEventListener('hashchange', syncCardDeepLink);
  }, [selectCard]);

  useEffect(() => {
    const cardId = deepLinkCardRef.current;
    if (!cardId || cards.length === 0) return;
    if (selectCard(cardId)) deepLinkCardRef.current = null;
  }, [cards, selectCard]);

  useEffect(() => {
    setFlipped(false);
    setSelectedChoiceLabel(null);
    requestAnimationFrame(() => flipBtnRef.current?.focus());
  }, [currentIndex]);

  // WARNING 2 fix: move focus to the first SRS rating button after flip.
  // Choice cards reveal via `selectedChoiceLabel`; same focus migration.
  useEffect(() => {
    if (flipped || selectedChoiceLabel !== null) {
      requestAnimationFrame(() => firstRatingRef.current?.focus());
    }
  }, [flipped, selectedChoiceLabel]);

  useEffect(() => {
    setSessionRatings(createRatingSummary());
  }, [cards]);

  const handleRate = useCallback(
    async (answer: ReviewAnswer) => {
      const card = useReviewStore.getState().currentCard();
      const beforeIndex = useReviewStore.getState().currentIndex;
      // For multiple_choice cards: the user committed to a label without
      // peeking, so forward the selected label and peeked=false. For open
      // cards: the user clicked "Show answer" before rating, so peeked=true.
      const isChoice = card ? isChoiceCard(card) : false;
      const result = await rate(answer, {
        peekedThisSession: isChoice ? false : true,
        selectedChoiceLabel: isChoice ? selectedChoiceLabel : null,
      });
      const afterIndex = useReviewStore.getState().currentIndex;
      if (afterIndex > beforeIndex) {
        setSessionRatings((prev) => ({
          ...prev,
          [answer]: prev[answer] + 1,
        }));
      }
      // Refresh overview sidebar data when a new rating was persisted
      if (result?.inserted) {
        refreshAbortRef.current?.abort();
        const ctrl = new AbortController();
        refreshAbortRef.current = ctrl;
        Promise.allSettled([
          getWeakConcepts({ signal: ctrl.signal }),
          getReviewMastery({ signal: ctrl.signal }),
        ]).then(([weakRes, masteryRes]) => {
          if (ctrl.signal.aborted) return;
          if (weakRes.status === 'fulfilled') {
            setWeakConcepts(weakRes.value.concepts);
            setNewConcepts(weakRes.value.new_concepts ?? []);
          }
          if (masteryRes.status === 'fulfilled') {
            setMastery(masteryRes.value.mastery);
          }
        });
      }
    },
    [rate, selectedChoiceLabel],
  );

  const handleQueueState = useCallback(
    async (state: ReviewQueueState) => {
      const card = useReviewStore.getState().currentCard();
      if (!card || queueStateBusyRef.current) return;
      queueStateBusyRef.current = true;
      queueStateAbortRef.current?.abort();
      const ctrl = new AbortController();
      queueStateAbortRef.current = ctrl;
      setQueueStateBusy(true);
      setQueueStateMessage(
        state === 'suspended'
          ? t('Review.card_suspending')
          : t('Review.card_archiving'),
      );
      try {
        await updateReviewQueueState(
          { card_id: card.card_id, state },
          { signal: ctrl.signal },
        );
        if (ctrl.signal.aborted) return;
        setQueueStateMessage(
          state === 'suspended'
            ? t('Review.card_suspended')
            : t('Review.card_archived'),
        );
        await useReviewStore.getState().loadQueue();
      } catch (e) {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setQueueStateMessage(t('Review.error_unknown'));
      } finally {
        if (!ctrl.signal.aborted) {
          queueStateBusyRef.current = false;
          setQueueStateBusy(false);
        }
      }
    },
    [t],
  );

  useEffect(() => {
    return () => {
      queueStateBusyRef.current = false;
      queueStateAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.isComposing) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement;
      const tag = target?.tagName;
      // Allow SRS rating shortcuts (1-4) when focused on a rating button.
      // Allow A-D shortcuts when focused on a choice button.
      const isSrsBtn = tag === 'BUTTON' && target.classList.contains('srs-btn');
      const isSrsKey = e.key === '1' || e.key === '2' || e.key === '3' || e.key === '4';
      const isChoiceBtn = tag === 'BUTTON' && target.classList.contains('review__choice');
      const isChoiceKey = !!CHOICE_KEY_LABELS[e.key.toLowerCase()];
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        tag === 'SELECT' ||
        (tag === 'BUTTON' && !(isSrsBtn && isSrsKey) && !(isChoiceBtn && isChoiceKey)) ||
        tag === 'A' ||
        target?.isContentEditable
      ) return;
      const card = useReviewStore.getState().currentCard();
      const isChoice = card ? isChoiceCard(card) : false;
      // Choice cards use answer_mode='multiple_choice'; question phase shows
      // ABCD buttons. After a selection (selectedChoiceLabel != null) the card
      // is "revealed" and 1-4 rating shortcuts apply.
      const choiceRevealed = isChoice && selectedChoiceLabel !== null;
      const isRevealed = isChoice ? choiceRevealed : flipped;
      if (!isRevealed) {
        if (isChoice && card) {
          const label = CHOICE_KEY_LABELS[e.key.toLowerCase()];
          if (label) {
            const choice = card.choices?.find((c) => c.label === label);
            if (choice) {
              e.preventDefault();
              setSelectedChoiceLabel(label);
              return;
            }
          }
          return;
        }
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          setFlipped(true);
        }
        return;
      }
      // Wrong-answer guard for choice cards: Good and Easy are disabled and
      // the shortcuts should not bypass that. Test the same gate the buttons
      // use.
      if (isChoice && card) {
        const correctChoice = card.choices?.find((c) => c.is_correct);
        const isAnswerCorrect =
          correctChoice !== undefined && correctChoice.label === selectedChoiceLabel;
        if (!isAnswerCorrect && (e.key === '3' || e.key === '4')) {
          return;
        }
      }
      if (e.key === '1') void handleRate('wrong');
      else if (e.key === '2') void handleRate('hard');
      else if (e.key === '3') void handleRate('good');
      else if (e.key === '4') void handleRate('easy');
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [flipped, handleRate, selectedChoiceLabel]);

  const total = cards.length;
  const card = currentCard();
  const done = currentIndex >= total;
  const sessionReviewedCount = countRatings(sessionRatings);
  const confidentCount = sessionRatings.good + sessionRatings.easy;
  const followupCount = sessionRatings.wrong + sessionRatings.hard;
  const choiceCard = useMemo(
    () => (card && isChoiceCard(card) ? card : null),
    [card],
  );
  const correctChoice = useMemo<ReviewChoice | null>(() => {
    if (!choiceCard) return null;
    return choiceCard.choices.find((c) => c.is_correct) ?? null;
  }, [choiceCard]);

  // --- Loading skeleton (preserves 2-column layout) ---
  if (loading) {
    return (
      <AppShell>
        <div className="page active review" data-page="review" role="status" aria-label={t('A11y.loading')}>
          <div className="review__head">
            <div className="review__head-left">
              <Skeleton variant="text" width="180px" />
              <Skeleton variant="text" width="300px" height="2em" />
            </div>
          </div>
          <div className="review__grid">
            <div>
              <Skeleton variant="card" height="300px" />
              <div className="srs-buttons" style={{ marginTop: 14 }}>
                <Skeleton variant="row" />
                <Skeleton variant="row" />
                <Skeleton variant="row" />
                <Skeleton variant="row" />
              </div>
            </div>
            <aside aria-label={t('Review.sidebar_label')}>
              <Skeleton variant="card" height="120px" />
            </aside>
          </div>
        </div>
      </AppShell>
    );
  }

  // --- Error state (queue load error from store) ---
  if (error) {
    const errorKind = classifyError(error);
    return (
      <AppShell>
        <div className="page active review" data-page="review">
          <div className="review__head">
            <div className="review__head-left">
              <h1 className="review__title">{t('Review.title')}</h1>
            </div>
          </div>
          <div role="alert" aria-live="assertive" className="review__error">
            {errorKind === 'network' && (
              <>
                <p className="review__error-message">{t('Review.error_network')}</p>
                <p className="review__error-hint">{t('Review.error_network_hint')}</p>
                <button
                  type="button"
                  className="review__error-action"
                  onClick={() => void loadQueue()}
                >
                  {t('Review.error_retry')}
                </button>
              </>
            )}
            {errorKind === 'auth' && (
              <>
                <p className="review__error-message">{t('Review.error_auth')}</p>
                <p className="review__error-hint">{t('Review.error_auth_hint')}</p>
                <button
                  type="button"
                  className="review__error-action"
                  onClick={() => window.location.reload()}
                >
                  {t('Review.error_refresh')}
                </button>
              </>
            )}
            {errorKind === 'unknown' && (
              <>
                <p className="review__error-message">{t('Review.error_unknown')}</p>
                <button
                  type="button"
                  className="review__error-action"
                  onClick={() => void loadQueue()}
                >
                  {t('Review.error_retry')}
                </button>
              </>
            )}
          </div>
        </div>
      </AppShell>
    );
  }
  const isAnswerCorrect =
    choiceCard !== null &&
    correctChoice !== null &&
    selectedChoiceLabel === correctChoice.label;
  const choiceRevealed = choiceCard !== null && selectedChoiceLabel !== null;
  // For choice cards: the rating block (Easy/Good/Hard/Wrong) replaces flip.
  // Easy/Good are disabled when the user picked wrong (per plan: keep manual
  // rating, force at least Hard or Wrong on incorrect selections).
  const ratingsBlocked = choiceCard !== null && !isAnswerCorrect;

  // --- Empty queue ---
  if (total === 0) {
    return (
      <AppShell>
        <div className="page active review" data-page="review">
          <div className="review__head">
            <div className="review__head-left">
              <div className="review__eyebrow">{t('Review.eyebrow')}</div>
              <h1 className="review__title">{t('Review.title')}</h1>
            </div>
          </div>
          <div className="review__empty">
            <div className="review__empty-icon" aria-hidden="true">✓</div>
            <p>{t('Review.queue_empty')}</p>
            <p className="review__empty-hint">{t('Review.queue_empty_hint')}</p>
            <a href="#/" className="review__empty-cta">{t('Review.queue_empty_cta')}</a>
          </div>
        </div>
      </AppShell>
    );
  }

  // --- Session complete ---
  if (done) {
    return (
      <AppShell>
        <div className="page active review" data-page="review">
          <div className="review__head">
            <div className="review__head-left">
              <div className="review__eyebrow">{t('Review.eyebrow')}</div>
              <h1 className="review__title">{t('Review.title')}</h1>
            </div>
          </div>
          <div className="review__complete">
            <div className="review__complete-icon" aria-hidden="true">&#127881;</div>
            <h2>{t('Review.complete')}</h2>
            <p className="review__complete-count">
              {t('Review.complete_hint', { count: total })}
            </p>
            <div
              className="review__complete-stats"
              aria-label={t('Review.complete_stats_title')}
            >
              <div className="review__complete-stat">
                <span>{t('Review.stat_completed')}</span>
                <strong>{sessionReviewedCount || total}</strong>
              </div>
              <div className="review__complete-stat">
                <span>{t('Review.stat_confident')}</span>
                <strong>{confidentCount}</strong>
              </div>
              <div className="review__complete-stat">
                <span>{t('Review.stat_followup')}</span>
                <strong>{followupCount}</strong>
              </div>
            </div>
            <div
              className="review__rating-summary"
              aria-label={t('Review.rating_summary_title')}
            >
              <h2>{t('Review.rating_summary_title')}</h2>
              {REVIEW_RATING_ORDER.map((answer) => (
                <div key={answer} className="review__rating-row">
                  <span>{t(REVIEW_RATING_LABEL_KEYS[answer])}</span>
                  <strong>{sessionRatings[answer]}</strong>
                </div>
              ))}
            </div>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div className="page active review" data-page="review">
        {/* Header */}
        <div className="review__head">
          <div className="review__head-left">
            <div className="review__eyebrow">{t('Review.eyebrow')}</div>
            <h1 className="review__title">
              {t('Review.title')} ·{' '}
              <span className="mono">
                {t('Review.progress', {
                  current: currentIndex + 1,
                  total,
                })}
              </span>
            </h1>
            <div className="review__sub">
              {t('Review.sub_forgetting')}
              {weakConcepts.length > 0 && (
                <span className="review__sub-risk">
                  {' '}{t('Review.sub_risk_count', { count: weakConcepts.length })}
                </span>
              )}
            </div>
          </div>
          <div className="review__head-right">
            <span className="review__chip">{t('Review.chip_cards', { count: total })}</span>
            <span className="review__chip review__chip--active">
              {t('Review.chip_fsrs')} <InfoHint label={t('Review.fsrs_hint')} />
            </span>
            {weakConcepts.length > 0 && (
              <span className="review__chip review__chip--warn">
                {t('Review.chip_at_risk', { count: weakConcepts.length })}
              </span>
            )}
          </div>
        </div>

        {(heatmapCells.length > 0 || mastery.length > 0 || weakConcepts.length > 0 || newConcepts.length > 0) && (
          <section className="review__summary">
            <button
              type="button"
              className="review__summary-toggle"
              onClick={() => setSummaryOpen(!summaryOpen)}
              aria-expanded={summaryOpen}
            >
              <span>{t('Review.summary_title')}</span>
              <span aria-hidden="true">{summaryOpen ? '−' : '+'}</span>
            </button>
            {summaryOpen && (
              <div className="review__summary-body">
                {heatmapCells.length > 0 && (
                  <div className="review__summary-card">
                    <CalendarHeatmap cells={heatmapCells} title={t('Review.heatmap_title')} />
                  </div>
                )}
                {mastery.length > 0 && (
                  <div className="review__summary-card">
                    <h2 className="review__summary-card-title">
                      {t('Review.mastery_title')} <InfoHint label={t('Review.mastery_hint')} />
                    </h2>
                    <div className="review__mastery-list">
                      {mastery.slice(0, 10).map((m) => {
                        const pct = Math.min(100, ((m.avg_rating ?? 0) / 4) * 100);
                        const tier = pct >= 70 ? '' : pct >= 40 ? ' mastery-bar__fill--warn' : ' mastery-bar__fill--danger';
                        return (
                          <div key={m.concept} className="review__mastery-row">
                            <span className="review__mastery-label">{m.concept}</span>
                            <div
                              className="mastery-bar"
                              role="progressbar"
                              aria-valuenow={Math.round(pct)}
                              aria-valuemin={0}
                              aria-valuemax={100}
                              aria-label={m.concept}
                            >
                              <span
                                className={`mastery-bar__fill${tier}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span className="review__mastery-count">{m.review_count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                {weakConcepts.length > 0 && (
                  <div className="review__summary-card">
                    <h2 className="review__summary-card-title">
                      {t('Review.weak_title')} <InfoHint label={t('Review.weak_stability_hint')} />
                    </h2>
                    <p className="review__summary-subtitle">{t('Review.weak_subtitle')}</p>
                    <ul className="review__weak-list">
                      {weakConcepts.slice(0, 8).map((w) => (
                        <li key={w.card_id} className="review__weak-item">
                          <span>{w.concept}</span>
                          <span className="review__weak-meta">
                            {t('Review.weak_stability')} {w.stability.toFixed(1)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {newConcepts.length > 0 && (
                  <div className="review__summary-card">
                    <h2 className="review__summary-card-title">{t('Review.new_concepts_title')}</h2>
                    <p className="review__summary-subtitle">{t('Review.new_concepts_subtitle')}</p>
                    <ul className="review__weak-list">
                      {newConcepts.slice(0, 8).map((w) => (
                        <li key={w.card_id} className="review__weak-item">
                          <span>{w.concept}</span>
                          <span className="review__weak-meta review__weak-meta--new">
                            {t('Review.stability_new')}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* Main content */}
        <div className="review__grid">
          {/* Left: Flashcard + buttons */}
          <div>
            <div className="flashcard">
              {card!.scaffolding_level && (
                <div className="flashcard__tag">
                  <span className="review__chip">
                    L{card!.scaffolding_level}
                  </span>
                </div>
              )}
              <div className="flashcard__concept">
                {t('Review.card_concept')} · {card!.concept}
                <span className="flashcard__source-badge">{t('Review.card_ai_source')}</span>
              </div>
              <div className="flashcard__queue-actions">
                <button
                  type="button"
                  className="flashcard__queue-action"
                  onClick={() => void handleQueueState('suspended')}
                  disabled={queueStateBusy}
                >
                  {t('Review.suspend_card')}
                </button>
                <button
                  type="button"
                  className="flashcard__queue-action"
                  onClick={() => void handleQueueState('archived')}
                  disabled={queueStateBusy}
                >
                  {t('Review.archive_card')}
                </button>
                {queueStateMessage && (
                  <span
                    className="flashcard__queue-status"
                    role="status"
                    aria-live="polite"
                    aria-busy={queueStateBusy}
                  >
                    {queueStateMessage}
                  </span>
                )}
              </div>
              <div className="flashcard__front">
                {card!.question?.trim() || (
                  <>
                    {card!.display_path}
                    {card!.symbol && <> · <span className="mono">{card!.symbol}</span></>}
                  </>
                )}
              </div>
              {/* Choice mode: ABCD buttons. Question phase shows interactive
                  options; reveal phase highlights correct/wrong. */}
              {choiceCard && (
                <div className="review__choices-block">
                  <p className="review__choice-prompt">{t('Review.select_prompt')}</p>
                  <div
                    className="review__choices"
                    role="radiogroup"
                    aria-label={t('Review.select_prompt')}
                  >
                    {choiceCard.choices.map((choice) => {
                      const isSelected = selectedChoiceLabel === choice.label;
                      const isCorrect = choice.is_correct;
                      const isWrongSelected = isSelected && !isCorrect;
                      const stateClass = choiceRevealed
                        ? isCorrect
                          ? ' review__choice--correct'
                          : isWrongSelected
                            ? ' review__choice--wrong'
                            : ''
                        : '';
                      const ariaLabel = t('Review.choice_a11y', {
                        label: choice.label,
                        text: choice.text,
                      });
                      return (
                        <button
                          key={choice.label}
                          type="button"
                          role="radio"
                          aria-checked={isSelected}
                          aria-label={ariaLabel}
                          className={`review__choice${
                            isSelected ? ' review__choice--selected' : ''
                          }${choiceRevealed ? ' review__choice--disabled' : ''}${stateClass}`}
                          disabled={choiceRevealed}
                          onClick={() => {
                            if (choiceRevealed) return;
                            setSelectedChoiceLabel(choice.label);
                          }}
                        >
                          <span className="review__choice-letter" aria-hidden="true">
                            {choice.label}
                          </span>
                          <span className="review__choice-content">
                            <span className="review__choice-text">{choice.text}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <div
                className="flashcard__back"
                hidden={choiceCard ? !choiceRevealed : !flipped}
                aria-live="polite"
              >
                <div className="review__eyebrow u-mb-2">
                  {t('Review.answer_label')}
                </div>
                {choiceCard && correctChoice ? (
                  <>
                    <p
                      className={`review__result ${
                        isAnswerCorrect ? 'review__result--correct' : 'review__result--wrong'
                      }`}
                    >
                      {isAnswerCorrect ? t('Quiz.correct') : t('Quiz.wrong')}
                    </p>
                    <div className="flashcard__answer">
                      <span className="review__correct-label">
                        {t('Quiz.correct_answer_is')}
                      </span>{' '}
                      {correctChoice.label}. {correctChoice.text}
                    </div>
                  </>
                ) : card!.answer?.trim() ? (
                  <div className="flashcard__answer">{card!.answer}</div>
                ) : (
                  <div className="flashcard__meta">
                    {card!.source_ref && (
                      <>
                        {t('Review.card_source')}: <span className="mono">{card!.source_ref}</span>
                        {' · '}
                      </>
                    )}
                    {t('Review.scaffolding_level', { level: card!.scaffolding_level })}
                  </div>
                )}
                <div className="flashcard__meta">
                  {card!.display_path}
                  {card!.symbol && <> · <span className="mono">{card!.symbol}</span></>}
                </div>
                {card!.display_path && (
                  <a
                    className="flashcard__evidence"
                    href={`/#/run/${encodeURIComponent(card!.run_id)}/lesson`}
                    data-testid="flashcard-evidence-link"
                  >
                    <span className="flashcard__evidence-label">{t('Review.evidence_label')}</span>
                    <span className="flashcard__evidence-path">
                      {card!.display_path}
                    </span>
                  </a>
                )}
              </div>
            </div>

            {/* Action area:
                - Choice cards: question phase shows nothing here (the ABCD
                  buttons inside the flashcard ARE the action). Reveal phase
                  shows SRS rating buttons with Easy/Good disabled if the
                  user picked wrong.
                - Open cards: keep flip-then-rate flow unchanged. */}
            {choiceCard ? (
              choiceRevealed ? (
                <div className="srs-buttons">
                  <button
                    ref={firstRatingRef}
                    type="button"
                    className="srs-btn"
                    onClick={() => void handleRate('wrong')}
                    disabled={rating}
                    aria-label={t('Review.srs_aria_wrong')}
                    aria-describedby="srs-interval-wrong"
                  >
                    <div className="srs-btn__label">{t('Review.rating_wrong')}</div>
                    <div className="srs-btn__interval" id="srs-interval-wrong">{t('Review.interval_again')}</div>
                    <span className="srs-btn__kbd">1</span>
                  </button>
                  <button
                    type="button"
                    className="srs-btn"
                    onClick={() => void handleRate('hard')}
                    disabled={rating}
                    aria-label={t('Review.srs_aria_hard')}
                    aria-describedby="srs-interval-hard"
                  >
                    <div className="srs-btn__label">{t('Review.rating_hard')}</div>
                    <div className="srs-btn__interval" id="srs-interval-hard">{t('Review.interval_hard')}</div>
                    <span className="srs-btn__kbd">2</span>
                  </button>
                  <button
                    type="button"
                    className="srs-btn srs-btn--good"
                    onClick={() => void handleRate('good')}
                    disabled={rating || ratingsBlocked}
                    aria-label={t('Review.srs_aria_good')}
                    aria-describedby="srs-interval-good"
                  >
                    <div className="srs-btn__label">{t('Review.rating_good')}</div>
                    <div className="srs-btn__interval" id="srs-interval-good">{t('Review.interval_good')}</div>
                    <span className="srs-btn__kbd">3</span>
                  </button>
                  <button
                    type="button"
                    className="srs-btn srs-btn--easy"
                    onClick={() => void handleRate('easy')}
                    disabled={rating || ratingsBlocked}
                    aria-label={t('Review.srs_aria_easy')}
                    aria-describedby="srs-interval-easy"
                  >
                    <div className="srs-btn__label">{t('Review.rating_easy')}</div>
                    <div className="srs-btn__interval" id="srs-interval-easy">{t('Review.interval_easy')}</div>
                    <span className="srs-btn__kbd">4</span>
                  </button>
                </div>
              ) : null
            ) : !flipped ? (
              <button
                ref={flipBtnRef}
                type="button"
                className="flashcard__flip-btn"
                onClick={() => setFlipped(true)}
              >
                {t('Review.flip')} <span className="srs-btn__kbd">Space</span>
              </button>
            ) : (
              <div className="srs-buttons">
                <button
                  ref={firstRatingRef}
                  type="button"
                  className="srs-btn"
                  onClick={() => void handleRate('wrong')}
                  disabled={rating}
                  aria-label={t('Review.srs_aria_wrong')}
                  aria-describedby="srs-interval-wrong"
                >
                  <div className="srs-btn__label">{t('Review.rating_wrong')}</div>
                  <div className="srs-btn__interval" id="srs-interval-wrong">{t('Review.interval_again')}</div>
                  <span className="srs-btn__kbd">1</span>
                </button>
                <button
                  type="button"
                  className="srs-btn"
                  onClick={() => void handleRate('hard')}
                  disabled={rating}
                  aria-label={t('Review.srs_aria_hard')}
                  aria-describedby="srs-interval-hard"
                >
                  <div className="srs-btn__label">{t('Review.rating_hard')}</div>
                  <div className="srs-btn__interval" id="srs-interval-hard">{t('Review.interval_hard')}</div>
                  <span className="srs-btn__kbd">2</span>
                </button>
                <button
                  type="button"
                  className="srs-btn srs-btn--good"
                  onClick={() => void handleRate('good')}
                  disabled={rating}
                  aria-label={t('Review.srs_aria_good')}
                  aria-describedby="srs-interval-good"
                >
                  <div className="srs-btn__label">{t('Review.rating_good')}</div>
                  <div className="srs-btn__interval" id="srs-interval-good">{t('Review.interval_good')}</div>
                  <span className="srs-btn__kbd">3</span>
                </button>
                <button
                  type="button"
                  className="srs-btn srs-btn--easy"
                  onClick={() => void handleRate('easy')}
                  disabled={rating}
                  aria-label={t('Review.srs_aria_easy')}
                  aria-describedby="srs-interval-easy"
                >
                  <div className="srs-btn__label">{t('Review.rating_easy')}</div>
                  <div className="srs-btn__interval" id="srs-interval-easy">{t('Review.interval_easy')}</div>
                  <span className="srs-btn__kbd">4</span>
                </button>
              </div>
            )}
          </div>

          {/* Right: Sidebar */}
          <aside aria-label={t('Review.sidebar_label')}>
            {heatmapCells.length > 0 && (
              <div className="review__sidebar-card review__sidebar-card--warm">
                <CalendarHeatmap cells={heatmapCells} title={t('Review.heatmap_sidebar_title')} />
              </div>
            )}

            {mastery.length > 0 && (
              <div className="review__sidebar-card review__sidebar-card--warm">
                <div className="review__sidebar-header">
                  <h2>
                    {t('Review.mastery_title')} <InfoHint label={t('Review.mastery_hint')} />
                  </h2>
                  <span className="review__sidebar-meta">{t('Review.mastery_top')}</span>
                </div>
                <div className="review__sidebar-body">
                  <div className="review__mastery-list">
                    {mastery.slice(0, 6).map((m) => {
                      const pct = Math.min(100, ((m.avg_rating ?? 0) / 4) * 100);
                      const tier = pct >= 70 ? '' : pct >= 40 ? ' mastery-bar__fill--warn' : ' mastery-bar__fill--danger';
                      return (
                        <div key={m.concept} className="review__mastery-row">
                          <span className="review__mastery-label">{m.concept}</span>
                          <div
                            className="mastery-bar"
                            role="progressbar"
                            aria-valuenow={Math.round(pct)}
                            aria-valuemin={0}
                            aria-valuemax={100}
                            aria-label={m.concept}
                          >
                            <span
                              className={`mastery-bar__fill${tier}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="review__mastery-count">{m.review_count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            <div className="review__sidebar-card">
              <div className="review__sidebar-header">
                <h2>{t('Review.card_concept')}</h2>
                <span className="review__sidebar-meta">{card!.concept}</span>
              </div>
              <div className="review__sidebar-body">
                <div className="u-muted-xs">
                  {card!.display_path}
                  {card!.source_ref && (
                    <div className="u-mt-1">
                      {t('Review.card_source')}: <span className="mono">{card!.source_ref}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Session progress card */}
            <div className="review__sidebar-card">
              <div className="review__sidebar-header">
                <h2>{t('Review.sidebar_progress')}</h2>
                <span className="review__sidebar-meta">
                  {currentIndex}/{total}
                </span>
              </div>
              <div className="review__sidebar-body">
                <div
                  className="mastery-bar"
                  data-testid="review-progress-bar"
                  role="progressbar"
                  aria-valuenow={currentIndex}
                  aria-valuemin={0}
                  aria-valuemax={total}
                  aria-label={t('Review.progress_hint')}
                >
                  <span
                    className="mastery-bar__fill"
                    style={{ width: `${total > 0 ? (currentIndex / total) * 100 : 0}%` }}
                  />
                </div>
              </div>
            </div>

            <Suspense fallback={null}>
              <GraphifyCard compact />
            </Suspense>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}
