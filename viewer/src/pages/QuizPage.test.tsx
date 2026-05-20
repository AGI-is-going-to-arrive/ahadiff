import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

function source(): string {
  return readFileSync(resolve(__dirname, 'QuizPage.tsx'), 'utf-8');
}

describe('QuizPage mode badge tooltip', () => {
  it('renders a real accessible tooltip instead of CSS-only tooltip text', () => {
    const src = source();

    expect(src).toContain('role="tooltip"');
    expect(src).toContain('aria-expanded={modeTipOpen}');
    expect(src).toContain("event.key === 'Escape'");
    expect(src).not.toContain('data-tooltip=');
  });
});
