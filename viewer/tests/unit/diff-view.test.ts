import { describe, expect, it } from 'vitest';

import {
  diffLineMatchesClaim,
  getClaimSourceLines,
  parseUnifiedDiff,
  type DiffClaimAnchor,
} from '../../src/components/DiffView';

function claim(file: string): DiffClaimAnchor {
  return {
    claim_id: 'c1',
    file,
    line_start: 1,
    line_end: 1,
    source_side: 'new',
  };
}

describe('DiffView path normalization', () => {
  it('matches Windows-style git headers against normalized claim paths', () => {
    const lines = parseUnifiedDiff(
      ['diff --git a\\src\\demo.py b\\src\\demo.py', '@@ -1 +1 @@', '-old', '+new'].join(
        '\n',
      ),
    );
    const add = lines.find((line) => line.type === 'add');

    expect(add?.filePath).toBe('src/demo.py');
    expect(add && diffLineMatchesClaim(add, claim('src/demo.py'))).toBe(true);
  });

  it('supports Git quoted C-style paths', () => {
    const lines = parseUnifiedDiff(
      [
        'diff --git "a/new\\nline.py" "b/new\\nline.py"',
        '@@ -1 +1 @@',
        '-old',
        '+new',
      ].join('\n'),
    );
    const sourceLines = getClaimSourceLines(lines, claim('new\nline.py'));

    expect(sourceLines).toHaveLength(1);
    expect(sourceLines[0]?.file).toBe('new\nline.py');
  });

  it('normalizes Unicode path forms before claim matching', () => {
    const nfdPath = 'cafe\u0301.ts';
    const lines = parseUnifiedDiff(
      [`diff --git a/${nfdPath} b/${nfdPath}`, '@@ -1 +1 @@', '-old', '+new'].join('\n'),
    );
    const add = lines.find((line) => line.type === 'add');

    expect(add && diffLineMatchesClaim(add, claim('café.ts'))).toBe(true);
  });

  it('rejects traversal paths instead of matching them as local files', () => {
    const lines = parseUnifiedDiff(
      ['diff --git a/../outside.py b/../outside.py', '@@ -1 +1 @@', '-old', '+new'].join(
        '\n',
      ),
    );
    const add = lines.find((line) => line.type === 'add');

    expect(add?.filePath).toBeNull();
    expect(add && diffLineMatchesClaim(add, claim('outside.py'))).toBe(false);
  });
});
