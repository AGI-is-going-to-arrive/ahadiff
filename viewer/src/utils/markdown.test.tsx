import type React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { renderMarkdownCollapsible } from './markdown';

function render(nodes: React.ReactNode[] | null): string {
  return renderToStaticMarkup(<>{nodes}</>);
}

describe('renderMarkdownCollapsible', () => {
  it('groups H2 sections and preserves preamble content', () => {
    const html = render(renderMarkdownCollapsible([
      'Intro before headings.',
      '',
      '## First section',
      'First body.',
      '',
      '## Second section',
      'Second body.',
    ].join('\n'), 'hero-demo'));

    expect((html.match(/<details/g) ?? []).length).toBe(2);
    expect(html.indexOf('Intro before headings.')).toBeLessThan(html.indexOf('<details'));
    expect(html).toContain('First section');
    expect(html).toContain('Second body.');
  });

  it('falls back to flat prose when markdown has no H2 sections', () => {
    const html = render(renderMarkdownCollapsible('Intro only.\n\n### Deep detail', 'hero-demo'));

    expect(html).not.toContain('<details');
    expect(html).toContain('Intro only.');
    expect(html).toContain('Deep detail');
  });

  it('keeps H3 content inside the current H2 section', () => {
    const html = render(renderMarkdownCollapsible('## First\n\n### Deep detail\n\nBody.', 'hero-demo'));

    expect((html.match(/<details/g) ?? []).length).toBe(1);
    expect(html).toContain('<h3');
    expect(html).toContain('Deep detail');
    expect(html).toContain('Body.');
  });
});
