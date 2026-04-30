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
        body: JSON.stringify({ history: [] }),
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
            '{"question_id":"quiz_1","review_card_id":"card_quiz_explicit_1","question":"What does the new comment indicate?","expected_answer":"A learn-from-diff marker","source_claims":["c1"],"concepts":["learn-from-diff"],"evidence":[{"file":"demo.py","line":4}],"explanation":"learn-from-diff marker tags the change for the lesson"}',
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
            },
          ],
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/config',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          lang: 'en',
          privacy_mode: 'strict_local',
          generate_model: 'gpt-5.4-mini',
          judge_model: 'gpt-5.4-mini',
          serve_port: 8384,
          key_status: { openai: 'configured' },
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/doctor',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          checks: [
            { name: 'repo_root', status: 'pass', message: '.ahadiff/ exists' },
            { name: 'sqlite_version', status: 'pass', message: 'SQLite 3.45.0' },
            { name: 'config_valid', status: 'pass', message: 'Config loaded' },
            { name: 'review_db', status: 'pass', message: 'review.sqlite present' },
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
            { name: 'claude', detected: true, platform_supported: true, description: 'Claude Code CLI' },
            { name: 'codex', detected: false, platform_supported: true, description: 'Codex CLI' },
            { name: 'cursor', detected: false, platform_supported: true, description: 'Cursor IDE' },
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
}
