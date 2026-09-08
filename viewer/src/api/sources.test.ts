import { createHash } from 'node:crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from './client';
import { getRunAnchors, getRunReviewContext } from './runs';
import { deleteSnapshot, getSnapshot, listSnapshots, saveSnapshot } from './snapshots';
import { evidenceAnchorsArtifactSchema, learnEstimateResponseSchema, reviewContextArtifactSchema, sourceAnchorSchema, snapshotRecordSchema, snapshotSummarySchema, snapshotListResponseSchema, snapshotDeleteResponseSchema } from './schemas';
import { getQuizQuestions, revealQuizQuestion } from './quiz';
import { parseSourceAnchors } from '../utils/source-anchors';
import type { SourceAnchor } from './types';

vi.mock('./client', () => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }));
const mockedFetch = vi.mocked(apiFetch);
const digest = (value: string): string => createHash('sha256').update(value).digest('hex');
const snapshotId = `snap_${digest('synthetic snapshot').slice(0, 32)}`;
const anchor: SourceAnchor = {
  schema_version: 1, source_kind: 'document', format: 'markdown', side: 'document',
  file: '学习.md', anchor_id: `anchor_${digest('synthetic document paragraph').slice(0, 32)}`, locator: { kind: 'paragraph', heading_path: ['学习'], key_path: [], paragraph_index: 1 },
  content_hash: digest('Document source fact.'), start: 3, end: 3, quote: 'Document source fact.',
};
const record = {
  schema_version: 1, snapshot_id: snapshotId, name: 'Baseline', file_name: '学习.md',
  content: '# Synthetic text', content_hash: digest('# Synthetic text'), hash_scope: 'sanitized_utf8_nfc_lf',
  created_at: '2026-09-08T00:00:00Z', size_bytes: 16, source: 'explicit_file', sanitized: true,
};
const { content: _content, ...summaryFields } = record;
const summary = { ...summaryFields, status: 'ready', stored_bytes: 300, record_hash: digest(JSON.stringify(record) + '\n') };

