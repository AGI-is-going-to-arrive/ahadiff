import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import AppShell from '../components/AppShell';
import Skeleton from '../components/Skeleton';
import { useReviewStore } from '../state/review-store';
import { useTranslation } from '../i18n/useTranslation';
import type { ReviewAnswer } from '../api/types';
import '../components/Review.css';

const GraphifyCard = lazy(() => import('../components/GraphifyCard'));

type RatingSummary = Record<ReviewAnswer, number>;

const REVIEW_RATING_ORDER: ReviewAnswer[] = ['wrong', 'hard', 'good', 'easy'];
const REVIEW_RATING_LABEL_KEYS: Record<ReviewAnswer, string> = {
  wrong: 'Review.rating_wrong',
  hard: 'Review.rating_hard',
  good: 'Review.rating_good',
  easy: 'Review.rating_easy',
};

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
  const remaining = useReviewStore((s) => s.remaining);

  const [flipped, setFlipped] = useState(false);
  const [sessionRatings, setSessionRatings] = useState<RatingSummary>(() => createRatingSummary());
  const abortRef = useRef<AbortController | null>(null);
  const flipBtnRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    void loadQueue({ signal: controller.signal });
    return () => controller.abort();
  }, [loadQueue]);

  useEffect(() => {
    setFlipped(false);
    requestAnimationFrame(() => flipBtnRef.current?.focus());
  }, [currentIndex]);

  useEffect(() => {
    setSessionRatings(createRatingSummary());
  }, [cards]);

  const handleRate = useCallback(
    async (answer: ReviewAnswer) => {
      const beforeIndex = useReviewStore.getState().currentIndex;
      await rate(answer);
      const afterIndex = useReviewStore.getState().currentIndex;
      if (afterIndex > beforeIndex) {
        setSessionRatings((prev) => ({
          ...prev,
          [answer]: prev[answer] + 1,
        }));
      }
    },
    [rate],
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        tag === 'SELECT' ||
        tag === 'BUTTON' ||
        tag === 'A' ||
        (e.target as HTMLElement)?.isContentEditable
      ) return;
      if (!flipped) {
        if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          setFlipped(true);
        }
        return;
      }
      if (e.key === '1') void handleRate('wrong');
      else if (e.key === '2') void handleRate('hard');
      else if (e.key === '3') void handleRate('good');
      else if (e.key === '4') void handleRate('easy');
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [flipped, handleRate]);

  // --- Loading skeleton (preserves 2-column layout) ---
  if (loading) {
    return (
      <AppShell>
        <div className="review" role="status" aria-label={t('A11y.loading')}>
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
              </div>
            </div>
            <aside>
              <Skeleton variant="card" height="120px" />
            </aside>
          </div>
        </div>
      </AppShell>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <AppShell>
        <div className="review">
          <div className="review__head">
            <div className="review__head-left">
              <h1 className="review__title">{t('Review.title')}</h1>
            </div>
          </div>
          <div role="alert" className="dashboard__error">
            {t('Error.fetch_failed', { resource: t('Review.title') })}
            <button
              type="button"
              className="retry-btn"
              onClick={() => void loadQueue()}
            >
              {t('Error.retry')}
            </button>
          </div>
        </div>
      </AppShell>
    );
  }

  const total = cards.length;
  const card = currentCard();
  const done = currentIndex >= total;
  const sessionReviewedCount = countRatings(sessionRatings);
  const confidentCount = sessionRatings.good + sessionRatings.easy;
  const followupCount = sessionRatings.wrong + sessionRatings.hard;

  // --- Empty queue ---
  if (total === 0) {
    return (
      <AppShell>
        <div className="review">
          <div className="review__head">
            <div className="review__head-left">
              <div className="review__eyebrow">{t('Review.eyebrow')}</div>
              <h1 className="review__title">{t('Review.title')}</h1>
            </div>
          </div>
          <div className="review__empty">
            <div className="review__empty-icon" aria-hidden="true">✓</div>
            <p>{t('Review.queue_empty')}</p>
          </div>
        </div>
      </AppShell>
    );
  }

  // --- Session complete ---
  if (done) {
    return (
      <AppShell>
        <div className="review">
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
      <div className="review">
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
              {remaining() === 1
                ? t('Review.card_remaining', { count: remaining() })
                : t('Review.cards_remaining', { count: remaining() })}
            </div>
          </div>
          <div className="review__head-right">
            <span className="review__chip">{t('Review.chip_cards', { count: total })}</span>
            <span className="review__chip review__chip--active">{t('Review.chip_fsrs')}</span>
          </div>
        </div>

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
              </div>
              <div className="flashcard__front">
                {card!.display_path}
                {card!.symbol && <> · <span className="mono">{card!.symbol}</span></>}
              </div>
              <div
                className="flashcard__back"
                hidden={!flipped}
                aria-live="polite"
              >
                <div className="review__eyebrow u-mb-2">
                  {t('Review.answer_label')}
                </div>
                <div className="flashcard__meta">
                  {card!.source_ref && (
                    <>
                      {t('Review.card_source')}: <span className="mono">{card!.source_ref}</span>
                      {' · '}
                    </>
                  )}
                  {t('Review.scaffolding_level', { level: card!.scaffolding_level })}
                </div>
              </div>
            </div>

            {!flipped ? (
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
                  type="button"
                  className="srs-btn"
                  onClick={() => void handleRate('wrong')}
                  disabled={rating}
                >
                  <div className="srs-btn__label">{t('Review.rating_wrong')}</div>
                  <div className="srs-btn__interval">{t('Review.interval_again')}</div>
                  <span className="srs-btn__kbd">1</span>
                </button>
                <button
                  type="button"
                  className="srs-btn"
                  onClick={() => void handleRate('hard')}
                  disabled={rating}
                >
                  <div className="srs-btn__label">{t('Review.rating_hard')}</div>
                  <div className="srs-btn__interval">{t('Review.interval_hard')}</div>
                  <span className="srs-btn__kbd">2</span>
                </button>
                <button
                  type="button"
                  className="srs-btn srs-btn--good"
                  onClick={() => void handleRate('good')}
                  disabled={rating}
                >
                  <div className="srs-btn__label">{t('Review.rating_good')}</div>
                  <div className="srs-btn__interval">{t('Review.interval_good')}</div>
                  <span className="srs-btn__kbd">3</span>
                </button>
                <button
                  type="button"
                  className="srs-btn srs-btn--easy"
                  onClick={() => void handleRate('easy')}
                  disabled={rating}
                >
                  <div className="srs-btn__label">{t('Review.rating_easy')}</div>
                  <div className="srs-btn__interval">{t('Review.interval_easy')}</div>
                  <span className="srs-btn__kbd">4</span>
                </button>
              </div>
            )}
          </div>

          {/* Right: Sidebar */}
          <aside>
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
                      ref: <span className="mono">{card!.source_ref}</span>
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
                <div className="mastery-bar">
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
