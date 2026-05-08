import React from 'react';

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFKC')
    .replace(/[^\p{L}\p{N}\s-]/gu, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
}

export function uniqueSlug(label: string, seen: Set<string>): string {
  const base = slugify(label) || 'section';
  let id = base;
  if (seen.has(id)) {
    let counter = 2;
    while (seen.has(`${base}-${counter}`)) counter++;
    id = `${base}-${counter}`;
  }
  seen.add(id);
  return id;
}

export function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`/g;
  let lastIndex = 0;
  let tokenIndex = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    if (match[1] != null) {
      nodes.push(<strong key={`${keyPrefix}-b-${tokenIndex++}`}>{match[1]}</strong>);
    } else {
      nodes.push(<code key={`${keyPrefix}-code-${tokenIndex++}`}>{match[2]}</code>);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes.length > 0 ? nodes : [text];
}

export function renderMarkdownProse(content: string, classPrefix = 'lesson'): React.ReactNode[] | null {
  if (!content) return null;
  const lines = content.split('\n');
  const elements: React.ReactNode[] = [];
  const headingSlugs = new Set<string>();
  let paragraphLines: string[] = [];
  let listItems: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  let codeLines: string[] | null = null;
  let codeLanguage = '';
  let blockKey = 0;

  const flushParagraph = () => {
    const text = paragraphLines.join(' ').trim();
    if (text) {
      const key = `paragraph-${blockKey++}`;
      elements.push(
        <p key={key} className={`${classPrefix}__paragraph`}>
          {renderInline(text, key)}
        </p>,
      );
    }
    paragraphLines = [];
  };

  const flushList = () => {
    if (!listType || listItems.length === 0) return;
    const key = `list-${blockKey++}`;
    const ListTag = listType;
    elements.push(
      <ListTag key={key} className={`${classPrefix}__list ${classPrefix}__list--${listType}`}>
        {listItems.map((item, index) => (
          <li key={`${key}-item-${index}`}>{renderInline(item, `${key}-item-${index}`)}</li>
        ))}
      </ListTag>,
    );
    listItems = [];
    listType = null;
  };

  const flushCode = () => {
    if (codeLines === null) return;
    elements.push(
      <pre
        key={`code-${blockKey++}`}
        className={`${classPrefix}__code-block`}
        data-language={codeLanguage || undefined}
      >
        <code>{codeLines.join('\n')}</code>
      </pre>,
    );
    codeLines = null;
    codeLanguage = '';
  };

  for (const rawLine of lines) {
    const trimmedLine = rawLine.trim();

    if (codeLines !== null) {
      if (trimmedLine.startsWith('```')) flushCode();
      else codeLines.push(rawLine);
      continue;
    }

    const fenceMatch = /^```\s*([\w.-]+)?/.exec(trimmedLine);
    if (fenceMatch) {
      flushParagraph();
      flushList();
      codeLines = [];
      codeLanguage = fenceMatch[1] ?? '';
      continue;
    }

    if (!trimmedLine) {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = /^(#{1,3})\s+(.+)$/.exec(trimmedLine);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const label = headingMatch[2].trim();
      const slug = uniqueSlug(label, headingSlugs);
      // Markdown headings inside an article render below the page-level <h1>.
      // Lesson markdown emits `##` for top-level sections (TL;DR / What
      // Changed / Walkthrough / Claims), so map `#`/`##` -> h2 and `###` -> h3
      // to keep the document outline as h1 > h2 > h3 (sidebar uses h3 too).
      const headingLevel = Math.max(2, Math.min(headingMatch[1].length, 3));
      const Tag = (`h${headingLevel}`) as 'h2' | 'h3';
      elements.push(
        <Tag key={`heading-${slug}`} id={slug} tabIndex={-1} className={`${classPrefix}__section-heading`}>
          {label}
        </Tag>,
      );
      continue;
    }

    const unorderedMatch = /^\s*[-*+]\s+(.+)$/.exec(rawLine);
    const orderedMatch = /^\s*\d+[.)]\s+(.+)$/.exec(rawLine);
    if (unorderedMatch || orderedMatch) {
      flushParagraph();
      const nextType = orderedMatch ? 'ol' : 'ul';
      if (listType && listType !== nextType) flushList();
      listType = nextType;
      listItems.push((orderedMatch?.[1] ?? unorderedMatch?.[1] ?? '').trim());
      continue;
    }

    flushList();
    paragraphLines.push(trimmedLine);
  }

  flushParagraph();
  flushList();
  flushCode();
  return elements;
}
