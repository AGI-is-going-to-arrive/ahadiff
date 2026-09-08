import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import type { ActivePracticeSummary } from '../../src/api/types';
import { installServeMock } from '../fixtures/serve-mock';

const TEST_PATH = '/__active-exercise-test.html';
const QUESTION = 'Complete a similar example:\nif request_fails:\n    ____';
const REFERENCE = 'if request_fails:\n    retry_later()';
const QUIZ = {
  question_id: 'quiz-practice', review_card_id: 'card_exercise_synthetic', question: QUESTION,
  quiz_kind: 'transfer', exercise_kind: 'completion', scenario_kind: 'new_variant', answer_mode: 'open',
  expected_answer: REFERENCE, source_claims: ['claim-retry'], concepts: ['retry'],
  evidence: [{ file: 'sample.py', line: 2 }], explanation: 'The source supports bounded retry, not guaranteed success.',
};
const HARNESS_HTML = `<!doctype html><html lang="en"><head><meta charset="UTF-8"></head><body>
<div id="root"></div><script type="module">
import React from 'react';
import { createRoot } from 'react-dom/client';
import SRSCard from '/src/components/SRSCard.tsx';
import { getQuizQuestions, revealQuizQuestion } from '/src/api/quiz.ts';
import { quizAnswer, srsReview } from '/src/api/signals.ts';
import { useLocaleStore } from '/src/state/locale-store.ts';
import '/src/components/Quiz.css';
import '/src/styles/tokens.css';
let root;
window.__activeAnswers = [];
window.__mountActive = async (locale) => {
  useLocaleStore.setState({locale});
  document.documentElement.lang = locale;
  const { questions } = await getQuizQuestions('run-1');
  const quiz = questions[0];
  root?.unmount();
  root = createRoot(document.getElementById('root'));
  root.render(React.createElement(React.StrictMode, null, React.createElement(SRSCard, {
    quiz,runId:'run-1',
    onReveal: label => revealQuizQuestion('run-1', quiz.question_id, {attempted: true, ...(label ? {selected_choice_label: label} : {})}),
    onAnswer: (_id, _answer, correct) => { window.__activeAnswers.push({correct}); },
    onRate: async (rating, assessment) => {
      await quizAnswer({idempotency_key:'test-assessment',run_id:'run-1',quiz_id:quiz.question_id,
        correct:null, exercise_kind:quiz.exercise_kind, feedback_kind:'semantic_self_assessment',
        self_assessment:assessment.selfAssessment,error_type:assessment.errorType});
      await srsReview({idempotency_key:'test-srs',card_id:quiz.review_card_id,answer:rating,peeked_this_session:false});
      return true;
    }
  })));
};
window.__mountMetrics = async (summary, locale) => {
  const { ActivePracticePanel } = await import('/src/pages/DashboardPage.tsx');
  useLocaleStore.setState({locale});
  root?.unmount();
  root = createRoot(document.getElementById('root'));
  root.render(React.createElement(ActivePracticePanel, {summary}));
};
window.__mountReviewExercise = async () => {
  const {ActiveReviewExercise} = await import('/src/pages/ReviewPage.tsx');
  const {useReviewStore} = await import('/src/state/review-store.ts');
  const base = {run_id:'run-1',concept:'',due_date:'2026-01-01T00:00:00Z',scaffolding_level:'1',display_path:'',
    stability:null,difficulty:null,reps:0,lapses:0,last_rating:null,exercise_kind:'completion',answer_mode:'open'};
  const cards = [
    {...base,card_id:'card_exercise_A',question_id:'quiz-practice',question:'Attempt A'},
    {...base,card_id:'card_exercise_B',question_id:'quiz-second',question:'Attempt B'},
  ];
  useReviewStore.getState().reset();
  useReviewStore.setState({cards});
  root?.unmount();
  root = createRoot(document.getElementById('root'));
  const render = card => root.render(React.createElement(ActiveReviewExercise, {key:card.card_id,card,
    onRate:(rating,binding)=>useReviewStore.getState().rate(rating,binding).then(result=>result!==null)}));
  window.__selectReviewExercise = id => {useReviewStore.getState().selectCard(id);render(useReviewStore.getState().currentCard());};
  render(cards[0]);
};
window.__mountQuizRoute = async (runId) => {
  const [{default:QuizPage},{MemoryRouter,Routes,Route,useNavigate}] = await Promise.all([
    import('/src/pages/QuizPage.tsx'),import('react-router-dom')]);
  function Navigation(){const navigate=useNavigate();React.useEffect(()=>{window.__navigateQuiz=navigate;},[navigate]);return null;}
  root?.unmount();
  root=createRoot(document.getElementById('root'));
  root.render(React.createElement(MemoryRouter,{initialEntries:['/run/'+runId+'/quiz']},
    React.createElement(Navigation),React.createElement(Routes,null,
      React.createElement(Route,{path:'/run/:runId/quiz',element:React.createElement(QuizPage)}))));
};
window.__activeReady = true;
</script></body></html>`;

