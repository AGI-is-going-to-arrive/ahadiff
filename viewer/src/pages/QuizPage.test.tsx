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
    expect(src).toContain('modeTipPointerDownRef.current');
    expect(src).toContain('onPointerDown={handleModeTipPointerDown}');
    expect(src).toContain('onFocus={handleModeTipFocus}');
    expect(src).toContain('onClick={handleModeTipClick}');
    expect(src).not.toContain('data-tooltip=');
  });
});

describe('QuizPage evidence empty states', () => {
  it('renders locked and answered-without-evidence empty states explicitly', () => {
    const src = source();

    expect(src).toContain('quiz-evidence__locked');
    expect(src).toContain("t('Quiz.evidence_locked_hint')");
    expect(src).toContain('currentEvidence.length > 0');
    expect(src).toContain("t('Quiz.evidence_unavailable')");
  });
});
