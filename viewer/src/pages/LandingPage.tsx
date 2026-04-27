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

export default function LandingPage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<'raw' | 'aha'>('aha');

  return (
    <div className="landing">
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
            <div className="hero-demo__tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'raw'}
                aria-controls="demo-panel"
                className={`hero-demo__tab${activeTab === 'raw' ? ' hero-demo__tab--active' : ''}`}
                onClick={() => setActiveTab('raw')}
              >
                {t('Landing.tab_raw')}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'aha'}
                aria-controls="demo-panel"
                className={`hero-demo__tab${activeTab === 'aha' ? ' hero-demo__tab--active' : ''}`}
                onClick={() => setActiveTab('aha')}
              >
                {t('Landing.tab_aha')}
              </button>
            </div>
            <div className="hero-demo__content" id="demo-panel" role="tabpanel">
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

      {/* Pipeline */}
      <section className="landing-section">
        <div className="landing-section__eyebrow">{t('Landing.section_workflow')}</div>
        <h2>{t('Landing.pipeline_title')}</h2>
        <div className="landing-section__sub">{t('Landing.pipeline_sub')}</div>
        <div className="steps-grid">
          {STEP_KEYS.map((key) => (
            <div className="step" key={key}>
              <div className="step__number">{t(`Landing.step_${key}` as 'Landing.step_01')}</div>
              <h4>{t(`Landing.step_${key}_title` as 'Landing.step_01_title')}</h4>
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
    </div>
  );
}