declare global {
  interface Window {
    __activeReady?: boolean;
    __mountReviewExercise: () => Promise<void>;
    __selectReviewExercise: (cardId: string) => void;
    __mountQuizRoute: (runId: string) => Promise<void>;
    __navigateQuiz: (path: string) => void;
    __mountMetrics: (summary: ActivePracticeSummary, locale: 'en' | 'zh-CN') => Promise<void>;
    __mountActive: (locale: 'en' | 'zh-CN') => Promise<void>;
    __activeAnswers: Array<{ correct: boolean | null }>;
  }
}

let server: ViteDevServer;
let browser: Browser;
let page: Page;
let baseUrl = '';
let requests: Array<{ path: string; body: Record<string, unknown> | null }>;

beforeAll(async () => {
  server = await createServer({ appType: 'custom', root: process.cwd(), logLevel: 'silent',
    server: { host: '127.0.0.1', port: 0 } });
  server.middlewares.use(TEST_PATH, async (_request, response) => {
    response.setHeader('content-type', 'text/html; charset=utf-8');
    response.end(await server.transformIndexHtml(TEST_PATH, HARNESS_HTML));
  });
  await server.listen();
  const address = server.httpServer?.address();
  if (!address || typeof address === 'string') throw new Error('No harness port');
  baseUrl = `http://127.0.0.1:${address.port}`;
  browser = await chromium.launch();
}, 30_000);

afterAll(async () => {
  await page?.close();
  await browser?.close();
  await server?.close();
});

beforeEach(async () => {
  await page?.close();
  page = await browser.newPage();
  requests = [];
  page.on('request', request => {
    const path = new URL(request.url()).pathname;
    if (!path.startsWith('/api/')) return;
    const body = request.postData();
    requests.push({ path, body: body ? JSON.parse(body) as Record<string, unknown> : null });
  });
  await page.route('**/api/auth/token', route => route.fulfill({ json: { token: 'test-token' } }));
  await page.route('**/api/run/run-1/quiz/questions', route => route.fulfill({ json: {
    run_id: 'run-1', questions: [{ question_id: QUIZ.question_id, review_card_id: QUIZ.review_card_id,
      question: QUESTION, quiz_kind: 'transfer', exercise_kind: 'completion', scenario_kind: 'new_variant',
      answer_mode: 'open', choices: null }],
  } }));
  await page.route('**/api/run/run-1/quiz/quiz-practice/reveal', route => route.fulfill({ json: {
    run_id: 'run-1', question: QUIZ, correct: null, feedback_kind: 'semantic_self_assessment',
  } }));
  await page.route('**/api/signals/**', route => route.fulfill({ json: { inserted: true } }));
});