describe('source artifact and snapshot contracts', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('keeps legacy estimate responses compatible and accepts only a boolean active-practice echo', () => {
    const estimate = { patch_bytes: 12, file_count: 1, total_lines: 2, estimated_tokens: 8,
      provider_context_window: 8192, provider_max_output: null, risk_level: 'ok', warnings: [] };
    expect(learnEstimateResponseSchema.parse(estimate)).not.toHaveProperty('active_practice');
    expect(learnEstimateResponseSchema.parse({ ...estimate, active_practice: true }).active_practice).toBe(true);
    expect(learnEstimateResponseSchema.safeParse({ ...estimate, active_practice: 'true' }).success).toBe(false);
  });

  it('supports document anchors and keeps old absent anchors compatible', () => {
    expect(parseSourceAnchors(undefined)).toEqual([]);
    expect(parseSourceAnchors([anchor])).toEqual([anchor]);
    expect(sourceAnchorSchema.safeParse({ ...anchor, side: 'new' }).success).toBe(false);
    expect(sourceAnchorSchema.safeParse({ ...anchor, end: 2 }).success).toBe(false);
    expect(sourceAnchorSchema.safeParse({ ...anchor, source_kind: 'diff', side: 'old' }).success).toBe(true);
    expect(sourceAnchorSchema.safeParse({ ...anchor, quote: '学'.repeat(2049) }).success).toBe(false);
    expect(sourceAnchorSchema.safeParse({ ...anchor, quote: '😀'.repeat(2048) }).success).toBe(true);
  });

  it('defaults omitted legacy anchor-index flags while keeping reviewer context separate', async () => {
    const anchors = { schema: 'ahadiff.evidence_anchors', schema_version: 1, source_kind: 'document', anchors: [anchor], sources: [] };
    mockedFetch.mockResolvedValueOnce({ run_id: 'run-1', artifact_type: 'anchors', content: JSON.stringify(anchors) });
    expect(await getRunAnchors('run-1')).toEqual({ ...anchors, truncated: false, warnings: [] });
    const context = { schema_version: 1, kind: 'auxiliary_untrusted', content: 'Synthetic notes', content_hash: digest('Synthetic notes'), sanitized: true };
    mockedFetch.mockResolvedValueOnce({ run_id: 'run-1', artifact_type: 'review-context', content: JSON.stringify(context) });
    expect(await getRunReviewContext('run-1')).toEqual(context);
  });

  it('keeps unreadable snapshots visible while refusing unknown record versions', async () => {
    const corrupt = { snapshot_id: `snap_${'b'.repeat(32)}`, status: 'corrupt', stored_bytes: 0, record_hash: null };
    mockedFetch.mockResolvedValue({ snapshots: [summary, corrupt], max_count: 100, max_bytes: 16777216 });
    const result = await listSnapshots();
    expect(result.snapshots[1]).toMatchObject({ status: 'corrupt', record_hash: null, content_hash: null });
    expect(snapshotRecordSchema.safeParse({ ...record, schema_version: 2 }).success).toBe(false);
  });

  it('sends explicit save and deletion hashes through the protected API client', async () => {
    const signal = new AbortController().signal;
    mockedFetch.mockResolvedValueOnce(summary);
    await saveSnapshot({ name: 'Baseline', file: { name: '学习.md', content: '# Synthetic text' } }, { signal });
    expect(mockedFetch).toHaveBeenLastCalledWith('/api/snapshots', expect.objectContaining({ method: 'POST', signal }));
    mockedFetch.mockResolvedValueOnce(record);
    expect((await getSnapshot('snapshot/1')).content).toBe('# Synthetic text');
    expect(mockedFetch).toHaveBeenLastCalledWith('/api/snapshots/snapshot%2F1', undefined);
    mockedFetch.mockResolvedValueOnce({ snapshot_id: snapshotId, deleted: true });
    await deleteSnapshot(snapshotId, summary.record_hash);
    expect(mockedFetch).toHaveBeenLastCalledWith(`/api/snapshots/${snapshotId}`, expect.objectContaining({
      method: 'DELETE', body: JSON.stringify({ expected_hash: summary.record_hash }),
    }));
  });

  it('rejects answer-bearing public quiz projections and wrong-run reveal responses', async () => {
    mockedFetch.mockResolvedValueOnce({ run_id: 'run-1', questions: [{ question_id: 'q1', question: 'Try it', quiz_kind: 'transfer', answer_mode: 'open', expected_answer: 'hidden' }] });
    await expect(getQuizQuestions('run-1')).rejects.toThrow();
    mockedFetch.mockResolvedValueOnce({ run_id: 'another-run', question: {
      question_id: 'q1', question: 'Try it', expected_answer: 'Reference', quiz_kind: 'transfer', answer_mode: 'open',
      source_claims: ['c1'], concepts: [], evidence: [], source_anchors: [anchor],
    }, correct: null, feedback_kind: 'semantic_self_assessment' });
    await expect(revealQuizQuestion('run-1', 'q1', { attempted: true })).rejects.toThrow('Invalid revealed quiz');
  });
  it.each([
    { anchor_id: 'anchor-1' },
    { anchor_id: `anchor_${'a'.repeat(31)}` },
    { anchor_id: `anchor_${'A'.repeat(32)}` },
    { anchor_id: `anchor_${'a'.repeat(32)}\n` },
    { content_hash: 'sha256:synthetic' },
    { content_hash: 'a'.repeat(63) },
    { content_hash: 'g'.repeat(64) },
    { content_hash: 'A'.repeat(64) },
    { content_hash: 'a'.repeat(64) + '\n' },
    { start: 0 },
    { start: 3.5 },
    { start: true },
    { end: 123 },
    { file: '学'.repeat(1025) },
  ])('rejects malformed new anchor identity, hash, range, or filename (#%#)', (change) => {
    expect(sourceAnchorSchema.safeParse({ ...anchor, ...change }).success).toBe(false);
  });

  it.each([
    { heading_path: Array.from({ length: 33 }, () => 'Heading') },
    { heading_path: ['学'.repeat(513)] },
    { key_path: Array.from({ length: 49 }, () => 'key') },
    { key_path: ['key'.repeat(171)] },
    { key_path: [true] },
    { cell_id: '学'.repeat(161) },
    { cell_index: -1 },
    { fallback_reason: 'x'.repeat(121) },
  ])('rejects out-of-contract locator bounds (#%#)', (change) => {
    expect(sourceAnchorSchema.safeParse({ ...anchor, locator: { ...anchor.locator, ...change } }).success).toBe(false);
  });

  it('accepts exact anchor boundaries in Unicode code points', () => {
    expect(sourceAnchorSchema.safeParse({
      ...anchor, end: anchor.start + 119, file: '学'.repeat(1024),
      locator: { ...anchor.locator, heading_path: ['😀'.repeat(512)], cell_id: '学'.repeat(160), fallback_reason: 'x'.repeat(120) },
    }).success).toBe(true);
  });

  it('rejects oversized anchor-index collections and malformed source digests', () => {
    const index = { schema: 'ahadiff.evidence_anchors', schema_version: 1, source_kind: 'document' };
    expect(evidenceAnchorsArtifactSchema.safeParse({ ...index, anchors: Array.from({ length: 4097 }, () => anchor) }).success).toBe(false);
    const source = { file: '学习.md', side: 'document', format: 'markdown', content_hash: anchor.content_hash };
    expect(evidenceAnchorsArtifactSchema.safeParse({ ...index, sources: Array.from({ length: 1001 }, () => source) }).success).toBe(false);
    expect(evidenceAnchorsArtifactSchema.safeParse({ ...index, sources: [{ ...source, content_hash: 'short' }] }).success).toBe(false);
    expect(evidenceAnchorsArtifactSchema.safeParse({ ...index, warnings: Array.from({ length: 21 }, () => 'anchor_limit_reached') }).success).toBe(false);
    expect(evidenceAnchorsArtifactSchema.parse(index)).toEqual({ ...index, anchors: [], sources: [], truncated: false, warnings: [] });
  });

  it.each(['hash', 'sha256:' + 'a'.repeat(64), 'g'.repeat(64), 'a'.repeat(64) + '\n'])('rejects malformed snapshot and auxiliary hashes (#%#)', (hash) => {
    expect(snapshotRecordSchema.safeParse({ ...record, content_hash: hash }).success).toBe(false);
    expect(snapshotSummarySchema.safeParse({ ...summary, content_hash: hash }).success).toBe(false);
    expect(snapshotSummarySchema.safeParse({ ...summary, record_hash: hash }).success).toBe(false);
    expect(reviewContextArtifactSchema.safeParse({ schema_version: 1, kind: 'auxiliary_untrusted', content: 'notes', content_hash: hash, sanitized: false }).success).toBe(false);
  });

  it('requires valid snapshot IDs and bounded normalized record text', () => {
    for (const id of ['snapshot-1', 'snap_' + 'a'.repeat(31), 'snap_' + 'A'.repeat(32)]) {
      expect(snapshotRecordSchema.safeParse({ ...record, snapshot_id: id }).success).toBe(false);
      expect(snapshotSummarySchema.safeParse({ ...summary, snapshot_id: id }).success).toBe(false);
      expect(snapshotDeleteResponseSchema.safeParse({ snapshot_id: id, deleted: true }).success).toBe(false);
    }
    for (const change of [
      { name: 'x'.repeat(81) }, { file_name: 'x'.repeat(256) }, { name: 'CON' }, { file_name: '../private.md' },
      { content: 'e\u0301', size_bytes: 3 }, { content: 'a\r\n', size_bytes: 3 }, { content: '\ud800', size_bytes: 3 },
      { size_bytes: 17 }, { content: '学'.repeat(87382), size_bytes: 262146 },
      { created_at: '2026-02-30T00:00:00Z' }, { created_at: '2026-09-08T00:00:00+00:00' },
      { created_at: '2026-09-08T00:00:00.1234567Z' },
    ]) expect(snapshotRecordSchema.safeParse({ ...record, ...change }).success).toBe(false);
    expect(snapshotRecordSchema.safeParse({ ...record, name: '😀'.repeat(80), created_at: '2026-09-08T00:00:00.123456Z' }).success).toBe(true);
    expect(snapshotSummarySchema.safeParse({ ...summary, size_bytes: 262145 }).success).toBe(false);
    expect(snapshotListResponseSchema.safeParse({ snapshots: [], max_count: 101, max_bytes: 16777216 }).success).toBe(false);
    expect(snapshotListResponseSchema.safeParse({ snapshots: [], max_count: 100, max_bytes: 16777217 }).success).toBe(false);
  });

  it('keeps over-quota corrupt records listable for explicit recovery', () => {
    const corrupted = Array.from({ length: 101 }, (_, index) => ({
      snapshot_id: `snap_${index.toString(16).padStart(32, '0')}`, status: 'corrupt', stored_bytes: 20 * 1024 * 1024,
    }));
    const result = snapshotListResponseSchema.parse({ snapshots: corrupted });
    expect(result.snapshots).toHaveLength(101);
    expect(result.snapshots[0]).toMatchObject({ record_hash: null, content_hash: null, hash_scope: 'sanitized_utf8_nfc_lf', source: 'explicit_file' });
  });

});
