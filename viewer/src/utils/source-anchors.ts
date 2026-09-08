import { sourceAnchorSchema } from '../api/schemas';
import type { SourceAnchor } from '../api/types';

export function parseSourceAnchors(value: unknown): SourceAnchor[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw) => {
    const result = sourceAnchorSchema.safeParse(raw);
    return result.success ? [result.data] : [];
  });
}

export function parseAssertionKind(value: unknown): 'source_fact' | 'semantic' | 'runtime_effect' | null {
  return value === 'source_fact' || value === 'semantic' || value === 'runtime_effect' ? value : null;
}