async function mount(locale: 'en' | 'zh-CN' = 'en'): Promise<void> {
  await page.goto(`${baseUrl}${TEST_PATH}`);
  await page.waitForFunction(() => window.__activeReady);
  await page.evaluate(value => window.__mountActive(value), locale);
  await expect.poll(() => page.locator('.srs-card').count()).toBe(1);
}

describe('active transfer practice', () => {
  it.each(['en', 'zh-CN'] as const)('separates answers, keeps multiline text and records semantic assessment in %s', async locale => {
    await mount(locale);
    expect(await page.locator('.srs-card__question').textContent()).toBe(QUESTION);
    expect(await page.locator('body').textContent()).not.toContain(REFERENCE);
    expect(requests.filter(request => request.path.endsWith('/reveal'))).toHaveLength(0);
    expect(await page.locator('.srs-card__rating-btn').count()).toBe(0);
    expect(await page.locator('.srs-card__evidence-link').count()).toBe(0);
    const draft = 'Schedule one more bounded attempt, using an equivalent implementation';
    await page.locator('textarea').fill(draft);
    await page.locator('.srs-card__btn--primary').click();
    await expect.poll(() => page.locator('.srs-card__explanation-body').first().textContent()).toBe(REFERENCE);
    expect(await page.evaluate(() => window.__activeAnswers)).toEqual([{ correct: null }]);
    expect(await page.locator('.srs-card__evidence-link').getAttribute('href')).toBe('#/run/run-1/diff?focus=sample.py%3A2');
    expect(await page.locator('.srs-card__result--wrong').count()).toBe(0);
    expect(requests.filter(request => request.path.endsWith('/reveal'))).toEqual([
      { path: '/api/run/run-1/quiz/quiz-practice/reveal', body: { attempted: true } },
    ]);
    expect(requests.some(request => request.path.endsWith('/quiz-answer'))).toBe(false);
    await expect.poll(() => page.locator('.srs-card__rating-btn--good').isEnabled(), { timeout: 5000 }).toBe(true);
    await page.locator('.srs-card__rating-btn--good').click();
    await expect.poll(() => requests.filter(request => request.path.endsWith('/srs-review')).length).toBe(1);
    const signal = requests.find(request => request.path.endsWith('/quiz-answer'))?.body;
    expect(signal).toMatchObject({ correct: null, self_assessment: 'independent', error_type: 'none' });
    expect(JSON.stringify(requests)).not.toContain(draft);
    expect(requests.find(request => request.path.endsWith('/srs-review'))?.body).toMatchObject({
      card_id: 'card_exercise_synthetic', answer: 'good', peeked_this_session: false,
    });
  });

  it('keeps an unsuccessful reveal private and retryable without losing the attempt', async () => {
    let available = false;
    await page.route('**/api/run/run-1/quiz/quiz-practice/reveal', route => available
      ? route.fulfill({ json: { run_id: 'run-1', question: QUIZ, correct: null, feedback_kind: 'semantic_self_assessment' } })
      : route.fulfill({ status: 500, json: { error: 'unavailable', error_code: 'INTERNAL_ERROR', status: 500 } }));
    await mount();
    await page.locator('textarea').fill('My private partial attempt');
    await page.locator('.srs-card__btn--primary').click();
    await expect.poll(() => page.getByRole('alert').count()).toBe(1);
    expect(await page.locator('textarea').inputValue()).toBe('My private partial attempt');
    expect(await page.locator('body').textContent()).not.toContain(REFERENCE);
    expect(await page.locator('.srs-card__rating-btn').count()).toBe(0);
    available = true;
    await page.locator('.srs-card__btn--primary').click();
    await expect.poll(() => page.locator('.srs-card__explanation-body').first().textContent()).toBe(REFERENCE);
    await expect.poll(() => page.locator('.srs-card__rating-btn--hard').isEnabled(), { timeout: 5000 }).toBe(true);
    await page.locator('select').selectOption('boundary');
    await page.locator('.srs-card__rating-btn--hard').click();
    await expect.poll(() => requests.filter(request => request.path.endsWith('/quiz-answer')).length).toBe(1);
    expect(requests.find(request => request.path.endsWith('/quiz-answer'))?.body).toMatchObject({
      self_assessment: 'assisted', error_type: 'boundary', correct: null,
    });
  });

  it('fits a narrow screen and retains keyboard access without early rating', async () => {
    await page.setViewportSize({ width: 375, height: 812 });
    await mount('zh-CN');
    await page.locator('textarea').fill('用自己的话说明边界');
    await page.keyboard.press('3');
    expect(requests.some(request => request.path.endsWith('/quiz-answer'))).toBe(false);
    await page.locator('.srs-card__btn--primary').focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => page.locator('.srs-card__explanation').count()).toBe(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  });
});

