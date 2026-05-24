import { useState, useEffect, useRef } from 'react';
import type { MessageKey, TranslateFn } from '../i18n/useTranslation';
import { getDemoLearnPreview, type DemoLearnPreviewResponse } from '../api/demo';
import Skeleton, { SkeletonGroup } from './Skeleton';
import './DemoWidget.css';

const demoCache = new Map<string, DemoLearnPreviewResponse>();
const CLAIM_STATUS_KEYS = {
  verified: 'Claim.verified',
  weak: 'Claim.weak',
  not_proven: 'Claim.not_proven',
} as const satisfies Record<DemoLearnPreviewResponse['claims'][number]['status'], MessageKey>;

export default function DemoWidget({ t, locale }: { t: TranslateFn; locale: string }) {
  const [data, setData] = useState<DemoLearnPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retryCount, setRetryCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (retryCount > 0) {
      demoCache.delete(locale);
    }
    const cached = demoCache.get(locale);
    if (cached) {
      setData(cached);
      setLoading(false);
      setError(null);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);

    getDemoLearnPreview({ headers: { 'accept-language': locale }, signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted) {
          demoCache.set(locale, res);
          setData(res);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setError(t('Settings_page.integration_demo_error'));
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [locale, retryCount, t]);

  if (loading) {
    return (
      <div className="demo-widget demo-widget--loading" role="status" aria-busy={loading}>
        <Skeleton variant="text" width="100px" />
        <SkeletonGroup count={3} variant="row" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="demo-widget demo-widget--error" role="alert">
        <p>{error ?? t('Settings_page.integration_demo_error')}</p>
        <button type="button" className="retry-btn" onClick={() => setRetryCount(c => c + 1)}>
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
            <li key={idx} className={`demo-widget__claim demo-widget__claim--${claim.status}`}>
              <span className="demo-widget__claim-status">
                {t(CLAIM_STATUS_KEYS[claim.status])}
              </span>
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
