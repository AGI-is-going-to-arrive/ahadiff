import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import FreshnessBadge from './FreshnessBadge';

vi.mock('../i18n/useTranslation', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe('FreshnessBadge', () => {
  const expectedTone = {
    fresh: 'success',
    stale: 'warning',
    unavailable: 'muted',
    disabled: 'muted',
  } as const;

  it.each(['fresh', 'stale', 'unavailable', 'disabled'] as const)(
    'renders %s projection with correct tone',
    (value) => {
      const html = renderToStaticMarkup(<FreshnessBadge value={value} />);
      expect(html).toContain('graphify-badge');
      expect(html).toContain(`graphify-badge--${expectedTone[value]}`);
      expect(html).toContain(`Graph.freshness_${value}`);
    },
  );

  it('returns null for null value', () => {
    const html = renderToStaticMarkup(<FreshnessBadge value={null} />);
    expect(html).toBe('');
  });

  it('returns null for undefined value', () => {
    const html = renderToStaticMarkup(<FreshnessBadge value={undefined} />);
    expect(html).toBe('');
  });

  it('returns null for unknown projection string', () => {
    const html = renderToStaticMarkup(<FreshnessBadge value="pending" />);
    expect(html).toBe('');
  });

  it('returns null for empty string', () => {
    const html = renderToStaticMarkup(<FreshnessBadge value="" />);
    expect(html).toBe('');
  });

  it('does not use role="status" (static badge)', () => {
    const html = renderToStaticMarkup(<FreshnessBadge value="fresh" />);
    expect(html).not.toContain('role=');
  });
});
