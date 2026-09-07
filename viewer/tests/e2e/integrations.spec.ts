import { expect, test, type Page } from '@playwright/test';
import type { InstallTarget } from '../../src/api/config';
import { installServeMock } from '../fixtures/serve-mock';

function target(name: string, displayName: string, overrides: Partial<InstallTarget> = {}): InstallTarget {
  const path = name === 'deepseek-harness' ? '.dsh/skills/ahadiff/SKILL.md'
    : name === 'roo' ? '.roo/rules/ahadiff.md'
      : `.${name}/skills/ahadiff/SKILL.md`;
  const action = { action: 'write', file_strategy: 'generated' as const, path };
  return {
    name,
    display_name: displayName,
    detected: false,
    platform_supported: true,
    status: 'available',
    lifecycle: 'active',
    description: `Write native ${displayName} guidance.`,
    install_command: `ahadiff install ${name}`,
    uninstall_command: `ahadiff uninstall ${name}`,
    manifest: { preview: [action], write: [action], uninstall: [{ ...action, action: 'remove' }] },
    manifest_hash: 'a'.repeat(64),
    usage_hint: {
      tool_category: 'cli',
      invocation_pattern: `Start ${name} and use the AhaDiff skill.`,
      quick_start_steps: ['Open this workspace.'],
      example_prompts: [],
      expected_behavior: 'Generate verified learning output.',
      platform_notes: {},
    },
    ...overrides,
  };
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test.describe('guidance catalogue', () => {
  test.beforeEach(async ({ page }) => {
    await installServeMock(page);
  });

  test('Guide shares one live catalogue across both sections and uses native metadata', async ({ page }) => {
    const targets = [target('pi', 'Pi Agent'), target('deepseek-harness', 'DeepSeek Harness', {
      lifecycle: 'preview',
      lifecycle_note: 'Developer preview; select the workspace in dsh web.',
    })];
    let requests = 0;
    await page.route('**/api/install/targets', async route => {
      requests += 1;
      await route.fulfill({ json: { targets, total: targets.length, legacy_targets: [] } });
    });
    await page.goto('/#/guide');
    const cards = page.locator('.guide-agent-card');
    await expect(cards).toHaveCount(targets.length);
    await expect(cards.filter({ hasText: 'DeepSeek Harness' })).toContainText('Developer preview');
    const pi = cards.filter({ hasText: 'Pi Agent' });
    await pi.locator('button').focus();
    await page.keyboard.press('Enter');
    await expect(pi).toContainText('.pi/skills/ahadiff/SKILL.md');
    await expect(pi).toContainText('Write native Pi Agent guidance.');
    const integrations = page.locator('#integrations');
    await integrations.locator('summary').click();
    await expect(integrations.locator('.guide-integrations__item')).toHaveText(targets.map(item => item.display_name));
    expect(requests).toBe(1);
    await expectNoHorizontalOverflow(page);
  });

  test('Guide retries a failed catalogue without fabricating available tools', async ({ page }) => {
    let available = false;
    await page.route('**/api/install/targets', route => route.fulfill(available
      ? { json: { targets: [target('grok', 'Grok Build')], total: 1 } }
      : { status: 503, json: { error: 'temporarily unavailable' } }));
    await page.goto('/#/guide');
    const skills = page.locator('#agent-skills');
    await expect(skills.getByRole('alert')).toContainText('could not be loaded');
    await expect(page.locator('.guide-agent-card')).toHaveCount(0);
    await expect(page.locator('.guide-integrations__item')).toHaveCount(0);
    available = true;
    await skills.getByRole('button', { name: 'Retry catalogue' }).click();
    await expect(page.locator('.guide-agent-card')).toHaveCount(1);
    await expect(page.locator('.guide-agent-card')).toContainText('Grok Build');
    await expect(skills.getByRole('alert')).toHaveCount(0);
  });

  test('Guide preserves a successful empty directory in both sections', async ({ page }) => {
    await page.route('**/api/install/targets', route => route.fulfill({ json: { targets: [], total: 0 } }));
    await page.goto('/#/guide');
    await expect(page.locator('#agent-skills').getByRole('status')).toContainText('No AI guidance targets');
    await expect(page.locator('.guide-agent-card')).toHaveCount(0);
    await expect(page.locator('.guide-integrations__item')).toHaveCount(0);
  });

  test('Settings updates installed guidance through preview without removing it', async ({ page }) => {
    const mutations: string[] = [];
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname.startsWith('/api/install/')) {
        mutations.push(new URL(request.url()).pathname);
      }
    });
    await page.goto('/#/settings?tab=integrations');
    const card = page.getByRole('article', { name: 'Claude Code' });
    await card.getByRole('button', { name: 'Update Claude Code guidance in this repository' }).click();
    await expect(card.getByRole('status')).toContainText('Guidance written');
    expect(mutations).toEqual(['/api/install/claude/preview', '/api/install/claude']);
    await expect(card.getByRole('button', { name: 'Remove Claude Code guidance from the current project' })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  for (const graphState of ['ready', 'empty', 'disabled', 'error'] as const) {
    test(`guidance click stays in place while Graphify finishes loading (${graphState})`, async ({ page }) => {
      let releaseGraph: (() => void) | undefined;
      const graphReady = new Promise<void>(resolve => { releaseGraph = resolve; });
      let graphRequested = false;
      const mutations: string[] = [];
      page.on('request', request => {
        const path = new URL(request.url()).pathname;
        if (request.method() === 'POST' && path.startsWith('/api/install/')) mutations.push(path);
      });
      await page.route('**/api/graph/status', async route => {
        graphRequested = true;
        await graphReady;
        if (graphState === 'error') {
          await route.fulfill({ status: 503, json: { error: 'graph unavailable' } });
        } else if (graphState === 'ready') {
          await route.fallback();
        } else {
          await route.fulfill({ json: {
            enabled: graphState !== 'disabled', source_exists: false, has_graph: false,
            freshness: graphState === 'disabled' ? 'disabled' : 'unavailable',
            node_count: 0, edge_count: 0, source_path: null, provenance: null,
          } });
        }
      });
      await page.goto('/#/settings?tab=integrations');
      await expect.poll(() => graphRequested).toBe(true);
      await page.evaluate(() => document.fonts.ready);
      const graph = page.locator('#spanel-integrations .graphify-card--stable');
      await expect(graph).toHaveAttribute('aria-busy', 'true');
      const card = page.getByRole('article', { name: 'Claude Code' });
      const button = card.getByRole('button', { name: 'Update Claude Code guidance in this repository' });
      await button.evaluate(element => element.scrollIntoView({ behavior: 'instant', block: 'center' }));
      const before = await button.boundingBox();
      const graphBefore = await graph.boundingBox();
      expect(before).not.toBeNull();
      expect(graphBefore).not.toBeNull();
      if (!before || !graphBefore) return;
      const clickPoint = { x: before.x + before.width / 2, y: before.y + before.height / 2 };
      await page.mouse.move(clickPoint.x, clickPoint.y);
      await page.mouse.down();
      try {
        releaseGraph?.();
        await expect(graph).not.toHaveAttribute('aria-busy', 'true');
        const expectedStatus = graphState === 'ready' ? '2026-05-02T00:00:00Z'
          : graphState === 'empty' ? 'No Graphify source has been imported yet'
            : graphState === 'disabled' ? 'Graphify integration is disabled' : 'Graph data is unavailable';
        await expect(graph).toContainText(expectedStatus);
        const after = await button.boundingBox();
        const graphAfter = await graph.boundingBox();
        expect(after).not.toBeNull();
        expect(graphAfter).not.toBeNull();
        if (!after || !graphAfter) return;
        expect(Math.abs(after.y + after.height / 2 - clickPoint.y)).toBeLessThanOrEqual(1);
        expect(Math.abs(graphAfter.height - graphBefore.height)).toBeLessThanOrEqual(1);
      } finally {
        await page.mouse.up();
      }
      await expect(card.getByRole('status')).toContainText('Guidance written');
      expect(mutations).toEqual(['/api/install/claude/preview', '/api/install/claude']);
      await expectNoHorizontalOverflow(page);
    });
  }

  test('Settings exposes detected retired guidance only for preview and cleanup', async ({ page }) => {
    let written = true;
    const legacy = target('roo', 'Roo Code', {
      lifecycle: 'retired', lifecycle_note: 'Roo Code has shut down.', detected: true, status: 'installed',
    });
    await page.route('**/api/install/targets', route => route.fulfill({
      json: { targets: [target('pi', 'Pi Agent')], legacy_targets: written ? [legacy] : [], total: 1 },
    }));
    await page.route('**/api/install/roo/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/preview')) {
        await route.fulfill({ json: { target: legacy, manifest_hash: legacy.manifest_hash } });
      } else {
        expect(path).toBe('/api/install/roo/uninstall');
        expect(route.request().postDataJSON()).toEqual({ confirmed_manifest_hash: legacy.manifest_hash });
        written = false;
        await route.fulfill({ json: {
          target: { ...legacy, detected: false, status: 'available' },
          operation: 'uninstall', updated: true, updated_paths: ['.roo/rules/ahadiff.md'], manifest_hash: legacy.manifest_hash,
        } });
      }
    });
    await page.goto('/#/settings?tab=integrations');
    const card = page.getByRole('article', { name: 'Roo Code' });
    await expect(page.getByRole('heading', { name: 'Previous guidance' })).toBeVisible();
    await expect(card).toContainText('has shut down');
    await expect(card.getByRole('button', { name: /Write|Update/ })).toHaveCount(0);
    await card.getByRole('button', { name: 'Remove Roo Code guidance from the current project' }).click();
    await expect(card).toHaveCount(0);
  });

  test('a failed refresh preserves committed guidance and retries only the catalogue', async ({ page }) => {
    let failRefresh = false;
    let mutations = 0;
    const installed = target('claude', 'Claude Code', { detected: true, status: 'installed' });
    await page.route('**/api/install/targets', route => route.fulfill(failRefresh
      ? { status: 503, json: { error: 'temporarily unavailable' } }
      : { json: { targets: [installed], total: 1 } }));
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/install/claude') {
        failRefresh = true;
        mutations += 1;
      }
    });
    await page.goto('/#/settings?tab=integrations');
    const card = page.getByRole('article', { name: 'Claude Code' });
    await card.getByRole('button', { name: 'Update Claude Code guidance in this repository' }).click();
    await expect(card.getByRole('status')).toContainText('Guidance written');
    await expect(card.getByRole('alert')).toContainText('guidance change succeeded');
    failRefresh = false;
    await card.getByRole('button', { name: 'Retry catalogue' }).click();
    await expect(card.getByRole('alert')).toHaveCount(0);
    expect(mutations).toBe(1);
  });

  test('an older refresh cannot undo another target successful installation', async ({ page }) => {
    const written = new Set<string>();
    const targets = () => ['pi', 'grok'].map(name => target(name, name === 'pi' ? 'Pi Agent' : 'Grok Build', {
      detected: written.has(name), status: written.has(name) ? 'installed' : 'available',
    }));
    let releaseStale: (() => void) | undefined;
    const staleReady = new Promise<void>(resolve => { releaseStale = resolve; });
    let staleCaptured = false;
    let staleFinished = false;
    await page.route('**/api/install/targets', async route => {
      const snapshot = targets();
      if (written.has('pi') && !written.has('grok') && !staleCaptured) {
        staleCaptured = true;
        await staleReady;
        await route.fulfill({ headers: { 'x-test-refresh': 'stale' }, json: { targets: snapshot, total: snapshot.length } });
        staleFinished = true;
        return;
      }
      await route.fulfill({ json: { targets: snapshot, total: snapshot.length } });
    });
    await page.route(url => url.pathname.startsWith('/api/install/') && url.pathname !== '/api/install/targets', async route => {
      const parts = new URL(route.request().url()).pathname.split('/');
      const name = parts[3];
      const current = targets().find(item => item.name === name);
      expect(current).toBeDefined();
      if (!current) return;
      if (parts[4] === 'preview') {
        await route.fulfill({ json: { target: current, manifest_hash: current.manifest_hash } });
        return;
      }
      written.add(name);
      await route.fulfill({ json: {
        target: targets().find(item => item.name === name), operation: 'install', updated: true,
        updated_paths: current.manifest?.write.map(action => action.path) ?? [], manifest_hash: current.manifest_hash,
      } });
    });
    await page.goto('/#/settings?tab=integrations');
    const pi = page.getByRole('article', { name: 'Pi Agent' });
    const grok = page.getByRole('article', { name: 'Grok Build' });
    await pi.getByRole('button', { name: 'Write Pi Agent guidance to the current project' }).click();
    await expect.poll(() => staleCaptured).toBe(true);
    await grok.getByRole('button', { name: 'Write Grok Build guidance to the current project' }).click();
    await expect(grok.getByRole('button', { name: 'Update Grok Build guidance in this repository' })).toBeVisible();
    const staleResponse = page.waitForResponse(response => response.headers()['x-test-refresh'] === 'stale');
    releaseStale?.();
    await (await staleResponse).finished();
    await expect.poll(() => staleFinished).toBe(true);
    await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(grok.getByRole('button', { name: 'Update Grok Build guidance in this repository' })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test('locale change reloads localized descriptions in the same Guide catalogue', async ({ page }) => {
    await page.route('**/api/install/targets', async route => {
      // WebKit omits Cookie from intercepted request headers. Use the matching
      // browser cookie store, which supplies the cookie to the real backend.
      const cookies = await page.context().cookies(route.request().url());
      const zh = cookies.some(cookie => cookie.name === 'ahadiff_lang' && cookie.value === 'zh-CN');
      return route.fulfill({ json: { targets: [target('pi', 'Pi Agent', {
        description: zh ? '写入 Pi 原生项目技能。' : 'Write a native Pi project skill.',
      })], total: 1 } });
    });
    await page.goto('/#/guide');
    const card = page.locator('.guide-agent-card');
    await card.locator('.guide-agent-card__header').click();
    await expect(card).toContainText('Write a native Pi project skill.');
    await page.getByRole('button', { name: '简体中文' }).click();
    await expect(card).toContainText('写入 Pi 原生项目技能。');
    await expect(card).toContainText('可写入指引');
    await expectNoHorizontalOverflow(page);
  });
});
