/**
 * OnboardingPage unit tests.
 *
 * The viewer suite has no jsdom / @testing-library/react. All other tests in
 * this codebase use `renderToStaticMarkup` for SSR-style rendering. Inside
 * `renderToStaticMarkup`, React's `useEffect` does NOT fire, so we cannot
 * exercise the doctor-fetch effect normally.
 *
 * This file injects local diagnostic and setup states via a partial mock of
 * `react`, then renders the page. Provider selection is also checked through
 * its pure resolver; asynchronous refresh is covered by the browser suite.
 * Other components used in the tree (AppShell,
 * CommandBlock, Skeleton) are mocked to passthroughs so they don't consume
 * `useState` slots.
 *
 * Click handlers cannot be exercised without a DOM, so the "Skip CTA" and
 * "hash chip → scrollIntoView" scenarios are verified via:
 *   1. observable rendered output across different initial states (Skip
 *      visibility), and
 *   2. source-level grep against `OnboardingPage.tsx` (scrollIntoView is
 *      wired into `SectionNav.handleJump`).
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { DoctorCheck, DbCheckResult, ProviderSummary } from '../../api/config';
import type { RunSummary } from '../../api/types';
import type { ProviderSetupStatus } from '../OnboardingPage';

const runState = vi.hoisted(() => ({
  runs: [] as RunSummary[],
  loadRuns: async (): Promise<void> => undefined,
  loading: false,
  error: null as string | null,
  lastLoadedAt: 1 as number | null,
}));

vi.mock('../../state/runs-store', () => ({
  useRunsStore: <T,>(selector: (state: typeof runState) => T): T => selector(runState),
}));

/* ----------------------------- React state injection ----------------------------- */

const stateOverrides: unknown[] = [];
let stateCallCounter = 0;

vi.mock('react', async () => {
  const actual = await vi.importActual<typeof import('react')>('react');
  return {
    ...actual,
    useState: <S,>(initial: S | (() => S)) => {
      const idx = stateCallCounter++;
      const init =
        typeof initial === 'function' ? (initial as () => S)() : initial;
      const value = (idx < stateOverrides.length
        ? (stateOverrides[idx] as S)
        : init);
      // Uncomment for debugging:
      // console.log(`[useState mock] idx=${idx}, init=`, init, ' value=', value);
      const setter = (() => undefined) as unknown as (v: S) => void;
      return [value, setter] as [S, (v: S) => void];
    },
  };
});

/* ----------------------------- API + util mocks ----------------------------- */

const getDoctorMock = vi.fn();
const fetchDbCheckMock = vi.fn();

vi.mock('../../api/config', async () => {
  const actual = await vi.importActual<typeof import('../../api/config')>(
    '../../api/config',
  );
  return {
    ...actual,
    getDoctor: (...args: unknown[]) => getDoctorMock(...args),
    fetchDbCheck: (...args: unknown[]) => fetchDbCheckMock(...args),
  };
});

vi.mock('../../utils/platform', async () => {
  const actual = await vi.importActual<typeof import('../../utils/platform')>(
    '../../utils/platform',
  );
  return {
    ...actual,
    detectPlatform: () => 'linux' as const,
    getInstallCommand: () => 'pipx install ahadiff',
    getShellHint: () => 'Terminal',
    getEnvVarCommand: (_p: unknown, name: string, value: string) =>
      `export ${name}="${value}"`,
    getPlatformLabel: () => 'Linux',
  };
});

/* ----------------------------- Component passthroughs ----------------------------- */

vi.mock('../../components/AppShell', () => ({
  default: ({ children }: { children: ReactNode }) => (
    <div data-testid="app-shell-mock">{children}</div>
  ),
}));

vi.mock('../../components/CommandBlock', () => ({
  CommandBlock: ({ command }: { command: string }) => (
    <pre data-testid="cmd-mock">{command}</pre>
  ),
  default: ({ command }: { command: string }) => (
    <pre data-testid="cmd-mock">{command}</pre>
  ),
}));

vi.mock('../../components/Skeleton', () => ({
  default: () => <div data-testid="skeleton-mock" />,
}));

/* ----------------------------- i18n: keep real catalog (zh-CN) ----------------------------- */

