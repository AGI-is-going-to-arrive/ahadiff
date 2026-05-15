import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import DiffView, {
  buildClaimLookup,
  buildSplitDiffRows,
  diffLineMatchesFocusTarget,
  diffLineMatchesClaim,
  getClaimSourceLines,
  getRenderedDiffLines,
  lookupClaimsForLine,
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

function largeDiff(lineCount: number): string {
  const body = Array.from({ length: lineCount }, (_, i) => ` line ${i + 1}`);
  return ['diff --git a/large.txt b/large.txt', `@@ -1,${lineCount} +1,${lineCount} @@`, ...body]
    .join('\n');
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

describe('DiffView claim lookup', () => {
  it('preserves multiple claims on the same line while deduping duplicate claim ids', () => {
    const lines = parseUnifiedDiff(
      ['diff --git a/src/a.ts b/src/a.ts', '@@ -1 +1 @@', '-old', '+new'].join('\n'),
    );
    const add = lines.find((line) => line.type === 'add');
    const lookup = buildClaimLookup([
      { claim_id: 'c1', file: 'src/a.ts', line_start: 1, line_end: 1, source_side: 'new' },
      { claim_id: 'c2', file: 'src/a.ts', line_start: 1, line_end: 1, source_side: 'new' },
      { claim_id: 'c1', file: 'src/a.ts', line_start: 1, line_end: 1, source_side: 'new' },
    ]);

    expect(add && lookupClaimsForLine(add, lookup).map((c) => c.claim_id)).toEqual(['c1', 'c2']);
  });

  it('keeps lookup construction bounded for abnormal claim ranges', () => {
    const lookup = buildClaimLookup([
      {
        claim_id: 'huge',
        file: 'src/a.ts',
        line_start: 1,
        line_end: 200_000,
        source_side: 'either',
      },
    ]);

    expect(lookup.size).toBeGreaterThan(0);
    expect(lookup.size).toBeLessThanOrEqual(10_000);
  });

  it('keeps old-side and new-side claims separate for the same file line number', () => {
    const lookup = buildClaimLookup([
      { claim_id: 'old-side', file: 'src/a.ts', line_start: 1, line_end: 1, source_side: 'old' },
      { claim_id: 'new-side', file: 'src/a.ts', line_start: 1, line_end: 1, source_side: 'new' },
    ]);

    expect(lookup.get('src/a.ts:old:1')?.map((c) => c.claim_id)).toEqual(['old-side']);
    expect(lookup.get('src/a.ts:new:1')?.map((c) => c.claim_id)).toEqual(['new-side']);
  });

  it('renders one aggregated claim indicator with the highest-severity claim as the click target', () => {
    const content = [
      'diff --git a/src/a.ts b/src/a.ts',
      '@@ -1 +1 @@',
      '-old',
      '+new',
    ].join('\n');
    const claims: DiffClaimAnchor[] = [
      {
        claim_id: 'c-verified',
        file: 'src/a.ts',
        line_start: 1,
        line_end: 1,
        source_side: 'new',
        verdict: 'verified',
      },
      {
        claim_id: 'c-weak',
        file: 'src/a.ts',
        line_start: 1,
        line_end: 1,
        source_side: 'new',
        verdict: 'weak',
      },
      {
        claim_id: 'c-not-proven',
        file: 'src/a.ts',
        line_start: 1,
        line_end: 1,
        source_side: 'new',
        verdict: 'not_proven',
      },
      {
        claim_id: 'c-rejected',
        file: 'src/a.ts',
        line_start: 1,
        line_end: 1,
        source_side: 'new',
        verdict: 'rejected',
      },
    ];

    const html = renderToStaticMarkup(
      createElement(DiffView, {
        content,
        claims,
        onSelectClaim: () => undefined,
      }),
    );

    expect(html.match(/class="[^"]*diff-line__claim-dot(?:\s|")/g) ?? []).toHaveLength(1);
    expect(html).toContain('diff-line__claim-dot--rejected');
    expect(html).toContain('diff-line__claim-count--rejected');
    expect(html).toContain('>4</span>');
    expect(html).toContain('data-claim-id="c-rejected"');
    expect(html).toContain('data-claim-ids="c-verified,c-weak,c-not-proven,c-rejected"');
    expect(html).toContain('c-verified');
    expect(html).toContain('c-rejected');
  });
});

describe('DiffView rendered line budget', () => {
  it('does not mount rows for collapsed file sections', () => {
    const lines = parseUnifiedDiff(largeDiff(300));

    expect(getRenderedDiffLines(lines, false, false)).toHaveLength(0);
    expect(getRenderedDiffLines(lines, true, false)).toHaveLength(lines.length);
  });

  it('truncates very large expanded files until the user opts into show all', () => {
    const lines = parseUnifiedDiff(largeDiff(5001));

    expect(getRenderedDiffLines(lines, true, false)).toHaveLength(1000);
    expect(getRenderedDiffLines(lines, true, true)).toHaveLength(lines.length);
  });
});

describe('DiffView focus target matching', () => {
  it('matches focus targets by normalized file and requested side', () => {
    const lines = parseUnifiedDiff(
      ['diff --git a/src/a.ts b/src/a.ts', '@@ -1 +1 @@', '-old', '+new'].join('\n'),
    );
    const del = lines.find((line) => line.type === 'del');
    const add = lines.find((line) => line.type === 'add');

    expect(del && diffLineMatchesFocusTarget(del, { file: 'src/a.ts', line: 1, side: 'old' }))
      .toBe(true);
    expect(del && diffLineMatchesFocusTarget(del, { file: 'src/a.ts', line: 1, side: 'new' }))
      .toBe(false);
    expect(add && diffLineMatchesFocusTarget(add, { file: 'src/a.ts', line: 1, side: 'new' }))
      .toBe(true);
    expect(add && diffLineMatchesFocusTarget(add, { file: 'src/a.ts', line: 1, side: 'old' }))
      .toBe(false);
  });
});

describe('buildSplitDiffRows', () => {
  it('pairs replacement blocks while preserving context, hunk, and meta rows', () => {
    const rows = buildSplitDiffRows(parseUnifiedDiff(
      [
        'diff --git a/demo.py b/demo.py',
        '@@ -1,3 +1,4 @@',
        ' def hello():',
        '-    return "world"',
        '+    return "AhaDiff"',
        '+    # learn-from-diff',
      ].join('\n'),
    ));

    expect(rows[0]).toMatchObject({ kind: 'span' });
    expect(rows[1]).toMatchObject({ kind: 'span' });
    expect(rows[2]).toMatchObject({
      kind: 'pair',
      oldLine: expect.objectContaining({ type: 'ctx', oldLineNo: 1 }),
      newLine: expect.objectContaining({ type: 'ctx', newLineNo: 1 }),
    });
    expect(rows[3]).toMatchObject({
      kind: 'pair',
      oldLine: expect.objectContaining({ type: 'del', text: '    return "world"', oldLineNo: 2 }),
      newLine: expect.objectContaining({ type: 'add', text: '    return "AhaDiff"', newLineNo: 2 }),
    });
    expect(rows[4]).toMatchObject({
      kind: 'pair',
      oldLine: null,
      newLine: expect.objectContaining({ type: 'add', text: '    # learn-from-diff', newLineNo: 3 }),
    });
  });

  it('keeps uneven delete-only and add-only runs aligned to the correct side', () => {
    const rows = buildSplitDiffRows(parseUnifiedDiff(
      [
        'diff --git a/a.txt b/a.txt',
        '@@ -1,3 +1,2 @@',
        '-old a',
        '-old b',
        '+new a',
        ' context',
        '+new tail',
      ].join('\n'),
    )).filter((row) => row.kind === 'pair');

    expect(rows[0]).toMatchObject({
      kind: 'pair',
      oldLine: expect.objectContaining({ type: 'del', text: 'old a' }),
      newLine: expect.objectContaining({ type: 'add', text: 'new a' }),
    });
    expect(rows[1]).toMatchObject({
      kind: 'pair',
      oldLine: expect.objectContaining({ type: 'del', text: 'old b' }),
      newLine: null,
    });
    expect(rows[2]).toMatchObject({
      kind: 'pair',
      oldLine: expect.objectContaining({ type: 'ctx', text: 'context' }),
      newLine: expect.objectContaining({ type: 'ctx', text: 'context' }),
    });
    expect(rows[3]).toMatchObject({
      kind: 'pair',
      oldLine: null,
      newLine: expect.objectContaining({ type: 'add', text: 'new tail' }),
    });
  });
});
