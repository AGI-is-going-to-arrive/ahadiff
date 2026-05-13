import { describe, expect, it } from 'vitest';
import { searchResponseSchema } from '../schemas';

describe('search API schema', () => {
  it('keeps graph node primary keys stable while exposing plain focus text', () => {
    const parsed = searchResponseSchema.parse({
      results: [
        {
          source_table: 'graph_nodes',
          primary_key: 'repo_graphify_extract_py',
          snippet: '<b>extract.py</b> graph node',
          rank: 0.98,
          href: null,
        },
      ],
      next_cursor: null,
    });

    expect(parsed.results[0]).toEqual({
      kind: 'concept',
      sourceTable: 'graph_nodes',
      id: 'repo_graphify_extract_py',
      focusText: 'extract.py graph node',
      title: 'extract.py graph node',
      snippet: 'extract.py graph node',
      rank: 0.98,
      href: null,
    });
  });

  it('keeps graph node slugs out of focus text', () => {
    const parsed = searchResponseSchema.parse({
      results: [
        {
          source_table: 'graph_nodes',
          primary_key: 'users_yangjunjie_desktop_demo_node',
          snippet: '<b>str value</b> with spaces / ? #',
          rank: 0.99,
          href: null,
        },
      ],
      next_cursor: null,
    });

    expect(parsed.results[0]).toMatchObject({
      kind: 'concept',
      sourceTable: 'graph_nodes',
      id: 'users_yangjunjie_desktop_demo_node',
      focusText: 'str value with spaces / ? #',
      title: 'str value with spaces / ? #',
      snippet: 'str value with spaces / ? #',
    });
  });

  it('keeps the backend primary key as the stable ledger concept identity', () => {
    const parsed = searchResponseSchema.parse({
      results: [
        {
          source_table: 'concepts',
          primary_key: 'str',
          snippet: '<b>str</b> concept ledger entry',
          rank: 0.72,
          href: null,
        },
      ],
      next_cursor: null,
    });

    expect(parsed.results[0]).toMatchObject({
      kind: 'concept',
      sourceTable: 'concepts',
      id: 'str',
      focusText: 'str',
      title: 'str concept ledger entry',
      snippet: 'str concept ledger entry',
    });
  });
});