const EMPTY_PRACTICE: ActivePracticeSummary = {
  initial: { attempts: 0, independent_rate: null },
  delayed_recall: { attempts: 0, independent_rate: null },
  unseen_variant: { attempts: 0, independent_rate: null },
  error_types: { none: 0, recall: 0, application: 0, reasoning: 0, boundary: 0 },
  feedback_kind: 'self_reported',
};

describe('practice measurement display', () => {
  it.each(['en', 'zh-CN'] as const)('distinguishes unmeasured rates from observed zero in %s', async locale => {
    await page.goto(`${baseUrl}${TEST_PATH}`);
    await page.waitForFunction(() => window.__activeReady);
    await page.evaluate(({ summary, locale }) => window.__mountMetrics(summary, locale), { summary: EMPTY_PRACTICE, locale });
    await expect.poll(() => page.locator('.practice-metrics .kpi').count()).toBe(3);
    const emptyText = await page.locator('.practice-metrics').textContent();
    expect(emptyText).toContain(locale === 'en' ? 'Not measured' : '未测量');
    expect(emptyText).not.toContain('0%');
    const measured: ActivePracticeSummary = { ...EMPTY_PRACTICE,
      initial: { attempts: 2, independent_rate: 0 },
      unseen_variant: { attempts: 2, independent_rate: 0.5 },
      error_types: { none: 1, recall: 1, application: 1, reasoning: 0, boundary: 1 },
    };
    await page.evaluate(({ summary, locale }) => window.__mountMetrics(summary, locale), { summary: measured, locale });
    await expect.poll(() => page.locator('.practice-metrics .kpi').first().textContent()).toContain('0%');
    expect(await page.locator('.practice-metrics .kpi').nth(1).textContent()).toContain(locale === 'en' ? 'Not measured' : '未测量');
    expect(await page.locator('.practice-metrics .kpi').nth(2).textContent()).toContain('50%');
    expect(await page.locator('.practice-metrics__errors dd').allTextContents()).toEqual(['1', '1', '1', '0', '1']);
    expect(await page.locator('.practice-metrics').textContent()).toContain(locale === 'en' ? 'self-reported' : '自报告');
    await page.setViewportSize({width: 375, height: 812});
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  });
});

