import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../i18n/useTranslation';
import { renderMarkdownProse } from '../utils/markdown';
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
  const renderedLesson = useMemo(() => renderMarkdownProse(SAMPLE_LESSON, 'hero-demo'), []);

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
    <main className="landing page active" data-page="landing" style={{ display: 'block', padding: 0, maxWidth: 'none' }}>
      {/* Hero */}
      <section className="hero">
        <div className="hero-grid">
          <div>
            <div className="eyebrow" style={{ marginBottom: '18px' }}>{t('Landing.hero_eyebrow')}</div>
            <h1>
              {t('Landing.hero_title_1')}
              <br />
              <em>{t('Landing.hero_title_2')}</em>
            </h1>
            <div className="en">{t('Brand.tagline')}</div>
            <p className="lead">{t('Landing.hero_lead')}</p>
            <div className="hero-ctas">
              <Link to="/" className="btn primary btn-inkstone">
                {t('Nav.dashboard')} →
              </Link>
              <span className="text">⌘ ahadiff learn HEAD~1..HEAD</span>
            </div>
          </div>

          <div className="hero-demo">
            <div className="tabs" role="tablist" aria-label={t('Landing.tabs_label')}>
              <button
                type="button"
                id="tab-raw"
                role="tab"
                aria-selected={activeTab === 'raw'}
                aria-controls="demo-panel"
                tabIndex={activeTab === 'raw' ? 0 : -1}
                className={`tab${activeTab === 'raw' ? ' active' : ''}`}
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
                className={`tab${activeTab === 'aha' ? ' active' : ''}`}
                onClick={() => setActiveTab('aha')}
                onKeyDown={e => handleDemoTabKeyDown(e, 1)}
              >
                {t('Landing.tab_aha')}
              </button>
            </div>
            <div className="pane active" id="demo-panel" role="tabpanel" aria-labelledby={activeTab === 'raw' ? 'tab-raw' : 'tab-aha'} tabIndex={0}>
              {activeTab === 'raw' ? (
                <pre className="code-block" style={{ margin: 0, borderLeft: '3px solid var(--muted)', maxHeight: '340px' }}>
                  {SAMPLE_DIFF}
                </pre>
              ) : (
                <div className="u-text-sm-relaxed prose" style={{ fontSize: '14.5px' }}>
                  {renderedLesson}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="section">
        <div className="eyebrow">{t('Landing.section_features')}</div>
        <h2>{t('Landing.features_title')}</h2>
        <div className="sub">{t('Landing.features_sub')}</div>
        <div className="feature-grid" aria-label={t('Landing.features_title')}>
          {FEATURE_CARDS.map((card) => (
            <article className="card" key={card.marker} style={{ padding: '18px 20px' }}>
              <div className="eyebrow">{card.marker}</div>
              <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: '18px', fontWeight: 500, margin: '8px 0 6px', letterSpacing: '-0.01em' }}>{t(card.titleKey)}</h3>
              <p style={{ fontSize: '13px', color: 'var(--muted)', margin: 0, lineHeight: 1.55 }}>{t(card.descKey)}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Pipeline */}
      <section className="section">
        <div className="eyebrow">{t('Landing.section_workflow')}</div>
        <h2>{t('Landing.pipeline_title')}</h2>
        <div className="sub">{t('Landing.pipeline_sub')}</div>
        <div className="steps">
          {STEP_KEYS.map((key) => (
            <div className="st" key={key}>
              <div className="n">{t(`Landing.step_${key}` as 'Landing.step_01')}</div>
              <h4>{t(`Landing.step_${key}_title` as 'Landing.step_01_title')}</h4>
              <p>{t(`Landing.step_${key}_desc` as 'Landing.step_01_desc')}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Before / After */}
      <section className="section">
        <div className="eyebrow">{t('Landing.section_evidence')}</div>
        <h2>{t('Landing.before_after_title')}</h2>
        <div className="sub">{t('Landing.before_after_sub')}</div>
        <div className="ba">
          <div className="col">
            <h5>{t('Landing.before_header')}</h5>
            <div className="ba-col__body">
              <pre className="mono" style={{ fontSize: '12px', lineHeight: 1.6, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{SAMPLE_DIFF}</pre>
            </div>
          </div>
          <div className="col" style={{ background: '#fff' }}>
            <h5>{t('Landing.after_header')}</h5>
            <div className="prose" style={{ fontSize: '14.5px', lineHeight: 1.7 }}>
              {renderedLesson}
            </div>
          </div>
        </div>
      </section>

      {/* Benchmark & Trust */}
      <section className="section">
        <div className="eyebrow">{t('Landing.section_benchmark')}</div>
        <h2>{t('Landing.benchmark_title')}</h2>
        <div className="sub">{t('Landing.benchmark_sub')}</div>
        <div className="demo-banner">
          <span className="demo-tag">{t('Landing.demo_tag_full')}</span>
          <span>
            {t('Landing.demo_banner_lead')}{' '}
            <strong>{t('Landing.demo_banner_action')}</strong>
            {t('Landing.demo_banner_tail')}
          </span>
        </div>
        <div className="kpi-grid" aria-label={t('Landing.bench_demo_note')}>
          {TRUST_CARDS.map((card) => (
            <article className="kpi" key={card.labelKey}>
              <div className="lb">
                {t(card.labelKey)}
                <span className="demo-tag" style={{ fontSize: '9px', padding: '1px 5px' }}>{t('Landing.demo_tag')}</span>
              </div>
              <div className="vl">{card.value}</div>
              <div className="delta">
                {card.deltaTone === 'up' ? (
                  <span className="up">▲ {t(card.deltaKey)}</span>
                ) : (
                  <span>{t(card.deltaKey)}</span>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
