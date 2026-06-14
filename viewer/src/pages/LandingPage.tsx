import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { getRatchetTransparency, getRunArtifact, getRunLesson } from '../api/runs';
import LearnTaskBanner from '../components/LearnTaskBanner';
import { ApiError } from '../api/client';
import type { RatchetTransparencyResponse, RunArtifactEnvelope, RunSummary } from '../api/types';
import { useTranslation } from '../i18n/useTranslation';
import { useLearnStore } from '../state/learn-store';
import { useRunsStore } from '../state/runs-store';
import { formatCompactNumber } from '../utils/format';
import { renderMarkdownCollapsible, renderMarkdownProse } from '../utils/markdown';
import '../components/Landing.css';

const LearnModeDialog = lazy(() => import('../components/LearnModeDialog'));

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

const SAMPLE_LESSON_ZH = `## 这次改了什么

返回值从 \`"world"\` 改成了 \`"AhaDiff"\`，
并新增了一个 \`# learn-from-diff\` 标记。

**声明 c007**（已验证）：该函数现在返回
项目名，而不是通用的问候语。
\`demo.py:3\` — 证据：第 3 行展示了新的返回值。`;

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

interface TrustCardView {
  key: string;
  label: string;
  value: string;
  delta: string;
  deltaTone: 'neutral' | 'up';
  source: 'demo' | 'live';
}

const DEMO_TABS = ['raw', 'aha'] as const;
type DemoTabId = typeof DEMO_TABS[number];
const LESSON_LEVEL_FALLBACKS = ['full', 'hint', 'compact'] as const;
const DEFAULT_DIFF_COLLAPSE_HEIGHT = 300;
const MIN_DIFF_COLLAPSE_HEIGHT = 200;
const DIFF_LINE_HEIGHT_PX = 19.2;
const DIFF_FADE_HEIGHT_PX = 64;

interface LiveHeroDemo {
  diff: string | null;
  lesson: string | null;
  runLabel: string;
}

function formatLiveNumber(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '—';
  return formatCompactNumber(value, locale);
}

function formatLiveScore(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '—';
  try {
    return new Intl.NumberFormat(locale || undefined, {
      maximumFractionDigits: 1,
      minimumFractionDigits: 1,
    }).format(value);
  } catch {
    return value.toFixed(1);
  }
}

function formatLiveRate(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '—';
  try {
    return new Intl.NumberFormat(locale || undefined, {
      maximumFractionDigits: 0,
      style: 'percent',
    }).format(value);
  } catch {
    return `${Math.round(value * 100)}%`;
  }
}

function latestRunOf(runs: RunSummary[]): RunSummary | null {
  if (runs.length === 0) return null;
  return [...runs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )[0];
}

async function getFirstAvailableLesson(
  runId: string,
  options: { signal: AbortSignal },
): Promise<RunArtifactEnvelope | null> {
  for (const level of LESSON_LEVEL_FALLBACKS) {
    try {
      return await getRunLesson(runId, level, options);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 404) continue;
      throw err;
    }
  }
  return null;
}

