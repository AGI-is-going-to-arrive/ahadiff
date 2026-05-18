import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { optionalArtifact, recommendScaffoldLevel } from './LessonPage';
import { ApiError } from '../api/client';
import type { WeakConceptsResponse } from '../api/types';

function weakWith(levels: string[]): WeakConceptsResponse {
  return {
    concepts: levels.map((level, index) => ({
      card_id: `card-${index}`,
      concept: `Concept ${index}`,
      stability: level === 'compact' ? 999 : level === 'hint' ? 7 : 0,
      difficulty: 5,
      scaffolding_level: level,
      display_path: `src/file_${index}.py`,
    })),
    new_concepts: [],
  };
}

describe('recommendScaffoldLevel', () => {
  it('defaults to compact when weak concept data is absent or empty', () => {
    expect(recommendScaffoldLevel(null)).toBe('compact');
    expect(recommendScaffoldLevel({ concepts: [], new_concepts: [] })).toBe('compact');
  });

  it('uses the weakest available scaffolding level', () => {
    expect(recommendScaffoldLevel(weakWith(['compact', 'hint']))).toBe('hint');
    expect(recommendScaffoldLevel(weakWith(['compact', 'hint', 'full']))).toBe('full');
  });

  it('treats all high-stability compact concepts as compact', () => {
    expect(recommendScaffoldLevel(weakWith(['compact', 'compact']))).toBe('compact');
  });
});

describe('optionalArtifact', () => {
  it('treats 404 artifacts as absent without reporting failure', async () => {
    await expect(
      optionalArtifact('claims', Promise.reject(new ApiError(404, { error: 'not_found' }))),
    ).resolves.toEqual({ failed: false, label: 'claims', value: null });
  });

  it('reports non-404 artifact failures while keeping the lesson usable', async () => {
    await expect(
      optionalArtifact('score', Promise.reject(new ApiError(500, { error: 'boom' }))),
    ).resolves.toEqual({ failed: true, label: 'score', value: null });
  });
});

describe('LessonPage request guards', () => {
  it('does not let the initial recommended lesson overwrite a manual level fetch', () => {
    const src = readFileSync(resolve(__dirname, 'LessonPage.tsx'), 'utf-8');

    expect(src).toContain('manualLevelOverrideRef.current = true');
    expect(src).toContain('const requestedLevel = manualLevelOverrideRef.current ? levelRef.current : recommended');
    expect(src).toContain('if (levelRef.current === requestedLevel)');
  });
});
