import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

function source(): string {
  return readFileSync(resolve(__dirname, 'ConceptsPage.tsx'), 'utf-8');
}

describe('ConceptsPage refresh hardening', () => {
  it('uses generation guards so stale graph fetch aborts cannot leave loading stuck', () => {
    const src = source();

    expect(src).toContain('graphFetchGenerationRef');
    expect(src).toContain('graphFetchGenerationRef.current === generation');
    expect(src).toContain('setGraphLoading(false)');
    expect(src).toContain('abortRef.current = null');
  });

  it('guards refresh completion against stale controllers and rapid duplicate clicks', () => {
    const src = source();

    expect(src).toContain('refreshingRef.current');
    expect(src).toContain('if (refreshingRef.current) return;');
    expect(src).toContain('refreshGenerationRef.current !== generation');
    expect(src).toContain('refreshAbortRef.current !== controller');
  });

  it('returns focus to the refresh button after cancel', () => {
    const src = source();

    expect(src).toContain('refreshButtonRef');
    expect(src).toContain('window.requestAnimationFrame(() => refreshButtonRef.current?.focus())');
  });

  it('keeps the elapsed timer out of the live region', () => {
    const src = source();

    expect(src).toContain('aria-hidden="true"');
    expect(src).toContain("t('Concept.refresh_in_progress')");
    expect(src).not.toMatch(/className="concepts-page__elapsed"[\s\S]{0,120}aria-live/);
  });
});
