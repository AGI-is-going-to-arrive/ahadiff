import { describe, expect, it } from 'vitest';

import {
  diffLineMatchesClaim,
  getClaimSourceLines,
  parseDiffFileSections,
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

describe('parseDiffFileSections', () => {
  it('groups lines into one section per file boundary', () => {
    const lines = parseUnifiedDiff(
      [
        'diff --git a/src/a.ts b/src/a.ts',
        '@@ -1 +1,2 @@',
        ' keep',
        '+added in a',
        'diff --git a/src/b.ts b/src/b.ts',
        '@@ -1 +1 @@',
        '-bye',
        '+hi',
      ].join('\n'),
    );
    const sections = parseDiffFileSections(lines);

    expect(sections).toHaveLength(2);
    expect(sections[0]?.filePath).toBe('src/a.ts');
    expect(sections[0]?.stats).toEqual({ added: 1, removed: 0 });
    expect(sections[1]?.filePath).toBe('src/b.ts');
    expect(sections[1]?.stats).toEqual({ added: 1, removed: 1 });
  });

  it('detects renames when oldPath and newPath differ', () => {
    const lines = parseUnifiedDiff(
      [
        'diff --git a/src/old.ts b/src/new.ts',
        'similarity index 100%',
        'rename from src/old.ts',
        'rename to src/new.ts',
        '@@ -1 +1 @@',
        '-x',
        '+y',
      ].join('\n'),
    );
    const sections = parseDiffFileSections(lines);

    expect(sections).toHaveLength(1);
    expect(sections[0]?.isRename).toBe(true);
    expect(sections[0]?.oldPath).toBe('src/old.ts');
    expect(sections[0]?.filePath).toBe('src/new.ts');
  });

  it('counts additions and deletions per file independently', () => {
    const lines = parseUnifiedDiff(
      [
        'diff --git a/x b/x',
        '@@ -1,2 +1,3 @@',
        '-a',
        '-b',
        '+c',
        '+d',
        '+e',
        'diff --git a/y b/y',
        '@@ -1 +0,0 @@',
        '-only-in-y',
      ].join('\n'),
    );
    const sections = parseDiffFileSections(lines);

    expect(sections).toHaveLength(2);
    expect(sections[0]?.stats).toEqual({ added: 3, removed: 2 });
    expect(sections[1]?.stats).toEqual({ added: 0, removed: 1 });
  });

  it('preserves original DiffLine ordering inside each section', () => {
    const lines = parseUnifiedDiff(
      ['diff --git a/f b/f', '@@ -1 +1,2 @@', ' x', '+y'].join('\n'),
    );
    const sections = parseDiffFileSections(lines);

    expect(sections).toHaveLength(1);
    const section = sections[0];
    expect(section?.lines.length).toBeGreaterThan(0);
    // The first line must be the `diff --git` meta marker.
    expect(section?.lines[0]?.type).toBe('meta');
    expect(section?.lines[0]?.text.startsWith('diff --git')).toBe(true);
  });

  it('returns an empty array for an empty diff', () => {
    expect(parseDiffFileSections([])).toEqual([]);
    expect(parseDiffFileSections(parseUnifiedDiff(''))).toEqual([]);
  });

  it('infers filePath from --- / +++ headers when diff --git is missing', () => {
    const lines = parseUnifiedDiff(
      ['--- a/src/c.ts', '+++ b/src/c.ts', '@@ -1 +1 @@', '-x', '+y'].join('\n'),
    );
    const sections = parseDiffFileSections(lines);

    expect(sections).toHaveLength(1);
    expect(sections[0]?.filePath).toBe('src/c.ts');
    expect(sections[0]?.stats).toEqual({ added: 1, removed: 1 });
  });
});
