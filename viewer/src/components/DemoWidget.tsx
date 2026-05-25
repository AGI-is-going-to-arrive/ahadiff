import { useState, useEffect } from 'react';
import type { TranslateFn } from '../i18n/useTranslation';
import { getDemoLearnPreview, type DemoLearnPreviewResponse } from '../api/demo';
import Skeleton, { SkeletonGroup } from './Skeleton';
import ClaimBadge from './ClaimBadge';
import './DemoWidget.css';

const demoCache = new Map<string, DemoLearnPreviewResponse>();
const demoInFlight = new Map<string, Promise<DemoLearnPreviewResponse>>();

function loadDemoPreview(locale: string): Promise<DemoLearnPreviewResponse> {
  const cached = demoCache.get(locale);
  if (cached) return Promise.resolve(cached);

  const inFlight = demoInFlight.get(locale);
  if (inFlight) return inFlight;

  const request = getDemoLearnPreview({ headers: { 'accept-language': locale } })
    .then((res) => {
      demoCache.set(locale, res);
      return res;
    })
    .finally(() => {
      demoInFlight.delete(locale);
    });
  demoInFlight.set(locale, request);
  return request;
}

export default function DemoWidget({ t, locale }: { t: TranslateFn; locale: string }) {
  const [data, setData] = useState<DemoLearnPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    loadDemoPreview(locale)
      .then((res) => {
        if (!cancelled) {
          setData(res);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('Settings_page.integration_demo_error'));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [locale, retryCount, t]);

  if (loading) {
    return (
      <div
        className="demo-widget demo-widget--loading"
        role="status"
        aria-busy={loading}
        aria-live="polite"
      >
        <span className="sr-only">{t('A11y.loading')}</span>
        <Skeleton variant="text" width="100px" />
        <SkeletonGroup count={3} variant="row" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="demo-widget demo-widget--error" role="alert">
        <p>{error ?? t('Settings_page.integration_demo_error')}</p>
        <button
          type="button"
          className="retry-btn"
          onClick={() => {
            demoCache.delete(locale);
            demoInFlight.delete(locale);
            setRetryCount(c => c + 1);
          }}
        >
          {t('Settings_page.integration_demo_retry')}
        </button>
      </div>
    );
  }

  return (
    <div className="demo-widget">
      <h3 className="demo-widget__title">{t('Settings_page.integration_demo_title')}</h3>

      <div className="demo-widget__section">
        <h4 className="demo-widget__heading">{t('Settings_page.integration_demo_sample_diff')}</h4>
        <pre className="demo-widget__diff"><code>{data.sample_diff}</code></pre>
      </div>

      <div className="demo-widget__section">
        <h4 className="demo-widget__heading">{t('Settings_page.integration_demo_claims')}</h4>
        <ul className="demo-widget__claims">
          {data.claims.map((claim, idx) => (
            <li key={idx} className="demo-widget__claim">
              <ClaimBadge verdict={claim.status} />
              <span className="demo-widget__claim-text">{claim.text}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="demo-widget__section">
        <h4 className="demo-widget__heading">{t('Settings_page.integration_demo_lesson')}</h4>
        <div className="demo-widget__lesson">{data.lesson_snippet}</div>
      </div>

      <div className="demo-widget__section">
        <h4 className="demo-widget__heading">{t('Settings_page.integration_demo_quiz')}</h4>
        <div className="demo-widget__quiz">
          <p className="demo-widget__quiz-q">{data.quiz.question}</p>
          <ul className="demo-widget__quiz-choices">
            {data.quiz.choices.map((choice, idx) => (
              <li
                key={idx}
                className={
                  `demo-widget__quiz-choice ${
                    idx === data.quiz.answer_index ? 'demo-widget__quiz-choice--correct' : ''
                  }`
                }
              >
                {choice}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
