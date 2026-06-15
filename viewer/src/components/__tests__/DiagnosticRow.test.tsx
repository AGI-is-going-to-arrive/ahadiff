import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { DiagnosticRow } from '../DiagnosticRow';

// DiagnosticRow only uses useTranslation to resolve the icon aria-label.
vi.mock('../../i18n/useTranslation', () => ({
  useTranslation: () => ({
    locale: 'en-US',
    t: (key: string) => key,
  }),
}));

describe('DiagnosticRow remedy hint', () => {
  it('renders the remedy line below the row when remedy is provided', () => {
    const html = renderToStaticMarkup(
      <DiagnosticRow
        status="fail"
        text="Sensitive config keys found"
        remedy="Re-save each provider under Settings - Providers."
      />,
    );
    expect(html).toContain('diag-row__remedy');
    expect(html).toContain('Re-save each provider under Settings - Providers.');
  });

  it('omits the remedy element when remedy is undefined', () => {
    const html = renderToStaticMarkup(
      <DiagnosticRow status="fail" text="Sensitive config keys found" />,
    );
    expect(html).not.toContain('diag-row__remedy');
  });

  it('omits the remedy element when remedy is null', () => {
    const html = renderToStaticMarkup(
      <DiagnosticRow status="fail" text="Sensitive config keys found" remedy={null} />,
    );
    expect(html).not.toContain('diag-row__remedy');
  });
});