export default function LandingPage() {
  const { t, locale } = useTranslation();
  const runs = useRunsStore((s) => s.runs);
  const loadRuns = useRunsStore((s) => s.loadRuns);
  const learnPhase = useLearnStore((s) => s.phase);
  const completedLearnRunId = useLearnStore((s) =>
    s.phase === 'completed' ? s.task?.result_summary?.run_id ?? null : null,
  );
  const [activeTab, setActiveTab] = useState<DemoTabId>('aha');
  const [isLearnDialogOpen, setIsLearnDialogOpen] = useState(false);
  const [liveDemo, setLiveDemo] = useState<LiveHeroDemo | null>(null);
  const [transparency, setTransparency] = useState<RatchetTransparencyResponse | null>(null);
  const latestRun = useMemo(() => latestRunOf(runs), [runs]);
  const activeRunId = completedLearnRunId ?? latestRun?.run_id ?? null;
  const activeRunSourceRef = runs.find((run) => run.run_id === activeRunId)?.source_ref ?? null;
  const liveLessonMissing = liveDemo !== null && liveDemo.lesson === null;
  const latestRunPath = activeRunId
    ? `/run/${encodeURIComponent(activeRunId)}${liveLessonMissing ? '' : '/lesson'}`
    : '/';
  const demoDiff = liveDemo ? liveDemo.diff : SAMPLE_DIFF;
  const demoLesson = liveDemo
    ? liveDemo.lesson
    : locale.startsWith('zh')
      ? SAMPLE_LESSON_ZH
      : SAMPLE_LESSON;
  const renderedLesson = useMemo(
    () => (demoLesson ? renderMarkdownProse(demoLesson, 'hero-demo') : null),
    [demoLesson],
  );
  const renderedLessonCollapsible = useMemo(
    () => (demoLesson ? renderMarkdownCollapsible(demoLesson, 'hero-demo', 1) : null),
    [demoLesson],
  );

  const [diffExpanded, setDiffExpanded] = useState(false);
  const rightColRef = useRef<HTMLDivElement>(null);
  const [diffCollapseHeight, setDiffCollapseHeight] = useState(DEFAULT_DIFF_COLLAPSE_HEIGHT);

  const diffLineCount = useMemo(() => {
    if (!demoDiff) return 0;
    return demoDiff.split('\n').length;
  }, [demoDiff]);

  const collapsedVisibleLineCount = useMemo(() => {
    if (!demoDiff) return 0;
    const visibleHeight = Math.max(DIFF_LINE_HEIGHT_PX, diffCollapseHeight - DIFF_FADE_HEIGHT_PX);
    return Math.max(1, Math.floor(visibleHeight / DIFF_LINE_HEIGHT_PX));
  }, [demoDiff, diffCollapseHeight]);

  const needsCollapse = diffLineCount > 0 && diffLineCount > collapsedVisibleLineCount + 3;

  useEffect(() => {
    setDiffExpanded(false);
  }, [demoDiff]);

  useEffect(() => {
    const el = rightColRef.current;
    if (!el) return;
    let frameId: number | null = null;
    const applyHeight = (height: number) => {
      const nextHeight = Math.max(MIN_DIFF_COLLAPSE_HEIGHT, Math.ceil(height));
      setDiffCollapseHeight((current) => (current === nextHeight ? current : nextHeight));
    };
    applyHeight(el.getBoundingClientRect().height);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      if (frameId !== null) window.cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(() => {
        applyHeight(entry.contentRect.height);
        frameId = null;
      });
    });
    ro.observe(el);
    return () => {
      if (frameId !== null) window.cancelAnimationFrame(frameId);
      ro.disconnect();
    };
  }, []);

  const handleDiffToggle = useCallback(() => {
    setDiffExpanded((prev) => !prev);
  }, []);

  useEffect(() => {
    void loadRuns().catch(() => {
      // Welcome remains useful as a static example when serve has no run list.
    });
  }, [loadRuns]);

  useEffect(() => {
    if (learnPhase !== 'completed') return undefined;
    const controller = new AbortController();
    void loadRuns(undefined, { signal: controller.signal }).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      // Keep the just-finished run preview path working via result_summary.run_id.
    });
    return () => controller.abort();
  }, [learnPhase, loadRuns]);

  useEffect(() => {
    const controller = new AbortController();
    getRatchetTransparency({ signal: controller.signal }).then((payload) => {
      if (!controller.signal.aborted) setTransparency(payload);
    }).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (!controller.signal.aborted) setTransparency(null);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!activeRunId) {
      setLiveDemo(null);
      return;
    }

    const controller = new AbortController();
    const runLabel = activeRunSourceRef || activeRunId.slice(0, 8);
    setLiveDemo({ diff: null, lesson: null, runLabel });
    Promise.allSettled([
      getRunArtifact(activeRunId, 'diff', { signal: controller.signal }),
      getFirstAvailableLesson(activeRunId, { signal: controller.signal }),
    ]).then(([diffResult, lessonResult]) => {
      if (controller.signal.aborted) return;
      const diff = diffResult.status === 'fulfilled'
        ? diffResult.value.content.trim() || null
        : null;
      const lesson = lessonResult.status === 'fulfilled'
        ? lessonResult.value?.content.trim() || null
        : null;
      setLiveDemo({
        diff,
        lesson,
        runLabel,
      });
    }).catch((err: unknown) => {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      setLiveDemo({ diff: null, lesson: null, runLabel });
    });

    return () => controller.abort();
  }, [activeRunId, activeRunSourceRef]);

  const trustCards: TrustCardView[] = useMemo(() => {
    const manifest = transparency?.benchmark.manifest ?? null;
    const report = transparency?.benchmark.report ?? null;
    if (manifest || report) {
      return [
        {
          key: 'fixtures',
          label: t('Landing.bench_live_fixtures'),
          value: formatLiveNumber(manifest?.entry_count ?? null, locale),
          delta: t('Landing.bench_live_fixtures_delta', {
            eval: String(manifest?.eval_entry_count ?? 0),
            integration: String(manifest?.integration_entry_count ?? 0),
          }),
          deltaTone: 'neutral',
          source: 'live',
        },
        {
          key: 'mean-score',
          label: t('Landing.bench_live_mean_score'),
          value: formatLiveScore(report?.mean_score ?? null, locale),
          delta: report?.suite_id ?? manifest?.suite_id ?? t('Landing.bench_live_suite_unknown'),
          deltaTone: 'up',
          source: 'live',
        },
        {
          key: 'comparable',
          label: t('Landing.bench_live_comparable'),
          value: formatLiveNumber(report?.comparable_entry_count ?? null, locale),
          delta: t('Landing.bench_live_comparable_delta', {
            degraded: String(report?.excluded_degraded_count ?? manifest?.degraded_entry_count ?? 0),
          }),
          deltaTone: 'neutral',
          source: 'live',
        },
        {
          key: 'claim-rate',
          label: t('Landing.bench_live_claim_rate'),
          value: formatLiveRate(report?.claim_verification_rate ?? null, locale),
          delta: report?.model_id ?? t('Landing.bench_live_model_none'),
          deltaTone: 'neutral',
          source: 'live',
        },
      ];
    }
    return TRUST_CARDS.map((card) => ({
      key: card.labelKey,
      label: t(card.labelKey),
      value: card.value,
      delta: t(card.deltaKey),
      deltaTone: card.deltaTone,
      source: 'demo',
    }));
  }, [locale, t, transparency]);

  const trustIsLive = trustCards.some((card) => card.source === 'live');

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
            <p className="eyebrow">{t('Landing.hero_eyebrow')}</p>
            <h1 className="hero__title">
              {t('Landing.hero_title_1')}
              <br />
              <em>{t('Landing.hero_title_2')}</em>
            </h1>
            <div className="en">{t('Brand.tagline')}</div>
            <p className="lead">{t('Landing.hero_lead')}</p>
            <div className="hero-ctas">
              <Link to={latestRunPath} className="btn primary btn-inkstone btn-primary">
                {activeRunId
                  ? t(liveLessonMissing ? 'Landing.hero_cta_run' : 'Landing.hero_cta_lesson')
                  : t('Nav.dashboard')} →
              </Link>
              <button
                type="button"
                className="btn ghost hero-ctas__learn"
                onClick={() => setIsLearnDialogOpen(true)}
              >
                {t('Landing.hero_cta_learn')}
              </button>
              <span className="text cli-cmd">ahadiff learn HEAD~1..HEAD</span>
            </div>
            <div className="hero-learn-status">
              <LearnTaskBanner />
            </div>
            <p className="folio-line hero__folio" aria-hidden="true">
              <span className="folio-line__page">§ 01</span>
              <span className="folio-line__sep">·</span>
              <span>{t('Brand.name')}</span>
              <span className="folio-line__sep">·</span>
              <span>{t('Brand.tagline')}</span>
            </p>
          </div>

          <div className="hero-demo">
            <div className="tabs hero-demo__tabs" role="tablist" aria-label={t('Landing.tabs_label')}>
              <button
                type="button"
                id="tab-raw"
                role="tab"
                aria-selected={activeTab === 'raw'}
                aria-controls="demo-panel"
                tabIndex={activeTab === 'raw' ? 0 : -1}
                className={`tab hero-demo__tab${activeTab === 'raw' ? ' active hero-demo__tab--active' : ''}`}
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
                className={`tab hero-demo__tab${activeTab === 'aha' ? ' active hero-demo__tab--active' : ''}`}
                onClick={() => setActiveTab('aha')}
                onKeyDown={e => handleDemoTabKeyDown(e, 1)}
              >
                {t('Landing.tab_aha')}
              </button>
            </div>
            <div className={`hero-demo__source${liveDemo ? ' hero-demo__source--live' : ''}`}>
              <span className="demo-tag">
                {liveDemo ? t('Landing.live_tag') : t('Landing.demo_tag')}
              </span>
              <span>
                {liveDemo
                  ? t('Landing.hero_demo_source_latest', { run: liveDemo.runLabel })
                  : t('Landing.hero_demo_source_demo')}
              </span>
            </div>
            <div className="pane active hero-demo__content" id="demo-panel" role="tabpanel" aria-labelledby={activeTab === 'raw' ? 'tab-raw' : 'tab-aha'} tabIndex={0}>
              {activeTab === 'raw' ? (
                demoDiff ? (
                  <pre className="code-block" style={{ margin: 0, borderLeft: '3px solid var(--muted)' }}>
                    {demoDiff}
                  </pre>
                ) : (
                  <div className="hero-demo__artifact-empty" role="status">
                    {t('Landing.hero_demo_diff_unavailable')}
                  </div>
                )
              ) : (
                <div className="u-text-sm-relaxed prose" style={{ fontSize: '14.5px' }}>
                  {renderedLessonCollapsible ?? (
                    <div className="hero-demo__artifact-empty" role="status">
                      <strong>{t('Landing.hero_demo_lesson_unavailable_title')}</strong>
                      <span>{t('Landing.hero_demo_lesson_unavailable_body')}</span>
                    </div>
                  )}
                  {liveDemo && activeRunId && liveDemo.lesson && (
                    <div className="hero-demo__lesson-link">
                      <Link to={`/run/${encodeURIComponent(activeRunId)}/lesson`}>
                        {t('Diff.open_lesson')} →
                      </Link>
                    </div>
                  )}
                  {liveDemo && activeRunId && !liveDemo.lesson && (
                    <div className="hero-demo__lesson-link">
                      <Link to={`/run/${encodeURIComponent(activeRunId)}`}>
                        {t('Landing.hero_demo_open_run')} →
                      </Link>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </section>
      {isLearnDialogOpen ? (
        <Suspense fallback={null}>
          <LearnModeDialog open={isLearnDialogOpen} onClose={() => setIsLearnDialogOpen(false)} />
        </Suspense>
      ) : null}

      {/* Features */}
      <section className="section">
        <div className="eyebrow">{t('Landing.section_features')}</div>
        <h2>{t('Landing.features_title')}</h2>
        <div className="sub">{t('Landing.features_sub')}</div>
        <div className="feature-grid" aria-label={t('Landing.features_title')}>
          {FEATURE_CARDS.map((card) => (
            <article className="card feature-card" key={card.marker}>
              <div className="eyebrow feature-card__marker">{card.marker}</div>
              <h3>{t(card.titleKey)}</h3>
              <p>{t(card.descKey)}</p>
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
            <div className="st step" key={key}>
              <div className="n">{t(`Landing.step_${key}` as 'Landing.step_01')}</div>
              <h3>{t(`Landing.step_${key}_title` as 'Landing.step_01_title')}</h3>
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
        <div className="ba ba-grid">
          <div className="col">
            <h3 className="ba-col__header">{t('Landing.before_header')}</h3>
            <div className="ba-col__body">
              {demoDiff ? (
                <>
                  <div
                    className="ba-diff-wrap"
                    id="landing-diff-content"
                    style={{ maxHeight: needsCollapse && !diffExpanded ? diffCollapseHeight : 'none' }}
                  >
                    <pre className="mono" style={{ fontSize: '12px', lineHeight: 1.6, color: 'var(--ink-2)', whiteSpace: 'pre-wrap' }}>{demoDiff}</pre>
                    {needsCollapse && !diffExpanded && (
                      <div className="ba-diff-fade" aria-hidden="true">
                        <span className="ba-diff-line-count">
                          {t('Landing.diff_showing_lines', { shown: String(collapsedVisibleLineCount), total: String(diffLineCount) })}
                        </span>
                      </div>
                    )}
                  </div>
                  {needsCollapse && (
                    <button
                      type="button"
                      className="ba-diff-toggle"
                      aria-expanded={diffExpanded}
                      aria-controls="landing-diff-content"
                      aria-label={diffExpanded
                        ? `${t('Landing.before_header')}: ${t('Landing.diff_collapse')}`
                        : `${t('Landing.before_header')}: ${t('Landing.diff_expand')} — ${t('Landing.diff_showing_lines', { shown: String(collapsedVisibleLineCount), total: String(diffLineCount) })}`}
                      onClick={handleDiffToggle}
                    >
                      {diffExpanded ? t('Landing.diff_collapse') : t('Landing.diff_expand')}
                      <span className="ba-diff-arrow" aria-hidden="true">▼</span>
                    </button>
                  )}
                </>
              ) : (
                <div className="hero-demo__artifact-empty" role="status">
                  {t('Landing.hero_demo_diff_unavailable')}
                </div>
              )}
            </div>
          </div>
          <div className="col" style={{ background: 'var(--elevated)' }}>
            <div ref={rightColRef}>
              <h3 className="ba-col__header">{t('Landing.after_header')}</h3>
              <div className="prose" style={{ fontSize: '14.5px', lineHeight: 1.7 }}>
                {renderedLesson ?? (
                  <div className="hero-demo__artifact-empty" role="status">
                    <strong>{t('Landing.hero_demo_lesson_unavailable_title')}</strong>
                    <span>{t('Landing.hero_demo_lesson_unavailable_body')}</span>
                  </div>
                )}
              </div>
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
          <span className="demo-tag">{trustIsLive ? t('Landing.live_tag') : t('Landing.demo_tag_full')}</span>
          <span>
            {trustIsLive
              ? t('Landing.benchmark_live_banner')
              : (
                <>
                  {t('Landing.demo_banner_lead')}{' '}
                  <strong>{t('Landing.demo_banner_action')}</strong>
                  {t('Landing.demo_banner_tail')}
                </>
              )}
          </span>
        </div>
        <div className="kpi-grid" aria-label={t(trustIsLive ? 'Landing.bench_live_note' : 'Landing.bench_demo_note')}>
          {trustCards.map((card) => (
            <article className="kpi benchmark-card" key={card.key}>
              <div className="lb">
                {card.label}
                <span className="demo-tag" style={{ fontSize: '9px', padding: '1px 5px' }}>
                  {card.source === 'live' ? t('Landing.live_tag') : t('Landing.demo_tag')}
                </span>
              </div>
              <div className="vl">{card.value}</div>
              <div className="delta benchmark-card__delta">
                {card.deltaTone === 'up' ? (
                  <span className="up">▲ {card.delta}</span>
                ) : (
                  <span>{card.delta}</span>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
