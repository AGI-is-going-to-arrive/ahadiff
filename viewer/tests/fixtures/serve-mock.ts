import type { Page, Request } from '@playwright/test';

const SAMPLE_DIFF = `diff --git a/demo.py b/demo.py
index 0000001..0000002 100644
--- a/demo.py
+++ b/demo.py
@@ -1,3 +1,4 @@
 def hello():
-    return "world"
+    return "AhaDiff"
+    # learn-from-diff
`;

function extractCookieLocale(req: Request): string {
  const cookie = req.headers()['cookie'] ?? '';
  const match = /(?:^|;\s*)ahadiff_lang=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]!) : 'en';
}

/**
 * Install minimal serve API mocks.
 *
 * NOTE: route predicates use `URL.pathname` equality instead of glob patterns.
 * Glob like `**\/api/runs**` over-matches and intercepts Vite's source module
 * requests (e.g. `/src/api/runs.ts`), returning JSON for what should be a JS
 * module and breaking React boot.
 */
export async function installServeMock(page: Page): Promise<void> {
  // Phase 2H: viewer ensureToken() POSTs to /api/auth/token.
  // Mock fulfils both POST (default) and GET (legacy compatibility).
  await page.route(
    (url) => url.pathname === '/api/auth/token',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ token: 'test-token-xxx' }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/locale',
    async (route) => {
      const req = route.request();
      if (req.method() === 'PUT') {
        // Mirror real backend (routes_locale.py:21-36): 200 + JSONResponse(LocaleResponse).
        let lang = 'en';
        try {
          const body = req.postDataJSON() as { lang?: string } | null;
          if (body?.lang === 'en' || body?.lang === 'zh-CN') lang = body.lang;
        } catch {
          // ignore malformed test bodies
        }
        // route.fulfill Set-Cookie is not always written into the BrowserContext
        // cookie store under WebKit + Playwright; explicitly sync via addCookies
        // so document.cookie reads after page.reload() are cross-browser consistent
        // with what the real backend (routes_locale.py) sets.
        await page.context().addCookies([
          {
            name: 'ahadiff_lang',
            value: lang,
            url: 'http://localhost:5173/',
            sameSite: 'Lax',
          },
        ]);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ locale: lang }),
        });
        return;
      }
      const locale = extractCookieLocale(req);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ locale }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === '/api/runs',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ runs: [] }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/ratchet/history',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          history: [
            { run_id: 'run-h1', source_ref: 'HEAD~2', eval_bundle_version: 'bundle-v1', overall: 82, verdict: 'PASS', status: 'baseline', weakest_dim: 'evidence', timestamp: '2026-04-25T10:00:00Z', note_json: null },
            { run_id: 'run-h2', source_ref: 'HEAD~1', eval_bundle_version: 'bundle-v1', overall: 65, verdict: 'CAUTION', status: 'baseline', weakest_dim: 'conciseness', timestamp: '2026-04-26T12:00:00Z', note_json: null },
            { run_id: 'run-h3', source_ref: 'HEAD', eval_bundle_version: 'bundle-v2', overall: 78, verdict: 'PASS', status: 'baseline', weakest_dim: 'learnability', timestamp: '2026-04-27T08:00:00Z', note_json: null },
          ],
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/diff$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'diff',
          content: SAMPLE_DIFF,
          content_lang: 'en',
        }),
      }),
  );
  // RunDetail (used by Lesson page initial fetch)
  await page.route(
    (url) => /^\/api\/run\/[^/]+$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          source_kind: 'git_ref',
          source_ref: 'HEAD',
          content_lang: 'en',
          capability_level: 3,
          verdict: 'PASS',
          overall: 88,
          status: 'baseline',
          weakest_dim: 'evidence',
          created_at: '2026-04-25T00:00:00Z',
          degraded_flags: {},
          base_ref: 'HEAD~1',
          prompt_version: 'abc1234',
          eval_bundle_version: 'v1',
          note_json: null,
          artifacts: ['patch.diff', 'metadata.json', 'claims.jsonl'],
          graphify_mode: null,
          graphify_status: null,
          graphify_notes: null,
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/lesson$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'lesson',
          content: '# Sample lesson\n\nThis change adds a learn-from-diff comment.',
          content_lang: 'en',
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/claims$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'claims',
          content:
            '{"claim_id":"c1","verdict":"verified","file":"demo.py","line_start":4,"line_end":4,"statement":"adds learn-from-diff comment"}',
          content_lang: 'en',
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/quiz$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'quiz',
          content:
            '{"question_id":"quiz_1","review_card_id":"card_quiz_explicit_1","question":"What does the new comment indicate?","expected_answer":"A learn-from-diff marker","source_claims":["c1"],"concepts":["learn-from-diff"],"evidence":[{"file":"demo.py","line":4}],"explanation":"learn-from-diff marker tags the change for the lesson","answer_mode":"multiple_choice","choices":[{"label":"A","text":"A learn-from-diff marker","is_correct":true},{"label":"B","text":"A runtime debug flag","is_correct":false},{"label":"C","text":"A deprecation warning","is_correct":false},{"label":"D","text":"A type annotation","is_correct":false}]}\n{"question_id":"quiz_2","question":"Why was the return value changed?","expected_answer":"To brand the output as AhaDiff","source_claims":["c1"],"concepts":["branding"],"evidence":[{"file":"demo.py","line":3}],"explanation":"The string literal was updated from world to AhaDiff"}',
          content_lang: 'en',
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/misconceptions$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'misconceptions',
          content:
            '{"card_id":"m1","concept":"learn-from-diff","misconception":"The marker proves runtime behavior changed.","correction":"It only tags the diff for the lesson pipeline.","evidence_ref":"demo.py:4","severity":"low","safety_tags":[],"run_id":"test-run"}',
          content_lang: 'en',
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/score$/.test(url.pathname),
    (route) => {
      const runId = new URL(route.request().url()).pathname.split('/')[3] ?? 'test-run';
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          artifact_type: 'score',
          content: JSON.stringify({
            run_id: runId,
            source_ref: 'HEAD',
            source_kind: 'git_ref',
            capability_level: 3,
            degraded_flags: {},
            overall: 78,
            verdict: 'CAUTION',
            weakest_dim: 'conciseness',
            eval_bundle_version: 'bundle-v1',
            rubric_version: 'rubric-v1',
            dimensions: {
              accuracy: { score: 18, max_score: 20, reason: 'Strong code evidence linking.' },
              evidence: { score: 16, max_score: 20, reason: 'Most claims backed by file:line refs.' },
              diff_coverage: { score: 14, max_score: 20, reason: 'Covered 70% of changed lines.' },
              learnability: { score: 12, max_score: 15, reason: 'Good scaffolding but could be more concise.' },
              conciseness: { score: 8, max_score: 10, reason: 'Some sections are verbose.' },
              quiz_transfer: { score: 4, max_score: 5, reason: 'Quiz questions test understanding.' },
              spec_alignment: { score: 3, max_score: 5, reason: 'Aligned with program spec.' },
              safety_privacy: { score: 5, max_score: 5, reason: 'No sensitive data exposed.' },
            },
            hard_gates: {
              no_fabrication: { passed: true, detail: 'No fabricated claims detected.' },
            },
            notes: ['Overall strong lesson with good evidence.', 'Conciseness could be improved in section 2.'],
          }),
          content_lang: 'en',
        }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === '/api/concepts',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          artifact_type: 'concepts',
          content:
            '{"concept":"learn-from-diff","term_key":"learn-from-diff","display_name":"Learn-from-diff","related_claims":["c1"],"file_refs":["demo.py"]}',
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/concepts$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: 'test-run',
          artifact_type: 'concepts',
          content:
            '{"concept":"learn-from-diff","term_key":"learn-from-diff","display_name":"Learn-from-diff","related_claims":["c1"],"file_refs":["demo.py"]}',
          content_lang: 'en',
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/graph/status',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          enabled: true,
          source_exists: true,
          has_graph: true,
          freshness: 'fresh',
          node_count: 3,
          edge_count: 2,
          source_path: '.ahadiff/graphify/graph.json',
          provenance: {
            graph_sha256: 'abc123def456789012345678901234567890abcdef1234567890abcdef123456',
            import_time: '2026-05-02T00:00:00Z',
            parser_version: '1.0',
          },
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/graph/concepts',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: {
            enabled: true,
            source_exists: true,
            has_graph: true,
            freshness: 'fresh',
            node_count: 3,
            edge_count: 2,
            source_path: '.ahadiff/graphify/graph.json',
            provenance: {
              graph_sha256: 'abc123def456789012345678901234567890abcdef1234567890abcdef123456',
              import_time: '2026-05-02T00:00:00Z',
              parser_version: '1.0',
            },
          },
          nodes: [
            {
              id: 'n1',
              name: 'learn-from-diff',
              kind: 'function',
              file_path: 'demo.py',
              freshness: 'fresh',
              metadata: {},
            },
            {
              id: 'n2',
              name: 'retry-logic',
              kind: 'function',
              file_path: 'retry.py',
              freshness: 'fresh',
              metadata: {},
            },
            {
              id: 'n3',
              name: 'config-parser',
              kind: 'module',
              file_path: 'config.py',
              freshness: 'stale',
              metadata: {},
            },
          ],
          edges: [
            {
              id: 'n1->n2:0',
              source: 'n1',
              target: 'n2',
              relation: 'calls',
              weight: 1.0,
            },
            {
              id: 'n2->n3:1',
              source: 'n2',
              target: 'n3',
              relation: 'imports',
              weight: 0.5,
            },
          ],
          truncated: false,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/review/queue',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cards: [
            {
              card_id: 'card-1',
              concept: 'learn-from-diff',
              run_id: 'test-run',
              due_date: '2026-04-27T00:00:00Z',
              scaffolding_level: '3',
              display_path: 'demo.py',
              source_ref: 'HEAD',
              symbol: null,
              question: 'What does the useEffect cleanup function do in React?',
              answer: 'It runs when the component unmounts or before the effect re-runs, used for cleanup like cancelling subscriptions.',
              answer_mode: 'open',
              choices: null,
            },
            {
              card_id: 'card-2-mc',
              concept: 'learn-from-diff',
              run_id: 'test-run',
              due_date: '2026-04-27T00:00:00Z',
              scaffolding_level: '2',
              display_path: 'demo.py',
              source_ref: 'HEAD',
              symbol: 'demo.hello',
              question: 'What does the new comment indicate?',
              answer: 'A learn-from-diff marker',
              answer_mode: 'multiple_choice',
              choices: [
                { label: 'A', text: 'A learn-from-diff marker', is_correct: true },
                { label: 'B', text: 'A runtime debug flag', is_correct: false },
                { label: 'C', text: 'A deprecation warning', is_correct: false },
                { label: 'D', text: 'A type annotation', is_correct: false },
              ],
            },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/concepts/weak',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          concepts: [
            {
              card_id: 'c1',
              concept: 'circuit breaker',
              stability: 0.3,
              difficulty: 7.2,
              scaffolding_level: 'full',
              display_path: 'src/retry.py',
            },
            {
              card_id: 'c2',
              concept: 'backoff strategy',
              stability: 0.5,
              difficulty: 6.1,
              scaffolding_level: 'hint',
              display_path: 'src/http.py',
            },
          ],
          new_concepts: [
            {
              card_id: 'c-new',
              concept: 'idempotent retry',
              stability: 0,
              difficulty: 0,
              scaffolding_level: 'full',
              display_path: 'src/retry.py',
            },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/review/mastery',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          mastery: [
            {
              concept: 'idempotency',
              review_count: 5,
              avg_rating: 3.5,
              last_review: '2026-05-03T00:00:00Z',
            },
            {
              concept: 'retry with jitter',
              review_count: 3,
              avg_rating: 2.0,
              last_review: '2026-05-02T00:00:00Z',
            },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/config',
    (route) => {
      if (route.request().method() === 'PUT') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ updated: true, scope: 'session' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          lang: 'en',
          privacy_mode: 'strict_local',
          generate_provider: null,
          generate_model: 'gpt-5.4-mini',
          judge_provider: null,
          judge_model: 'gpt-5.4-mini',
          serve_port: 8384,
          key_status: { openai: 'configured' },
          capture: {
            max_files: 30,
            hard_limit: 3000,
            max_patch_bytes: 5000000,
            file_ranking: 'learning_value',
            symbol_extractor: 'auto',
          },
          llm: {
            input_token_budget: 100000,
            output_token_budget: 16000,
            request_timeout_seconds: 120,
            max_concurrent: 4,
            retry_attempts: 2,
            output_lang: 'auto',
          },
          learn: {
            learnability_threshold: 0.3,
            desired_retention: 0.9,
          },
        }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === '/api/doctor',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          summary_status: 'pass',
          checks: [
            { name: 'repo_root', status: 'pass', message: '.ahadiff/ exists', category: 'repo', details: {} },
            { name: 'sqlite_version', status: 'pass', message: 'SQLite 3.45.0', category: 'runtime', details: { version: '3.45.0' } },
            { name: 'config_valid', status: 'pass', message: 'Config loaded', category: 'config', details: {} },
            { name: 'review_db', status: 'pass', message: 'review.sqlite present', category: 'data', details: {} },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/install/targets',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          targets: [
            {
              name: 'claude',
              display_name: 'Claude Code',
              detected: true,
              platform_supported: true,
              status: 'installed',
              description: 'Claude Code CLI',
              error_message: null,
            },
            {
              name: 'codex',
              display_name: 'Codex CLI',
              detected: false,
              platform_supported: true,
              status: 'available',
              description: 'Codex CLI',
              error_message: null,
            },
            {
              name: 'cursor',
              display_name: 'Cursor',
              detected: false,
              platform_supported: true,
              status: 'available',
              description: 'Cursor IDE',
              error_message: null,
            },
          ],
          total: 3,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/providers',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          providers: [
            {
              alias: 'openai-gpt5',
              role: 'generate',
              provider_class: 'openai',
              provider_kind: 'openai',
              model_name: 'gpt-5.4-mini',
              base_url: 'https://api.openai.com/v1',
              api_key_env: 'OPENAI_API_KEY',
              key_status: 'configured',
              api_family: 'openai_chat',
              api_family_version: 'v1',
              probed: true,
              probed_max_context: 128000,
              probed_tpm: 1000000,
              probed_rpm: 500,
              probe_timestamp: '2026-04-30T11:59:00Z',
            },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/usage',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          models: [
            {
              provider_class: 'openai',
              model_id: 'gpt-5.4-mini',
              call_count: 42,
              total_input_tokens: 10000,
              total_output_tokens: 5000,
              total_cost_usd: 0.015,
            },
          ],
          total_calls: 42,
          total_input_tokens: 10000,
          total_output_tokens: 5000,
          total_cost_usd: 0.015,
          cache_hits: 8,
          cache_misses: 34,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/audit',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entries: [
            {
              timestamp: '2026-04-30T12:00:00Z',
              event_type: 'provider_call',
              provider_class: 'openai',
              model_id: 'gpt-5.4-mini',
              prompt_name: 'lesson_generate',
              input_tokens: 500,
              output_tokens: 200,
              cost_usd: 0.001,
              cost_confidence: 'estimated',
              execution_origin: 'serve',
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
          page: 1,
          has_more: false,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/stats',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_runs: 3,
          total_lessons: 3,
          total_quizzes: 2,
          total_concepts: 8,
          total_claims: 5,
          total_reviews: 4,
          avg_overall_score: 75.0,
          weakest_dimensions: ['conciseness', 'evidence', 'quiz_transfer', 'learnability_and_scaffolding_quality'],
          last_run_at: '2026-05-03T00:00:00Z',
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/serve/status',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          version: '0.1.0a0',
          uptime_seconds: 12.5,
          review_db_exists: true,
          runs_count: 1,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/stats/learning',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_concepts_reviewed: 1,
          concepts_improving: 1,
          concepts_stable: 0,
          concepts_declining: 0,
          transfer_rate: 1.0,
          helpfulness: [
            {
              target_kind: 'section',
              target_id: 'test-run:intro',
              signal_count: 2,
              positive_count: 2,
              negative_count: 0,
              helpfulness_score: 1.0,
            },
          ],
          transfer_metrics: [
            {
              concept: 'learn-from-diff',
              total_reviews: 3,
              avg_rating: 2.7,
              improving: true,
            },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/spec/alignment',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          alignment_score: 84.2,
          total_evaluated: 4,
          recent_trend: 'stable',
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/watch/status',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          enabled: false,
          running: false,
          last_trigger_time: null,
          pending_changes: 0,
          restartable: true,
          stop_timed_out: false,
          consecutive_failures: 0,
          total_triggers: 0,
          total_failures: 0,
          last_error: null,
          failure_threshold_hit: false,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/review/heatmap',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entries: [
            { date: '2026-05-01', review_count: 3, avg_rating: 3.2 },
            { date: '2026-05-02', review_count: 5, avg_rating: 2.8 },
            { date: '2026-05-03', review_count: 1, avg_rating: 4.0 },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/signals/quiz-answer',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ inserted: true }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/signals/srs-review',
    (route) => {
      const body = route.request().postDataJSON() as {
        answer?: string;
        card_id?: string;
        peeked_this_session?: boolean;
      } | null;
      if (
        body?.peeked_this_session === true &&
        (body.answer === 'easy' || body.answer === 'good')
      ) {
        return route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            error: 'peeked cards cannot be reviewed as good or easy; use hard or wrong',
          }),
        });
      }
      if (body?.card_id !== 'card_quiz_explicit_1') {
        return route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({
            error: 'wrong_card_id',
            expected: 'card_quiz_explicit_1',
            received: body?.card_id ?? null,
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ inserted: true }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === '/api/review/rate',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ inserted: true }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/review/queue-state',
    (route) => {
      const body = route.request().postDataJSON() as {
        card_id?: string;
        state?: string;
      } | null;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          card_id: body?.card_id ?? 'card-1',
          state: body?.state ?? 'archived',
          updated: true,
        }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === '/api/tasks',
    (route) => {
      if (route.request().method() !== 'GET') {
        return route.fulfill({
          status: 405,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'method_not_allowed' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tasks: [] }),
      });
    },
  );
  await page.route(
    (url) => /^\/api\/tasks\/[^/]+$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'mock-task-001',
          task_type: 'learn',
          status: 'completed',
          progress: { current: 10, total: 10, message: 'Done' },
          result_summary: {
            run_id: 'test-run',
            status: 'completed',
            overall: 88,
            verdict: 'PASS',
            warnings: [],
          },
          error: null,
          error_code: null,
          created_at: '2026-04-27T00:00:00Z',
          started_at: '2026-04-27T00:00:01Z',
          completed_at: '2026-04-27T00:00:05Z',
          elapsed_seconds: 4,
          recovery_hint: null,
        }),
      }),
  );
  await page.route(
    (url) => /^\/api\/tasks\/[^/]+\/cancel$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ cancelled: true }),
      }),
  );
  await page.route(
    (url) => /^\/api\/tasks\/[^/]+\/progress$/.test(url.pathname),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body:
          'event: progress\n' +
          'data: {"event":"progress","data":{"task_id":"mock-task-001","task_type":"learn","status":"completed","progress":{"current":10,"total":10,"message":"Done"},"result_summary":{"run_id":"test-run","status":"completed","overall":88,"verdict":"PASS","warnings":[]},"error":null,"error_code":null,"created_at":"2026-04-27T00:00:00Z","started_at":"2026-04-27T00:00:01Z","completed_at":"2026-04-27T00:00:05Z","elapsed_seconds":4,"recovery_hint":null}}\n\n',
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/search',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ results: [], next_cursor: null }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/learn',
    (route) =>
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 'mock-task-001' }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/signals/mark-wrong',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ inserted: true }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/signals/helpfulness',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ inserted: true }),
      }),
  );
}
