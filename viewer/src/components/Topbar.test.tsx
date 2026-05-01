import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import Topbar from './Topbar';

let learnPhase = 'idle';
const submitLearn = vi.fn();

vi.mock('../state/learn-store', () => ({
  useLearnStore: (selector: (state: { phase: string; submitLearn: typeof submitLearn }) => unknown) =>
    selector({ phase: learnPhase, submitLearn }),
}));

describe('Topbar', () => {
  beforeEach(() => {
    learnPhase = 'idle';
    submitLearn.mockReset();
  });

  it('uses the busy label as the accessible name while a learn run is active', () => {
    learnPhase = 'running';

    const html = renderToStaticMarkup(
      <MemoryRouter>
        <Topbar isMenuOpen={false} onMenuToggle={() => undefined} />
      </MemoryRouter>,
    );

    expect(html).toContain('aria-label="Running');
    expect(html).not.toContain('aria-label="Start a new learn run"');
  });

  it('disables the busy pulse animation for reduced-motion users', () => {
    const css = readFileSync(resolve(__dirname, 'Topbar.css'), 'utf-8');
    const reducedMotionBlock = css.match(/@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*?\n\}/);

    expect(reducedMotionBlock?.[0]).toContain('.topbar__btn--busy');
    expect(reducedMotionBlock?.[0]).toContain('animation: none');
  });
});
