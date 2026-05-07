import { describe, expect, it } from 'vitest';
import { recommendScaffoldLevel } from './LessonPage';
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
