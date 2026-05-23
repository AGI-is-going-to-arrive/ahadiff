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

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

interface MockConfigState {
  lang: string;
  privacy_mode: string;
  generate_provider: string | null;
  generate_model: string | null;
  judge_provider: string | null;
  judge_model: string | null;
  serve_port: number;
  key_status: Record<string, 'configured' | 'missing'>;
  capture: Record<string, string | number>;
  llm: Record<string, string | number>;
  learn: Record<string, number>;
  quiz: {
    quiz_question_count: number;
    quiz_question_count_mode: string;
    quiz_auto_range_min: number;
    quiz_auto_range_max: number;
  };
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
  const configState: MockConfigState = {
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
    quiz: {
      quiz_question_count: 3,
      quiz_question_count_mode: 'fixed',
      quiz_auto_range_min: 3,
      quiz_auto_range_max: 12,
    },
  };

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
            url: new URL(req.url()).origin,
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
    (url) => url.pathname === '/api/ratchet/transparency',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          results: [
            {
              run_id: 'run-h3',
              source_ref: 'HEAD',
              base_ref: 'HEAD~1',
              prompt_version: 'prompt-v2',
              eval_bundle_version: 'bundle-v2',
              rubric_version: 'rubric-v1',
              overall: 78,
              verdict: 'PASS',
              status: 'keep',
              weakest_dim: 'learnability',
              timestamp: '2026-04-27T08:00:00Z',
              note_json: '{"phase25":true,"phase25_note":"PHASE25: consecutive_discard_count=2","trigger_reason":"consecutive_discard_count=2","target_dimension":"learnability","targeted_baseline_score":65,"targeted_candidate_score":78,"targeted_passed":true}',
            },
            {
              run_id: 'run-h2',
              source_ref: 'HEAD~1',
              base_ref: 'HEAD~2',
              prompt_version: 'prompt-v1',
              eval_bundle_version: 'bundle-v1',
              rubric_version: 'rubric-v1',
              overall: 65,
              verdict: 'CAUTION',
              status: 'discard',
              weakest_dim: 'conciseness',
              timestamp: '2026-04-26T12:00:00Z',
              note_json: '{"targeted_reason":"score did not beat baseline"}',
            },
            {
              run_id: 'run-h1',
              source_ref: 'HEAD~2',
              base_ref: null,
              prompt_version: 'prompt-v1',
              eval_bundle_version: 'bundle-v1',
              rubric_version: 'rubric-v1',
              overall: 82,
              verdict: 'PASS',
              status: 'baseline',
              weakest_dim: 'evidence',
              timestamp: '2026-04-25T10:00:00Z',
              note_json: null,
            },
          ],
          benchmark: {
            manifest: {
              schema_version: 1,
              suite_id: 'ahadiff-local-v1',
              suite_digest: 'abc123def4567890',
              visibility: 'private',
              entry_count: 31,
              eval_entry_count: 20,
              integration_entry_count: 11,
              degraded_entry_count: 6,
              language_count: 8,
              group_count: 3,
            },
            report: {
              suite_id: 'ahadiff-local-v1',
              suite_digest: 'abc123def4567890',
              eval_bundle_version: 'bundle-v2',
              model_id: 'none',
              api_family_version: 'none',
              output_lang: 'en',
              comparable_entry_count: 14,
              excluded_degraded_count: 6,
              mean_score: 87.25,
              claim_verification_rate: 1,
              entries: [
                {
                  id: 'eval_001_python_retry',
                  group: 'benchmark_main',
                  language: 'python',
                  degraded: false,
                  overall: 91,
                  verdict: 'PASS',
                  weakest_dim: 'evidence',
                  claim_verification_rate: 1,
                  ground_truth_digest: 'f'.repeat(64),
                },
              ],
            },
            warnings: [],
          },
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
    (route) => {
      const runId = new URL(route.request().url()).pathname.split('/')[3] ?? 'test-run';
      const gateFailRun = runId === 'gate-fail-run';
      const artifacts = runId === 'no-score-run'
        ? ['patch.diff', 'metadata.json', 'claims.jsonl', 'concepts.jsonl']
        : runId === 'no-score-spec-run'
          ? ['patch.diff', 'metadata.json', 'claims.jsonl', 'concepts.jsonl', 'spec_alignment.json']
          : [
            'patch.diff',
            'metadata.json',
            'claims.jsonl',
            'score.json',
            'judge.json',
            'concepts.jsonl',
            'spec_alignment.json',
              'graphify_signoff.json',
            ];
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          source_kind: 'git_ref',
          source_ref: 'HEAD',
          content_lang: 'en',
          capability_level: 3,
          verdict: gateFailRun ? 'FAIL' : 'PASS',
          overall: gateFailRun ? 86.92 : 88,
          status: 'baseline',
          weakest_dim: gateFailRun ? 'diff_coverage' : 'evidence',
          created_at: '2026-04-25T00:00:00Z',
          degraded_flags: {},
          base_ref: 'HEAD~1',
          prompt_version: 'abc1234',
          eval_bundle_version: 'v1',
          note_json: null,
          artifacts,
          graphify_mode: null,
          graphify_status: null,
          graphify_notes: null,
        }),
      });
    },
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
            '{"question_id":"quiz_1","review_card_id":"card_quiz_explicit_1","question":"What does the new comment indicate?","expected_answer":"A learn-from-diff marker","quiz_kind":"recall","source_claims":["c1"],"concepts":["learn-from-diff"],"evidence":[{"file":"demo.py","line":4}],"explanation":"learn-from-diff marker tags the change for the lesson","answer_mode":"multiple_choice","choices":[{"label":"A","text":"A learn-from-diff marker","is_correct":true},{"label":"B","text":"A runtime debug flag","is_correct":false},{"label":"C","text":"A deprecation warning","is_correct":false},{"label":"D","text":"A type annotation","is_correct":false}]}\n{"question_id":"quiz_2","question":"Why was the return value changed?","expected_answer":"To brand the output as AhaDiff","quiz_kind":"transfer","source_claims":["c1"],"concepts":["branding"],"evidence":[{"file":"demo.py","line":3}],"explanation":"The string literal was updated from world to AhaDiff"}',
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
      if (runId === 'no-score-run' || runId === 'no-score-spec-run') {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'artifact_not_found', status: 404 }),
        });
      }
      if (runId === 'gate-fail-run') {
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
              overall: 86.92,
              verdict: 'FAIL',
              weakest_dim: 'diff_coverage',
              eval_bundle_version: 'bundle-v1',
              rubric_version: 'rubric-v1',
              dimensions: {
                accuracy: { score: 18.91, max_score: 20, reason: 'claim status mix' },
                evidence: { score: 16.17, max_score: 18, reason: 'claim evidence coverage' },
                diff_coverage: {
                  score: 7.25,
                  max_score: 14,
                  reason: 'claim anchors cover files and hunks from line_map.json',
                },
                learnability: { score: 11.9, max_score: 14, reason: 'capture metadata learnability score' },
                quiz_transfer: { score: 10, max_score: 10, reason: 'quiz artifact quality' },
                spec_alignment: { score: 0, max_score: 0, reason: 'not applicable' },
                conciseness: { score: 8, max_score: 8, reason: 'lesson artifact presence and length budgets' },
                safety_privacy: { score: 6, max_score: 6, reason: 'persisted patch passes checks' },
              },
              hard_gates: {
                evidence_coverage: {
                  passed: false,
                  detail: 'claim anchor coverage score 7.25 < 8.40; requires >= 8.40',
                  score: 7.25,
                  threshold: 8.4,
                },
                evidence: {
                  passed: true,
                  detail: 'evidence score 16.17 >= 12.00',
                  score: 16.17,
                  threshold: 12,
                },
              },
              notes: [],
            }),
            content_lang: 'en',
          }),
        });
      }
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
    (url) => /^\/api\/run\/[^/]+\/spec-alignment$/.test(url.pathname),
    (route) => {
      const runId = new URL(route.request().url()).pathname.split('/')[3] ?? 'test-run';
      if (runId === 'missing-spec-run') {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'artifact_not_found', status: 404 }),
        });
      }
      const content = runId === 'invalid-spec-run'
        ? '{not json'
        : runId === 'empty-spec-run'
          ? JSON.stringify({
              artifact: 'spec_alignment',
              schema: 'ahadiff.spec_alignment',
              schema_version: 1,
              applicability: 'applicable',
              status: 'scored',
              eval_bundle_version: 'bundle-v1',
              rubric_version: 'v0.1',
              spec_source: {
                path: 'SPEC.md',
                ref: 'SPEC.md',
                sha256: 'f'.repeat(64),
                bytes: 240,
              },
              spec_digest: 'f'.repeat(64),
              requirements: [],
              summary: { implemented: 0, partial: 0, missing: 0, unknown: 0 },
              score: 0,
              max_score: 10,
              confidence: 0,
              known_limitations: ['No requirements extracted.'],
            })
        : JSON.stringify({
            artifact: 'spec_alignment',
            schema: 'ahadiff.spec_alignment',
            schema_version: 1,
            applicability: 'applicable',
            status: 'scored',
            eval_bundle_version: 'bundle-v1',
            rubric_version: 'v0.1',
            spec_source: {
              path: 'SPEC.md',
              ref: 'SPEC.md',
              sha256: 'f'.repeat(64),
              bytes: 240,
            },
            spec_digest: 'f'.repeat(64),
            requirements: [
              {
                id: 'REQ-001',
                text: 'The lesson must explain the learn-from-diff marker.',
                classification: 'implemented',
                severity: 'medium',
                evidence_refs: [
                  {
                    type: 'claim',
                    claim_id: 'c1',
                    file: 'demo.py',
                    start: 4,
                    end: 4,
                    side: 'new',
                  },
                ],
                confidence: 0.9,
                reason: 'Verified claim overlaps the requirement.',
              },
              {
                id: 'REQ-002',
                text: 'The flow should include a transfer question.',
                classification: 'partial',
                severity: 'medium',
                evidence_refs: [],
                confidence: 0.6,
                reason: 'Captured diff overlaps requirement but evidence is incomplete.',
              },
            ],
            summary: { implemented: 1, partial: 1, missing: 0, unknown: 0 },
            score: 7.5,
            max_score: 10,
            confidence: 0.75,
            deterministic_result: {
              score: 7.5,
              summary: { implemented: 1, partial: 1, missing: 0, unknown: 0 },
            },
            semantic_review: {
              enabled: true,
              provider: 'openai_responses',
              model: 'gpt-5.5',
              prompt_digest: 'abc123',
              input_digest: 'def456',
              requirements: [
                {
                  id: 'REQ-001',
                  classification: 'implemented',
                  confidence: 0.84,
                  rationale: 'The listed claim evidence supports the requirement.',
                  evidence_refs: [
                    {
                      type: 'claim',
                      claim_id: 'c1',
                      file: 'demo.py',
                      start: 4,
                      end: 4,
                      side: 'new',
                    },
                  ],
                  disagreement_with_deterministic: false,
                },
                {
                  id: 'REQ-002',
                  classification: 'unknown',
                  confidence: 0.2,
                  rationale: 'No deterministic evidence reference was bound.',
                  evidence_refs: [],
                  disagreement_with_deterministic: true,
                },
              ],
              aggregate: {
                implemented: 1,
                partial: 0,
                missing: 0,
                unknown: 1,
                violated: 0,
                confidence: 0.52,
                risk_flags: ['deterministic_semantic_disagreement'],
              },
              degraded: false,
              degradation_reason: null,
              limitations: ['Semantic review is not a proof.'],
              usage: { input_tokens: 24, output_tokens: 18, finish_reason: 'stop' },
            },
            semantic_adjustment: {
              policy: 'conservative_evidence_bound',
              score: 7.5,
              delta: 0,
              reason: 'semantic review recorded; deterministic score retained',
            },
            known_limitations: ['Deterministic lexical matching only.'],
          });
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          artifact_type: 'spec_alignment',
          content,
          content_lang: 'en',
        }),
      });
    },
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/graphify-signoff$/.test(url.pathname),
    (route) => {
      const runId = new URL(route.request().url()).pathname.split('/')[3] ?? 'test-run';
      if (runId === 'missing-graphify-run') {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'artifact_not_found', status: 404 }),
        });
      }
      const content = runId === 'degraded-graphify-run'
        ? JSON.stringify({
            artifact: 'graphify_signoff',
            schema: 'ahadiff.graphify_signoff',
            schema_version: 1,
            run_id: runId,
            signoff: 'degraded',
            freshness: 'stale',
            graph_source: 'graphify-out/graph.json',
            graph_sha256: '',
            parser_version: 'v1',
            import_time: '2026-05-14T00:00:00Z',
            node_count: 3,
            edge_count: 2,
            source_coverage: {
              selected_files: 1,
              omitted_files: 0,
              graph_nodes: 3,
              graph_edges: 2,
            },
            degradation_reasons: ['graph_digest_missing', 'freshness_stale'],
            checks: [{ name: 'digest_present', passed: false, detail: '' }],
            known_limitations: ['Fixture limitation.'],
          })
        : JSON.stringify({
            artifact: 'graphify_signoff',
            schema: 'ahadiff.graphify_signoff',
            schema_version: 1,
            run_id: runId,
            signoff: 'passed',
            freshness: 'fresh',
            graph_source: 'graphify-out/graph.json',
            graph_sha256: 'a'.repeat(64),
            parser_version: 'v1',
            import_time: '2026-05-14T00:00:00Z',
            node_count: 12,
            edge_count: 9,
            source_coverage: {
              selected_files: 2,
              omitted_files: 0,
              graph_nodes: 12,
              graph_edges: 9,
            },
            degradation_reasons: [],
            checks: [{ name: 'digest_present', passed: true, detail: 'aaaaaaaaaaaa' }],
            known_limitations: ['Fixture limitation.'],
          });
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          artifact_type: 'graphify_signoff',
          content,
          content_lang: 'en',
        }),
      });
    },
  );
  await page.route(
    (url) => /^\/api\/run\/[^/]+\/judge$/.test(url.pathname),
    (route) => {
      const runId = new URL(route.request().url()).pathname.split('/')[3] ?? 'test-run';
      if (runId === 'missing-judge') {
        return route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'artifact_not_found', status: 404 }),
        });
      }
      if (runId === 'invalid-judge') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: runId,
            artifact_type: 'judge',
            content: '{not json',
            content_lang: 'en',
          }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: runId,
          artifact_type: 'judge',
          content: JSON.stringify({
            artifact: 'llm_judge',
            schema_version: 1,
            run_id: runId,
            source_ref: 'abc123',
            source_kind: 'git_ref',
            model_id: 'gpt-5.5',
            provider_class: 'openai_responses',
            prompt_fingerprint: 'prompt123',
            eval_bundle_version: 'bundle-v1',
            overall: runId === 'gate-fail-run' ? 92 : 91.5,
            notes: [
              'Overall strong lesson with good evidence.',
              'Second judge note confirms array rendering.',
            ],
            dimensions: {
              accuracy: { score: 18, max_score: 20, reason: 'Strong code evidence linking.' },
              evidence: { score: 16, max_score: 18, reason: 'Most claims backed by file:line refs.' },
              spec_alignment: {
                score: 0,
                max_score: 0,
                reason: 'not applicable in deterministic score',
              },
            },
            usage: {
              input_tokens: 123,
              output_tokens: 45,
            },
            finish_reason: 'stop',
            request_id: null,
          }),
          content_lang: 'en',
        }),
      });
    },
  );
  await page.route(
    (url) => url.pathname === '/api/improve/preflight',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          available: true,
          reason: null,
          anchor_run: {
            run_id: 'test-run',
            source_ref: 'abc123',
            overall: 80.5,
            weakest_dim: 'conciseness',
            finalized: true,
          },
          baseline_run: {
            run_id: 'baseline-run',
            source_ref: 'def456',
            overall: 75.2,
            weakest_dim: 'evidence',
            finalized: true,
          },
          target_dimension: 'conciseness',
          target_prompt_file: 'lesson_compact.md',
          mutable_prompts: [
            'claim_extract.md',
            'lesson_generate.md',
            'lesson_hint.md',
            'lesson_compact.md',
            'quiz_generate.md',
          ],
          phase25_eligible: false,
          phase25_trigger_reason: null,
          existing_sessions: [
            {
              session_id: 'session-001',
              rounds_completed: 1,
              last_status: 'discard',
              phase25_attempted: false,
              has_pending_worktree: false,
              interrupted_round: null,
              interrupted_stage: null,
              updated_at: '2026-05-08T10:00:00Z',
            },
          ],
          repo_state: {
            branch: 'main',
            head_sha: 'abc123def456',
            prompts_dirty: false,
          },
          provider_configured: true,
        }),
      }),
  );
  await page.route(
    (url) => url.pathname === '/api/concepts/ledger',
    (route) => {
      const url = new URL(route.request().url());
      const runFilter = url.searchParams.get('run');
      const cursor = Number(url.searchParams.get('cursor') ?? '0');
      const limit = Number(url.searchParams.get('limit') ?? '50');
      const allEntries = [
        {
          term_key: 'learn-from-diff',
          concept: 'learn-from-diff',
          display_name: 'Learn-from-diff',
          related_claims: ['c1'],
          file_refs: ['demo.py'],
          source_refs: ['abc123'],
          updated_by_runs: ['test-run'],
          graphify_node_id: 'node-learn-from-diff',
        },
        {
          term_key: 'branding',
          concept: 'branding',
          display_name: 'Branding',
          related_claims: ['c2'],
          file_refs: ['demo.py', 'config.py'],
          source_refs: ['def456'],
          updated_by_runs: ['test-run', 'test-run-2'],
          graphify_node_id: 'node-branding',
        },
      ];
      const filtered = runFilter
        ? allEntries.filter((entry) => entry.updated_by_runs.includes(runFilter))
        : allEntries;
      const entries = filtered.slice(cursor, cursor + limit);
      const nextCursor = cursor + limit < filtered.length ? String(cursor + limit) : null;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          entries,
          next_cursor: nextCursor,
          total_count: filtered.length,
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
              id: 'node-learn-from-diff',
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
              id: 'node-learn-from-diff->n2:0',
              source: 'node-learn-from-diff',
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
              stability: 4.5,
              difficulty: 6.25,
              reps: 2,
              lapses: 1,
              last_rating: 2,
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
        const body = asRecord(route.request().postDataJSON());
        const llm = asRecord(body.llm);
        const learn = asRecord(body.learn);
        const quiz = asRecord(body.quiz);
        const capture = asRecord(body.capture);
        if (Object.keys(llm).length > 0) {
          Object.assign(configState.llm, llm);
        }
        if (Object.keys(learn).length > 0) {
          Object.assign(configState.learn, learn);
        }
        if (Object.keys(quiz).length > 0) {
          Object.assign(configState.quiz, quiz);
        }
        if (Object.keys(capture).length > 0) {
          Object.assign(configState.capture, capture);
        }
        if (typeof body.lang === 'string') configState.lang = body.lang;
        if (typeof body.privacy_mode === 'string') configState.privacy_mode = body.privacy_mode;
        if (typeof body.generate_provider === 'string') configState.generate_provider = body.generate_provider;
        if (typeof body.generate_model === 'string') configState.generate_model = body.generate_model;
        if (typeof body.judge_provider === 'string') configState.judge_provider = body.judge_provider;
        if (typeof body.judge_model === 'string') configState.judge_model = body.judge_model;
        if (typeof body.serve_port === 'number') configState.serve_port = body.serve_port;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ updated: true, scope: 'session' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(configState),
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
  const installTargetNames = [
    'aider',
    'antigravity',
    'antigravity-cli',
    'claude',
    'cline',
    'codex',
    'continue',
    'copilot',
    'cursor',
    'gemini',
    'github-action',
    'hooks',
    'opencode',
    'roo',
    'windsurf',
  ];
  const manifestHashes: Record<string, string> = Object.fromEntries(
    installTargetNames.map((name, index) => [
      name,
      String.fromCharCode(97 + (index % 26)).repeat(64),
    ]),
  );
  const installState: Record<string, 'installed' | 'available'> = {
    claude: 'installed',
    codex: 'available',
    cursor: 'available',
  };
  const displayNames: Record<string, string> = {
    antigravity: 'Antigravity IDE',
    'antigravity-cli': 'Antigravity CLI',
    claude: 'Claude Code',
    codex: 'Codex CLI',
    copilot: 'Copilot / VS Code',
    cursor: 'Cursor',
    'github-action': 'GitHub Actions',
  };
  const manifestFor = (name: string) => {
    if (name === 'codex') {
      return {
        preview: [{ action: 'preview', file_strategy: 'user-managed', path: 'AGENTS.md' }],
        write: [{ action: 'append-section', file_strategy: 'user-managed', path: 'AGENTS.md' }],
        uninstall: [{ action: 'remove-section', file_strategy: 'user-managed', path: 'AGENTS.md' }],
      };
    }
    if (name === 'antigravity') {
      return {
        preview: [
          {
            action: 'write',
            file_strategy: 'generated',
            path: '.agents/skills/ahadiff-antigravity/SKILL.md',
          },
          { action: 'write', file_strategy: 'generated', path: '.agents/rules/ahadiff.md' },
        ],
        write: [
          {
            action: 'write',
            file_strategy: 'generated',
            path: '.agents/skills/ahadiff-antigravity/SKILL.md',
          },
          { action: 'write', file_strategy: 'generated', path: '.agents/rules/ahadiff.md' },
        ],
        uninstall: [
          {
            action: 'remove',
            file_strategy: 'generated',
            path: '.agents/skills/ahadiff-antigravity/SKILL.md',
          },
          { action: 'remove', file_strategy: 'generated', path: '.agents/rules/ahadiff.md' },
        ],
      };
    }
    if (name === 'antigravity-cli') {
      return {
        preview: [
          {
            action: 'write',
            file_strategy: 'generated',
            path: '.agents/skills/ahadiff-antigravity-cli/SKILL.md',
          },
          { action: 'merge-section', file_strategy: 'user-managed', path: 'GEMINI.md' },
        ],
        write: [
          {
            action: 'write',
            file_strategy: 'generated',
            path: '.agents/skills/ahadiff-antigravity-cli/SKILL.md',
          },
          { action: 'merge-section', file_strategy: 'user-managed', path: 'GEMINI.md' },
        ],
        uninstall: [
          {
            action: 'remove',
            file_strategy: 'generated',
            path: '.agents/skills/ahadiff-antigravity-cli/SKILL.md',
          },
          { action: 'remove-section', file_strategy: 'user-managed', path: 'GEMINI.md' },
        ],
      };
    }
    return {
      preview: [
        { action: 'preview', file_strategy: 'user-managed', path: `${name}/manifest.md` },
      ],
      write: [
        { action: 'write', file_strategy: 'generated', path: `${name}/manifest.md` },
      ],
      uninstall: [
        { action: 'remove', file_strategy: 'generated', path: `${name}/manifest.md` },
      ],
    };
  };
  const targetFor = (name: string) => ({
    name,
    display_name: displayNames[name] ?? name,
    detected: installState[name] === 'installed',
    platform_supported: true,
    status: installState[name] ?? 'available',
    description: `${displayNames[name] ?? name} project guidance`,
    install_command: `ahadiff install ${name}`,
    uninstall_command: `ahadiff uninstall ${name}`,
    manifest: manifestFor(name),
    manifest_hash: manifestHashes[name],
    manifest_error: null,
    error_message: null,
  });
  await page.route(
    (url) => url.pathname === '/api/install/targets',
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          targets: installTargetNames.map(targetFor),
          total: installTargetNames.length,
        }),
      }),
  );
  await page.route(
    (url) =>
      url.pathname !== '/api/install/targets' &&
      url.pathname.startsWith('/api/install/'),
    async (route) => {
      try {
        const req = route.request();
        if (req.method() !== 'POST') {
          await route.fulfill({ status: 405, contentType: 'application/json', body: JSON.stringify({ error: 'method_not_allowed' }) });
          return;
        }
        const parts = new URL(req.url()).pathname.split('/').filter(Boolean);
        const name = decodeURIComponent(parts[2] ?? '');
        if (!(name in installState)) {
          await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: 'unknown target' }) });
          return;
        }
        if (parts[3] === 'preview') {
          await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ target: targetFor(name), manifest_hash: manifestHashes[name] }),
          });
          return;
        }
        const body = (req.postDataJSON() ?? {}) as { confirmed_manifest_hash?: string };
        if (body.confirmed_manifest_hash !== manifestHashes[name]) {
          await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'confirmed_manifest_hash mismatch' }) });
          return;
        }
        const operation = parts[3] === 'uninstall' ? 'uninstall' : 'install';
        installState[name] = operation === 'install' ? 'installed' : 'available';
        const manifest = manifestFor(name);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            target: targetFor(name),
            operation,
            updated: true,
            updated_paths: manifest[operation === 'install' ? 'write' : 'uninstall'].map((action) => action.path),
            manifest_hash: manifestHashes[name],
          }),
        });
      } catch (error) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            error: error instanceof Error ? error.message : 'install mock failed',
          }),
        });
      }
    },
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
          alignment_score: 8.4,
          total_evaluated: 4,
          recent_trend: 'stable',
          total_requirements: 12,
          implemented: 8,
          partial: 2,
          missing: 1,
          unknown: 1,
          degraded_count: 0,
          semantic_reviewed: 1,
          semantic_degraded_count: 0,
          semantic_disagreement_count: 1,
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