vi.mock('../../i18n/useTranslation', async () => {
  const zhCNMessages = (await import('../../i18n/messages/zh-CN.json'))
    .default as Record<string, unknown>;
  function lookup(tree: Record<string, unknown>, dotKey: string): string | undefined {
    const parts = dotKey.split('.');
    let current: unknown = tree;
    for (const p of parts) {
      if (current && typeof current === 'object' && p in (current as Record<string, unknown>)) {
        current = (current as Record<string, unknown>)[p];
      } else {
        return undefined;
      }
    }
    return typeof current === 'string' ? current : undefined;
  }
  function interpolate(t: string, params?: Record<string, string | number>): string {
    if (!params) return t;
    return t.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`));
  }
  return {
    useTranslation: () => ({
      locale: 'zh-CN' as const,
      t: (key: string, params?: Record<string, string | number>): string => {
        const msg = lookup(zhCNMessages, key);
        return msg ? interpolate(msg, params) : key;
      },
    }),
  };
});

/* ----------------------------- Test fixtures ----------------------------- */

interface DoctorState {
  checks: DoctorCheck[];
  loading: boolean;
}

interface DbCheckState {
  result: DbCheckResult | null;
  loading: boolean;
}

function makeCheck(
  name: string,
  status: 'pass' | 'warn' | 'fail',
  message = 'msg',
): DoctorCheck {
  return { name, status, message, category: 'env' };
}

const ALL_FAIL_CHECKS: DoctorCheck[] = [
  makeCheck('repo_root', 'fail'),
  makeCheck('config_valid', 'fail'),
  makeCheck('review_db', 'fail'),
];
const REPO_ONLY_CHECKS: DoctorCheck[] = [
  makeCheck('repo_root', 'pass'),
  makeCheck('config_valid', 'fail'),
];
const ALL_PASS_CHECKS: DoctorCheck[] = [
  makeCheck('repo_root', 'pass'),
  makeCheck('config_valid', 'pass'),
  makeCheck('review_db', 'pass'),
];
const MIXED_WARN_CHECKS: DoctorCheck[] = [
  makeCheck('repo_root', 'pass'),
  makeCheck('config_valid', 'pass'),
  makeCheck('review_db', 'warn'),
];

const HEALTHY_DB: DbCheckResult = {
  healthy: true,
  schema_version: 9,
  quick_check: 'ok',
  event_count: 12,
  card_count: 4,
};

const SETTLED_DB_LOAD: DbCheckState = { result: HEALTHY_DB, loading: false };
const SETTLED_DOCTOR_LOAD = (checks: DoctorCheck[]): DoctorState => ({
  checks,
  loading: false,
});

/**
 * Push initial states for local diagnostics, selected step, source dialog and
 * the independently checked provider configuration.
 */
function setStates(opts: {
  doctor: DoctorState;
  dbCheck?: DbCheckState;
  activeStep?: 1 | 2 | 3 | 4;
  activeStepTouched?: boolean;
  providerSetup?: ProviderSetupStatus;
}) {
  stateOverrides.length = 0;
  stateOverrides.push(opts.doctor);
  stateOverrides.push(opts.dbCheck ?? SETTLED_DB_LOAD);
  stateOverrides.push(opts.activeStep ?? 4);
  stateOverrides.push(opts.activeStepTouched ?? true);
  stateOverrides.push(null);
  stateOverrides.push(opts.providerSetup ?? 'configured');
}

async function renderPage(): Promise<string> {
  stateCallCounter = 0;
  const mod = await import('../OnboardingPage');
  const OnboardingPage = mod.default;
  // No MemoryRouter wrapper: OnboardingPage uses no router hooks directly,
  // and react-router's MemoryRouter consumes 3 useState slots which would
  // shift our state-injection ordering off by 3.
  return renderToStaticMarkup(<OnboardingPage />);
}

/* ----------------------------- beforeEach ----------------------------- */

beforeEach(() => {
  vi.clearAllMocks();
  // Default API mocks resolve to empty/healthy. useEffect won't fire under SSR
  // so these are mostly unused, but keep them safe in case any code path
  // touches them eagerly.
  getDoctorMock.mockResolvedValue({ summary_status: 'fail', checks: [] });
  fetchDbCheckMock.mockResolvedValue(HEALTHY_DB);
  stateOverrides.length = 0;
  stateCallCounter = 0;
  runState.runs = [];
  runState.loading = false;
  runState.error = null;
  runState.lastLoadedAt = 1;
});

afterEach(() => {
  stateOverrides.length = 0;
  stateCallCounter = 0;
});

/* ----------------------------- Tests ----------------------------- */

/**
 * Helper: extract `data-state` for a given onboarding step number from
 * rendered HTML. Rendered attribute order is:
 *   non-current → `data-state="X" data-testid="onboarding-step-Y"`
 *   current     → `data-state="current" aria-current="step" data-testid="onboarding-step-Y"`
 * (the JSX puts `aria-current="step"` only on the current `<li>`.)
 */
function getStepState(html: string, step: 1 | 2 | 3 | 4): string | null {
  const re = new RegExp(
    `data-state="([a-z]+)"(?:\\s+aria-current="step")?\\s+data-testid="onboarding-step-${step}"`,
  );
  const match = html.match(re);
  return match?.[1] ?? null;
}

describe('OnboardingPage stepper', () => {
  it.each(['missing', 'select', 'missing_key', 'error', 'loading'] as const)('valid TOML does not complete provider setup when it is %s', async providerSetup => {
    setStates({ doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS), activeStep: 2, providerSetup });
    const html = await renderPage();
    expect(getStepState(html, 2)).toBe('current');
    expect(getStepState(html, 4)).toBe('pending');
    expect(html).not.toContain('data-testid="onboarding-completion"');
  });
  it('renders 4 stepper items and marks active step current (all-fail → step 2 current)', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_FAIL_CHECKS),
      activeStep: 2,
    });
    const html = await renderPage();
    // 4 stepper items rendered
    const stepMatches = html.match(/data-testid="onboarding-step-[1-4]"/g) ?? [];
    expect(stepMatches.length).toBe(4);
    // The active step (2) should be marked current with aria-current
    expect(getStepState(html, 2)).toBe('current');
    expect(html).toMatch(/aria-current="step"/);
  });

  it('derives computedStep=1 when repo_root fails (all-fail fixture)', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_FAIL_CHECKS),
      activeStep: 1,
    });
    const html = await renderPage();
    expect(getStepState(html, 1)).toBe('current');
    expect(getStepState(html, 3)).toBe('pending');
    expect(getStepState(html, 4)).toBe('pending');
  });

  it('derives computedStep=2 when repo_root passes but config_valid fails', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(REPO_ONLY_CHECKS),
      activeStep: 2,
    });
    const html = await renderPage();
    expect(getStepState(html, 1)).toBe('done');
    expect(getStepState(html, 2)).toBe('current');
    expect(getStepState(html, 4)).toBe('pending');
  });

  it('derives computedStep=4 when both repo_root and config_valid pass (mixed warn)', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(MIXED_WARN_CHECKS),
      activeStep: 4,
    });
    const html = await renderPage();
    // Doctor cannot prove the optional agent was installed.
    expect(getStepState(html, 3)).toBe('pending');
    expect(getStepState(html, 4)).toBe('current');
    // No completion section because not all pass
    expect(html).not.toMatch(/data-testid="onboarding-completion"/);
  });
});

describe('OnboardingPage generation-provider configuration', () => {
  function provider(alias: string, overrides: Partial<ProviderSummary> = {}): ProviderSummary {
    return {
      alias, provider_class: 'ollama', provider_kind: 'ollama', model_name: 'local-model',
      base_url: 'http://127.0.0.1:11434', key_status: 'unknown', probed: false,
      probed_max_context: null, ...overrides,
    };
  }

  it('requires a provider even when a default generation model is present elsewhere in config', async () => {
    const { resolveProviderSetupStatus } = await import('../OnboardingPage');
    expect(resolveProviderSetupStatus({ generate_provider: null }, [])).toBe('missing');
  });

  it('allows a single configured provider without pretending a probe succeeded', async () => {
    const { resolveProviderSetupStatus } = await import('../OnboardingPage');
    expect(resolveProviderSetupStatus({ generate_provider: null }, [provider('local')])).toBe('configured');
  });

  it('requires a valid explicit alias among multiple providers and does not infer selection from role labels', async () => {
    const { resolveProviderSetupStatus } = await import('../OnboardingPage');
    const providers = [provider('first', { role: 'generate' }), provider('second', { role: 'judge' })];
    expect(resolveProviderSetupStatus({ generate_provider: '' }, providers)).toBe('select');
    expect(resolveProviderSetupStatus({ generate_provider: 'second' }, providers)).toBe('configured');
    expect(resolveProviderSetupStatus({ generate_provider: 'deleted' }, providers)).toBe('select');
    expect(resolveProviderSetupStatus({ generate_provider: 'deleted' }, [providers[0]])).toBe('select');
  });

  it('does not mark an explicitly missing key or incomplete provider as configured', async () => {
    const { resolveProviderSetupStatus } = await import('../OnboardingPage');
    expect(resolveProviderSetupStatus({ generate_provider: null }, [provider('local', { key_status: 'missing' })])).toBe('missing_key');
    expect(resolveProviderSetupStatus({ generate_provider: null }, [provider('local', { model_name: ' ' })])).toBe('missing');
  });
});

describe('OnboardingPage DiagnosticRow status mapping', () => {
  it('does not report database issues when the check returned no result', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS),
      dbCheck: { result: null, loading: false },
    });
    const html = await renderPage();
    expect(html).toContain('无法完成数据库检查');
    expect(html).not.toContain('数据库异常');
    expect(html).not.toContain('onboarding-db-row-health');
  });

  it('still reports database issues for an actual unhealthy result', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS),
      dbCheck: { result: { ...HEALTHY_DB, healthy: false, quick_check: 'check failed' }, loading: false },
    });
    const html = await renderPage();
    expect(html).toContain('数据库异常');
    expect(html).toMatch(/data-status="fail"\s+data-testid="onboarding-db-row-health"/);
    expect(html).not.toContain('无法完成数据库检查');
  });

  it('renders DiagnosticRow with data-status="pass" and aria-label "通过" for a passing check', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD([makeCheck('repo_root', 'pass')]),
    });
    const html = await renderPage();
    // The doctor card should contain a diag row with data-status="pass" and the
    // doctor-row testid (rendered attribute order: data-status before data-testid).
    expect(html).toMatch(/data-status="pass"\s+data-testid="onboarding-doctor-row"/);
    // SR-only label "通过" comes from zh-CN Onboarding.doctor_pass_label,
    // emitted as a sibling <span class="sr-only"> next to the aria-hidden svg.
    expect(html).toMatch(/<span\s+class="[^"]*sr-only[^"]*">通过[:：]\s*<\/span>/);
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
  });

  it('renders DiagnosticRow with data-status="warn" and aria-label "警告" for a warn check', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD([makeCheck('config_unknown_keys', 'warn')]),
    });
    const html = await renderPage();
    expect(html).toMatch(/data-status="warn"\s+data-testid="onboarding-doctor-row"/);
    expect(html).toMatch(/<span\s+class="[^"]*sr-only[^"]*">警告[:：]\s*<\/span>/);
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
  });

  it('renders DiagnosticRow with data-status="fail" and aria-label "失败" for a fail check', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD([makeCheck('repo_root', 'fail')]),
    });
    const html = await renderPage();
    expect(html).toMatch(/data-status="fail"\s+data-testid="onboarding-doctor-row"/);
    expect(html).toMatch(/<span\s+class="[^"]*sr-only[^"]*">失败[:：]\s*<\/span>/);
    expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
  });
});

describe('OnboardingPage completion logic', () => {
  it('shows onboarding-completion only when all doctor checks pass and computedStep=4', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS),
      activeStep: 4,
    });
    const html = await renderPage();
    expect(html).toMatch(/data-testid="onboarding-completion"/);
    // role=status + aria-live=polite live region
    expect(html).toMatch(/role="status"/);
  });

  it('hides onboarding-completion when any doctor check is warn (mixed-warn fixture)', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(MIXED_WARN_CHECKS),
      activeStep: 4,
    });
    const html = await renderPage();
    expect(html).not.toMatch(/data-testid="onboarding-completion"/);
  });

  it('does not render Next CTA when complete; renders complete CTA instead', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS),
      activeStep: 4,
    });
    const html = await renderPage();
    expect(html).not.toMatch(/data-testid="onboarding-cta-next"/);
    expect(html).toMatch(/data-testid="onboarding-cta-complete"/);
  });
});

describe('OnboardingPage Skip CTA visibility', () => {
  it('renders Skip CTA when computedStep > activeStep (and not complete)', async () => {
    setStates({
      // REPO_ONLY: repo_root pass, config_valid fail → computedStep=3.
      // isComplete is false (config_valid is fail), so onboarding-actions renders.
      doctor: SETTLED_DOCTOR_LOAD(REPO_ONLY_CHECKS),
      activeStep: 1, // explicit user navigation back to step 1
      activeStepTouched: true,
    });
    const html = await renderPage();
    expect(html).toMatch(/data-testid="onboarding-cta-skip"/);
  });

  it('hides Skip CTA when activeStep equals computedStep', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(REPO_ONLY_CHECKS), // computedStep=3
      activeStep: 3,
    });
    const html = await renderPage();
    expect(html).not.toMatch(/data-testid="onboarding-cta-skip"/);
  });
});

describe('OnboardingPage preview verdict score', () => {
  it('shows loading before the first run list has settled, rather than claiming there are no runs', async () => {
    runState.lastLoadedAt = null;
    const html = await renderPage();
    expect(html).toContain('正在加载学习记录');
    expect(html).not.toContain('还没有已完成的运行');
  });

  it('reports a list failure without echoing raw errors or claiming an empty history', async () => {
    runState.error = 'private schema details';
    const html = await renderPage();
    expect(html).toContain('无法加载学习记录');
    expect(html).toContain('重试加载记录');
    expect(html).not.toContain('private schema details');
    expect(html).not.toContain('还没有已完成的运行');
  });

  it('keeps an earlier run explicitly stale when refreshing fails', async () => {
    runState.error = 'private refresh error';
    runState.runs = [{
      run_id: 'run_earlier', source_ref: 'sha256:test', source_kind: 'file_compare',
      content_lang: 'zh-CN', capability_level: 2, verdict: 'PASS', overall: 91.25,
      status: 'non_ratcheted', weakest_dim: 'evidence', created_at: '2026-09-08T00:00:00Z',
      degraded_flags: {},
    }];
    const html = await renderPage();
    expect(html).toContain('run_earlier');
    expect(html).toContain('此前加载的记录');
    expect(html).toContain('无法刷新学习记录');
    expect(html).not.toContain('private refresh error');
    expect(html).not.toContain('最近一次学习');
    expect(html).not.toContain('还没有已完成的运行');
  });

  it('shows an empty state without invented score, diff or specification counts', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_FAIL_CHECKS),
      activeStep: 2,
    });
    const html = await renderPage();
    expect(html).toContain('还没有已完成的运行');
    expect(html).not.toContain('onboarding-preview-verdict-badge');
    expect(html).not.toContain('PKCE');
    expect(html).not.toContain('+187');
  });

  it.each(['PASS', 'FAIL'] as const)('shows the persisted %s verdict beside the actual score', async (verdict) => {
    runState.runs = [{
      run_id: 'run_uploaded', source_ref: 'sha256:test', source_kind: 'file_compare',
      content_lang: 'zh-CN', capability_level: 2, verdict, overall: 91.25,
      status: 'non_ratcheted', weakest_dim: 'evidence', created_at: '2026-09-08T00:00:00Z',
      degraded_flags: {},
    }];
    const html = await renderPage();
    expect(html).toContain(`verdict-badge--${verdict}`);
    expect(html).toContain('91.25');
    expect(html).toContain('两份文件');
    expect(html).toContain('#/run/run_uploaded');
    expect(html).not.toContain('8 项需求');
    expect(html).not.toContain('+187');
    expect(html).not.toContain('verdict-badge--CAUTION');
  });
});

describe('OnboardingPage no literal "i" used as info icon', () => {
  it('renders info DiagnosticRow with an svg icon (Lucide Info), not a bare letter "i"', async () => {
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS),
      activeStep: 4,
    });
    const html = await renderPage();
    // At least one info-tagged diag row exists (db schema row).
    expect(html).toMatch(/data-status="info"/);
    // Each diag row must contain an <svg ...> for its icon (Lucide renders SVG).
    // Pull the first info-row substring and assert <svg appears within it.
    const infoMatch = html.match(/data-status="info"[^]*?<\/div>\s*<\/div>/);
    expect(infoMatch).toBeTruthy();
    expect(infoMatch?.[0] ?? '').toContain('<svg');
    // Source-level guard: OnboardingPage source must not contain the literal
    // character 'i' wrapped as a JSX text child like ">i<" used as an icon.
    const src = readFileSync(
      resolve(__dirname, '..', 'OnboardingPage.tsx'),
      'utf-8',
    );
    // Forbid `>i<` (JSX text "i" between tags) and the literal string '"i"'.
    expect(src).not.toMatch(/>\s*i\s*</);
    expect(src).not.toMatch(/'\s*i\s*'|"\s*i\s*"/);
  });
});

describe('OnboardingPage hash chip jump behavior', () => {
  it('wires scrollIntoView for hash nav chips and respects prefers-reduced-motion', async () => {
    // Render the page so SectionNav is in the tree; then verify source.
    setStates({
      doctor: SETTLED_DOCTOR_LOAD(ALL_PASS_CHECKS),
      activeStep: 4,
    });
    const html = await renderPage();
    // Section nav chips with the documented section ids must be present.
    expect(html).toMatch(/data-testid="onboarding-nav-chip-steps"/);
    expect(html).toMatch(/data-testid="onboarding-nav-chip-diagnostics"/);
    expect(html).toMatch(/data-testid="onboarding-nav-chip-preview"/);
    // Source-level: SectionNav.handleJump uses scrollIntoView with reduced-motion guard.
    const src = readFileSync(
      resolve(__dirname, '..', 'OnboardingPage.tsx'),
      'utf-8',
    );
    expect(src).toContain('scrollIntoView');
    expect(src).toContain('prefers-reduced-motion');
    // Click handler must call e.preventDefault() so HashRouter does not hijack the chip.
    expect(src).toContain('e.preventDefault()');
  });
});
