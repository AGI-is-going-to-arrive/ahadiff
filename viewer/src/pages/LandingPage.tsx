import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../i18n/useTranslation';
import '../components/Landing.css';

const SAMPLE_DIFF = `diff --git a/demo.py b/demo.py
--- a/demo.py
+++ b/demo.py
@@ -1,3 +1,4 @@
 def hello():
-    return "world"
+    return "AhaDiff"
+    # learn-from-diff`;

const SAMPLE_LESSON = `## What Changed

The return value was updated from \`"world"\` to \`"AhaDiff"\`,
and a \`# learn-from-diff\` marker was added.

**Claim c007** (verified): The function now returns
the project name instead of a generic greeting.
\`demo.py:3\` — evidence: line 3 shows the new return value.`;

const STEP_KEYS = ['01', '02', '03', '04', '05'] as const;
const FEATURE_CARDS = [
  {
    marker: '01',
    titleKey: 'Landing.feature_claims_title',
    descKey: 'Landing.feature_claims_desc',
  },
  {
    marker: '02',
    titleKey: 'Landing.feature_lessons_title',
    descKey: 'Landing.feature_lessons_desc',
  },
  {
    marker: '03',
    titleKey: 'Landing.feature_quiz_title',
    descKey: 'Landing.feature_quiz_desc',
  },
  {
    marker: '04',
    titleKey: 'Landing.feature_memory_title',
    descKey: 'Landing.feature_memory_desc',
  },
] as const;
const TRUST_CARDS = [
  {
    value: '50',
    labelKey: 'Landing.bench_pinned',
    deltaKey: 'Landing.bench_pinned_delta',
    deltaTone: 'neutral',
  },
  {
    value: '0.82',
    labelKey: 'Landing.bench_judge_human',
    deltaKey: 'Landing.bench_judge_human_delta',
    deltaTone: 'up',
  },
  {
    value: '64%',
    labelKey: 'Landing.bench_keep_rate',
    deltaKey: 'Landing.bench_keep_rate_delta',
    deltaTone: 'neutral',
  },
  {
    value: '$0.018',
    labelKey: 'Landing.bench_cost',
    deltaKey: 'Landing.bench_cost_delta',
    deltaTone: 'neutral',
  },
] as const;

const DEMO_TABS = ['raw', 'aha'] as const;
type DemoTabId = typeof DEMO_TABS[number];