describe('practice route and card identity', () => {
  it.each(['browser shortcut', 'select input'] as const)(
    'does not treat a %s as a quiz rating',
    async inputKind => {
      await installServeMock(page);
      await page.route('**/api/run/run-1/quiz/questions', route => route.fulfill({ json: {
        run_id: 'run-1', questions: [{ question_id: QUIZ.question_id, review_card_id: QUIZ.review_card_id,
          question: QUESTION, quiz_kind: 'transfer', exercise_kind: 'completion',
          scenario_kind: 'new_variant', answer_mode: 'open', choices: null }],
      } }));
      await page.route('**/api/run/run-1/quiz/quiz-practice/reveal', route => route.fulfill({ json: {
        run_id: 'run-1', question: QUIZ, correct: null, feedback_kind: 'semantic_self_assessment',
      } }));
      await page.goto(`${baseUrl}${TEST_PATH}`);
      await page.waitForFunction(() => window.__activeReady);
      await page.evaluate(() => window.__mountQuizRoute('run-1'));
      await expect.poll(() => page.locator('textarea').count()).toBe(1);
      await page.locator('textarea').fill('My own attempt');
      await page.locator('.srs-card__btn--primary').click();
      await expect.poll(() => page.locator('.srs-card__rating-btn--good').isEnabled(), { timeout: 5000 }).toBe(true);
      if (inputKind === 'select input') {
        await page.locator('.practice-error-select').focus();
        await page.keyboard.press('3');
      } else {
        await page.locator('.srs-card__question').click();
        await page.keyboard.press('Control+3');
        await page.keyboard.press('Meta+3');
        await page.keyboard.press('Alt+1');
      }
      await page.waitForTimeout(100);
      expect(requests.filter(request => request.path.endsWith('/quiz-answer') || request.path.endsWith('/srs-review'))).toEqual([]);
      expect(await page.locator('.srs-card__rating-btn--good').isEnabled()).toBe(true);
    },
  );

  it.each(['quiz-answer', 'srs-review'] as const)(
    'does not complete a new run when the previous run %s response arrives late',
    async pendingSignal => {
      await installServeMock(page);
      const publicQuestion = { question_id: QUIZ.question_id, review_card_id: QUIZ.review_card_id,
        question: QUESTION, quiz_kind: 'transfer', exercise_kind: 'completion',
        scenario_kind: 'new_variant', answer_mode: 'open', choices: null };
      let release: (() => void) | undefined;
      const pending = new Promise<void>(resolve => { release = resolve; });
      await page.route('**/api/run/run-A/quiz/questions', route => route.fulfill({ json: {
        run_id: 'run-A', questions: [publicQuestion],
      } }));
      await page.route('**/api/run/run-A/quiz/quiz-practice/reveal', route => route.fulfill({ json: {
        run_id: 'run-A', question: QUIZ, correct: null, feedback_kind: 'semantic_self_assessment',
      } }));
      await page.route('**/api/run/run-B/quiz/questions', route => route.fulfill({ json: {
        run_id: 'run-B', questions: [{ ...publicQuestion, question: 'B has not been attempted',
          review_card_id: 'card_exercise_B' }],
      } }));
      await page.route(`**/api/signals/${pendingSignal}`, async route => {
        await pending;
        await route.fulfill({ json: { inserted: true } }).catch(() => {});
      });
      await page.goto(`${baseUrl}${TEST_PATH}`);
      await page.waitForFunction(() => window.__activeReady);
      await page.evaluate(() => window.__mountQuizRoute('run-A'));
      await expect.poll(() => page.locator('textarea').count()).toBe(1);
      await page.locator('textarea').fill('Attempt at A');
      await page.locator('.srs-card__btn--primary').click();
      await expect.poll(() => page.locator('.srs-card__rating-btn--good').isEnabled(), { timeout: 5000 }).toBe(true);
      await page.locator('.srs-card__rating-btn--good').click();
      await expect.poll(() => requests.filter(request => request.path.endsWith(`/${pendingSignal}`)).length).toBe(1);
      await page.evaluate(() => window.__navigateQuiz('/run/run-B/quiz'));
      await expect.poll(() => page.locator('.srs-card__question').textContent()).toBe('B has not been attempted');
      const settled = page.waitForResponse(response => new URL(response.url()).pathname === `/api/signals/${pendingSignal}`);
      release?.();
      await (await settled).finished();
      await page.waitForTimeout(100);
      expect(await page.locator('.quiz-progress-badge--done').count()).toBe(0);
      expect(await page.locator('.quiz-page__progress--summary').count()).toBe(0);
      expect(requests.filter(request => request.path.endsWith('/srs-review'))).toHaveLength(
        pendingSignal === 'srs-review' ? 1 : 0,
      );
    },
  );

  it('never rates B when A assessment finishes after the learner switched cards', async () => {
    let release: (() => void) | undefined;
    const submitted = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/api/run/run-1/quiz/quiz-practice/reveal', route => route.fulfill({json:{
      run_id:'run-1',question:{...QUIZ,question:'Attempt A',review_card_id:'card_exercise_A'},correct:null,feedback_kind:'semantic_self_assessment',
    }}));
    await page.route('**/api/signals/quiz-answer', async route => {
      await submitted;
      await route.fulfill({json:{inserted:true}}).catch(() => {});
    });
    await page.goto(`${baseUrl}${TEST_PATH}`);
    await page.waitForFunction(() => window.__activeReady);
    await page.evaluate(() => window.__mountReviewExercise());
    await expect.poll(() => page.locator('textarea').count()).toBe(1);
    await page.locator('textarea').fill('Attempt at A');
    await page.locator('.srs-card__btn--primary').click();
    await expect.poll(() => page.locator('.srs-card__rating-btn--good').isEnabled(), {timeout:5000}).toBe(true);
    await page.locator('.srs-card__rating-btn--good').click();
    await expect.poll(() => requests.filter(request => request.path.endsWith('/quiz-answer')).length).toBe(1);
    await page.evaluate(() => window.__selectReviewExercise('card_exercise_B'));
    await expect.poll(() => page.locator('.srs-card__question').textContent()).toBe('Attempt B');
    const settled = page.waitForResponse(response => new URL(response.url()).pathname === '/api/signals/quiz-answer');
    release?.();
    await (await settled).finished();
    await page.waitForTimeout(50);
    await page.waitForFunction(() => !document.querySelector('.srs-card')?.getAttribute('aria-busy') || document.querySelector('.srs-card')?.getAttribute('aria-busy') === 'false');
    expect(requests.filter(request => request.path.endsWith('/review/rate'))).toEqual([]);
    expect(await page.locator('.srs-card__question').textContent()).toBe('Attempt B');
  });

  it('does not fetch B answer artifacts while its public questions are still loading after completed A', async () => {
    await installServeMock(page);
    const publicQuestion = {question_id:'quiz-practice',question:QUESTION,quiz_kind:'transfer',
      exercise_kind:'completion',scenario_kind:'new_variant',answer_mode:'open',choices:null};
    let releaseB: (() => void) | undefined;
    const pendingB = new Promise<void>(resolve => { releaseB = resolve; });
    await page.route('**/api/run/run-A/quiz/questions', route => route.fulfill({json:{run_id:'run-A',questions:[publicQuestion]}}));
    await page.route('**/api/run/run-A/quiz/quiz-practice/reveal', route => route.fulfill({json:{run_id:'run-A',question:{...QUIZ,review_card_id:undefined},correct:null,feedback_kind:'semantic_self_assessment'}}));
    await page.route('**/api/run/run-B/quiz/questions', async route => {
      await pendingB;
      await route.fulfill({json:{run_id:'run-B',questions:[{...publicQuestion,question:'B has not been attempted'}]}}).catch(() => {});
    });
    await page.goto(`${baseUrl}${TEST_PATH}`);
    await page.waitForFunction(() => window.__activeReady);
    await page.evaluate(() => window.__mountQuizRoute('run-A'));
    await expect.poll(() => page.locator('textarea').count()).toBe(1);
    await page.locator('textarea').fill('Attempt at A');
    await page.locator('.srs-card__btn--primary').click();
    await expect.poll(() => requests.some(request => request.path === '/api/run/run-A/misconceptions')).toBe(true);
    await page.evaluate(() => window.__navigateQuiz('/run/run-B/quiz'));
    await expect.poll(() => requests.some(request => request.path === '/api/run/run-B/quiz/questions')).toBe(true);
    expect(requests.some(request => request.path === '/api/run/run-B/misconceptions')).toBe(false);
    releaseB?.();
    await expect.poll(() => page.locator('.srs-card__question').textContent()).toBe('B has not been attempted');
    expect(requests.some(request => request.path === '/api/run/run-B/misconceptions')).toBe(false);
  });
});