export default function LandingPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<DemoTabId>('aha');

  function handleDemoTabKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    const len = DEMO_TABS.length;
    const rtl = getComputedStyle(e.currentTarget).direction === 'rtl';
    const nextKey = rtl ? 'ArrowLeft' : 'ArrowRight';
    const prevKey = rtl ? 'ArrowRight' : 'ArrowLeft';

    let targetIndex = -1;
    switch (e.key) {
      case nextKey:
      case 'ArrowDown':
        targetIndex = (currentIndex + 1) % len;
        break;
      case prevKey:
      case 'ArrowUp':
        targetIndex = (currentIndex - 1 + len) % len;
        break;
      case 'Home':
        targetIndex = 0;
        break;
      case 'End':
        targetIndex = len - 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    setActiveTab(DEMO_TABS[targetIndex]);
    const targetBtn = document.getElementById(`tab-${DEMO_TABS[targetIndex]}`);
    targetBtn?.focus();
  }

  return (
    <main className="landing">
      {/* Hero */}
      <section className="hero">
        <div className="hero-grid">
          <div>
            <div className="hero__eyebrow">{t('Landing.hero_eyebrow')}</div>
            <h1 className="hero__title">
              {t('Landing.hero_title_1')}
              <br />
              <em>{t('Landing.hero_title_2')}</em>
            </h1>
            <div className="hero__en">{t('Brand.tagline')}</div>
            <p className="hero__lead">{t('Landing.hero_lead')}</p>
            <div className="hero-ctas">
              <Link to="/" className="btn-primary">
                {t('Nav.dashboard')} →
              </Link>
              <code className="cli-cmd">pip install ahadiff</code>
            </div>
          </div>

          <div className="hero-demo">
            <div className="hero-demo__tabs" role="tablist" aria-label={t('Landing.tabs_label')}>
              <button
                type="button"
                id="tab-raw"
                role="tab"
                aria-selected={activeTab === 'raw'}
                aria-controls="demo-panel"
                tabIndex={activeTab === 'raw' ? 0 : -1}
                className={`hero-demo__tab${activeTab === 'raw' ? ' hero-demo__tab--active' : ''}`}
                onClick={() => setActiveTab('raw')}
                onKeyDown={e => handleDemoTabKeyDown(e, 0)}
              >
                {t('Landing.tab_raw')}
              </button>
              <button
                type="button"
                id="tab-aha"
                role="tab"
                aria-selected={activeTab === 'aha'}
                aria-controls="demo-panel"
                tabIndex={activeTab === 'aha' ? 0 : -1}
                className={`hero-demo__tab${activeTab === 'aha' ? ' hero-demo__tab--active' : ''}`}
                onClick={() => setActiveTab('aha')}
                onKeyDown={e => handleDemoTabKeyDown(e, 1)}
              >
                {t('Landing.tab_aha')}
              </button>
            </div>
            <div className="hero-demo__content" id="demo-panel" role="tabpanel" aria-labelledby={activeTab === 'raw' ? 'tab-raw' : 'tab-aha'} tabIndex={0}>
              {activeTab === 'raw' ? (
                <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 12, margin: 0 }}>
                  {SAMPLE_DIFF}
                </pre>
              ) : (
                <div className="u-text-sm-relaxed">
                  {SAMPLE_LESSON.split('\n').map((line, i) => (
                    <p key={i} style={{ margin: '4px 0' }}>{line}</p>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="landing-section landing-section--features">
        <div className="landing-section__eyebrow">{t('Landing.section_features')}</div>
        <h2>{t('Landing.features_title')}</h2>
        <div className="landing-section__sub">{t('Landing.features_sub')}</div>
        <div className="feature-grid" aria-label={t('Landing.features_title')}>
          {FEATURE_CARDS.map((card) => (
            <article className="feature-card" key={card.marker}>
              <div className="feature-card__marker">{card.marker}</div>
              <h3>{t(card.titleKey)}</h3>
              <p>{t(card.descKey)}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Pipeline */}
      <section className="landing-section">
        <div className="landing-section__eyebrow">{t('Landing.section_workflow')}</div>
        <h2>{t('Landing.pipeline_title')}</h2>
        <div className="landing-section__sub">{t('Landing.pipeline_sub')}</div>
        <div className="steps-grid">
          {STEP_KEYS.map((key) => (
            <div className="step" key={key}>
              <div className="step__number">{t(`Landing.step_${key}` as 'Landing.step_01')}</div>
              <h3>{t(`Landing.step_${key}_title` as 'Landing.step_01_title')}</h3>
              <p>{t(`Landing.step_${key}_desc` as 'Landing.step_01_desc')}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Before / After */}
      <section className="landing-section">
        <div className="landing-section__eyebrow">{t('Landing.section_evidence')}</div>
        <h2>{t('Landing.before_after_title')}</h2>
        <div className="landing-section__sub">{t('Landing.before_after_sub')}</div>
        <div className="ba-grid">
          <div className="ba-col">
            <div className="ba-col__header">{t('Landing.before_header')}</div>
            <div className="ba-col__body">
              <pre>{SAMPLE_DIFF}</pre>
            </div>
          </div>
          <div className="ba-col">
            <div className="ba-col__header">{t('Landing.after_header')}</div>
            <div className="ba-col__body">
              {SAMPLE_LESSON.split('\n').map((line, i) => (
                <p key={i} style={{ margin: '4px 0', fontSize: 13, lineHeight: 1.65 }}>{line}</p>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Benchmark & Trust */}
      <section className="landing-section">
        <div className="landing-section__eyebrow">{t('Landing.section_benchmark')}</div>
        <h2>{t('Landing.benchmark_title')}</h2>
        <div className="landing-section__sub">{t('Landing.benchmark_sub')}</div>
        <div className="demo-banner">
          <span className="demo-tag">{t('Landing.demo_tag_full')}</span>
          <span>
            {t('Landing.demo_banner_lead')}{' '}
            <strong>{t('Landing.demo_banner_action')}</strong>
            {t('Landing.demo_banner_tail')}
          </span>
        </div>
        <div className="benchmark-grid" aria-label={t('Landing.bench_demo_note')}>
          {TRUST_CARDS.map((card) => (
            <article className="benchmark-card" key={card.labelKey}>
              <div className="benchmark-card__label-row">
                <span className="benchmark-card__label">{t(card.labelKey)}</span>
                <span className="demo-tag benchmark-card__demo">{t('Landing.demo_tag')}</span>
              </div>
              <div className="benchmark-card__value">{card.value}</div>
              <div
                className={
                  card.deltaTone === 'up'
                    ? 'benchmark-card__delta benchmark-card__delta--up'
                    : 'benchmark-card__delta'
                }
              >
                {t(card.deltaKey)}
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
