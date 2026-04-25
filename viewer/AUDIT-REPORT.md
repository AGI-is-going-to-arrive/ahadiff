# AhaDiff Viewer v0.1 -- Full Technical Audit Report

**Date**: 2026-04-25
**Scope**: `/viewer/src/` (46 source files, 225 Playwright tests passing, 0 typecheck errors, 258.66 KB build, 80/80 i18n parity)
**Auditor**: Full 6-dimension code review covering all TSX, TS, and CSS files

---

## Anti-Patterns Verdict

**No critical anti-patterns detected.** The codebase demonstrates mature patterns: proper AbortController cleanup, Zustand selector usage, memo/callback discipline, BEM-style CSS with tokens, and comprehensive media query coverage. Two medium-severity architectural concerns noted below.

---

## Dimension Scores (0-4)

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| 1. Accessibility (WCAG AAA) | **3.0** | Strong foundation (skip-link, aria-live, keyboard nav, focus-visible, role=tablist roving tabindex). Falls short of AAA on 4 contrast pairs and heading hierarchy gap. |
| 2. Performance | **3.5** | VirtualList, memo, useCallback with correct deps, AbortController cleanup, TTL caching. Minor concern: VirtualList uses `top` instead of `transform`. |
| 3. Theming & Dark Mode | **3.5** | Full CSS custom property pipeline, comprehensive dark-mode overrides, forced-colors support, reduced-motion coverage. Minor gap: reduced-transparency file exists but is thin. |
| 4. Responsive & Cross-Browser | **3.0** | Logical properties throughout, 44px touch targets, print.css, three breakpoints. Issues: `100vh` on iOS Safari, no RTL `dir` attribute support despite logical props. |
| 5. State Management & Data Flow | **3.5** | Clean Zustand stores with selectors, TTL-based cache, monotonic token race guard, token refresh dedup. Minor: locale `initLocale` has no AbortController. |
| 6. Cross-Browser Corner Cases | **3.0** | Safari cookie race handled, `color-mix` fallback provided, `-webkit-backdrop-filter` prefixed. Gaps on `toLocaleDateString` and cookie SameSite capitalization. |
| **Overall** | **3.25** | |

---

## Findings

### P0 -- Critical (0 found)

None.

### P1 -- High (3 found)

**[P1-1]** `src/styles/tokens.css:80` + `src/styles/tokens.css:19` | Accessibility/Contrast | `--muted-strong` (#8F8878) on `--paper` (#FAF8F2) = **3.32:1**, fails WCAG AA for normal text (requires 4.5:1). Used in `sidebar__label` (10px uppercase) and KPI card labels. In dark mode the same pair is 4.83:1 (passes AA).
**Impact**: Low-vision users cannot reliably read secondary labels in light mode.
**Fix**: Darken `--muted-strong` to at least `#7A7462` (would yield ~4.55:1). Or ensure it is only used on large/bold text where 3:1 suffices.

**[P1-2]** `src/styles/tokens.css:19` | Accessibility/Contrast | `--accent` (#D27050) on `--paper` (#FAF8F2) = **3.20:1** and `--on-accent` (#FFFFFF) on `--accent` (#D27050) = **3.40:1**. Both fail WCAG AA normal text. `--accent` is used for links and the primary button text color on accent background.
**Impact**: Link text and primary button labels are below AA contrast in light mode.
**Fix**: Darken `--accent` to ~`#B85A3C` for text usage, or introduce `--accent-text` variant darker than the background accent. Keep the current `--accent` for decorative/non-text use.

**[P1-3]** `src/styles/tokens.css:36` | Accessibility/Contrast | `--warning` (#B4791F) on `--paper` (#FAF8F2) = **3.47:1**, fails AA normal text. Used as text color in verdict badges (`.verdict-badge--CAUTION`) and claim badges (`.claim-badge--weak`).
**Impact**: CAUTION verdict text and "weak" claim badges are hard to read for low-vision users.
**Fix**: Darken to ~`#946216` (would yield ~4.5:1).

### P2 -- Medium (8 found)

**[P2-1]** `src/components/VirtualList.tsx:73-76` | Performance | VirtualList positions items via `top: i * itemHeight` instead of `transform: translateY(...)`. Top-based positioning triggers layout recalculation on each scroll frame; transform is GPU-composited and avoids layout thrash.
**Impact**: Scroll jank on large diffs (>1000 lines) on low-end devices.
**Fix**: Replace `top: i * itemHeight` with `transform: translateY(${i * itemHeight}px)`, set `top: 0`.

**[P2-2]** `src/components/AppShell.css:28,149` | Cross-Browser | Uses `min-height: 100vh` and `height: 100vh` which on iOS Safari includes the URL bar height, causing content to be clipped behind the browser chrome. iOS Safari requires `100dvh` or the `-webkit-fill-available` fallback.
**Impact**: Bottom nav items may be partially hidden on iOS Safari.
**Fix**: Add fallback: `min-height: 100vh; min-height: 100dvh;` and `height: 100vh; height: 100dvh;` (or use `min-height: -webkit-fill-available` as first fallback).

**[P2-3]** `src/pages/LessonPage.tsx:165-166` | Accessibility/Heading | LessonPage has `<h1>` then `<h3>` inside the sidebar (EvidencePanel). The `<h2>` level is skipped. Per WCAG 1.3.1, heading levels should not skip (h1 -> h3 without an intervening h2).
**Impact**: Screen readers announce an unexpected heading jump, confusing document structure.
**Fix**: Either change EvidencePanel's `<h3>` to `<h2>`, or wrap the sidebar in a section with an `<h2>` heading, then keep `<h3>` inside it.

**[P2-4]** `src/state/locale-store.ts:15` | Cross-Browser/Cookie | Cookie is written with `samesite=lax` (lowercase). Per RFC 6265bis, the `SameSite` attribute value is case-insensitive in modern browsers, but some older WebKit versions and HTTP proxy caches may not recognize lowercase. Additionally, the cookie lacks `Secure` flag which means it will be sent over HTTP.
**Impact**: Minimal for localhost-only usage, but could cause issues if ever served over HTTPS.
**Fix**: Use `SameSite=Lax` (capital S) for maximum compatibility. Consider adding `Secure` conditionally when on HTTPS.

**[P2-5]** `src/state/locale-store.ts:44-60` | State Management | `initLocale()` does not use an AbortController. If the component that triggers it unmounts quickly (e.g., rapid navigation), the server response may arrive after the store has already been set by user action, causing a stale overwrite.
**Impact**: Low probability race condition on locale initialization.
**Fix**: Accept `signal?: AbortSignal` parameter, pass it to `getLocale()`, and check abort before `set()`.

**[P2-6]** `src/pages/DashboardPage.tsx:289-294` | Cross-Browser/Date | `toLocaleDateString(locale, ...)` with `month: 'short'` produces locale-dependent output. Safari may produce different month abbreviations than Chrome/Firefox for `zh-CN`. The `try/catch` handles errors but not display inconsistency.
**Impact**: Cosmetic cross-browser date display differences.
**Fix**: Consider using `Intl.DateTimeFormat` directly for more predictable output, or accept the cosmetic difference and document it.

**[P2-7]** `src/api/client.ts:29-45` | State Management | The `ensureToken()` singleton deduplication correctly prevents concurrent token fetches. However, if the first token fetch fails, `tokenPromise` is cleared in `finally` but `cachedToken` remains null. Subsequent calls will retry, which is correct. But there is no retry limit -- a server that returns persistent 500s will cause infinite retry loops from UI interactions.
**Impact**: Excessive network requests on persistent server errors.
**Fix**: Add an exponential backoff or max-retry counter to `ensureToken()`.

**[P2-8]** `src/components/ErrorBoundary.tsx:49-56` | Theming | The `DefaultErrorFallback` uses inline `style` with a hardcoded `#fff` for button text color instead of `var(--on-accent)`. This bypasses the token system and will not adapt to forced-colors or future theme changes.
**Impact**: Inconsistency with token-based theming.
**Fix**: Replace `color: '#fff'` with `color: 'var(--on-accent)'`. Better yet, move the inline styles to a CSS class.

### P3 -- Low (6 found)

**[P3-1]** `src/components/ConceptGraph.tsx:129` | Accessibility | The SVG wrapper div uses inline `style={{ position: 'relative' }}` which should be in the CSS file for consistency.
**Fix**: Move to `.concept-graph__svg-wrap` in ConceptGraph.css.

**[P3-2]** `src/components/RatchetChart.tsx:60` | Accessibility | The SVG uses `role="img"` with a `<title>` element -- correct pattern. However the Y-axis labels and data points lack `aria-hidden="true"`, so screen readers will attempt to read individual SVG text elements.
**Fix**: Add `aria-hidden="true"` to the Y-axis label `<g>` and dot `<g>` groups, since the chart's meaning is conveyed by the `<title>` and `aria-label`.

**[P3-3]** `src/components/SRSCard.tsx:146-148` | Accessibility | The correct/wrong indicator uses color alone (`var(--success)` / `var(--danger)`) to distinguish outcomes. WCAG 1.4.1 requires that color is not the sole means of conveying information. The text ("Correct"/"Wrong") does provide a textual alternative, so this passes, but adding an icon would reinforce the signal for color-blind users.
**Fix**: Optional enhancement -- prepend a checkmark/cross icon to the correct/wrong text.

**[P3-4]** `src/components/Sidebar.tsx:21-41` | Accessibility | Sidebar nav icons use Unicode characters (e.g., `'?'` for quiz). These are rendered as text, not as proper icons. The `aria-hidden="true"` on the icon span is correct, but if the font does not support the character, users see a replacement glyph. Consider using SVG icons for reliability.
**Fix**: Replace Unicode icons with inline SVGs for cross-platform glyph consistency.

**[P3-5]** `src/components/Diff.css:9` | Performance | `line-height: 22px` uses a px value which does not scale with user font-size preferences. If a user zooms text-only, the line height stays fixed.
**Fix**: Use a unitless value like `line-height: 1.69` (22/13) or keep the px value and document it as intentional for the fixed-height virtual list.

**[P3-6]** `src/styles/base.css:73-81` | Cross-Browser | `::-webkit-scrollbar` styles only affect WebKit/Blink browsers. Firefox users get the default scrollbar. Consider adding `scrollbar-width: thin; scrollbar-color: var(--hair-strong) var(--paper);` for Firefox support.
**Fix**: Add standard `scrollbar-width` and `scrollbar-color` properties as progressive enhancement.

---

## Positive Findings (Done Well)

1. **Skip-to-content link** (`AppShell.tsx:15`) -- properly implemented with `inset-inline-start` positioning and focus-activated visibility.

2. **Roving tabindex on ScaffoldingTabs** (`ScaffoldingTabs.tsx:23-39`) -- textbook WAI-ARIA tablist pattern with ArrowLeft/Right/Up/Down keyboard navigation, correct `aria-selected`, and focus management via refs.

3. **Monotonic token race guard** (`LessonPage.tsx:116-119`) -- level-change fetches use both AbortController cancellation AND a monotonic counter, preventing stale state from slow responses.

4. **AbortController discipline** -- every `useEffect` that fetches data creates a controller and aborts on cleanup. All 5 pages (Dashboard, Lesson, DiffViewer, Quiz, Concepts) follow this pattern consistently.

5. **CSS custom properties everywhere** -- zero hardcoded color values in component CSS (only in tokens.css definitions). All colors flow through the token pipeline.

6. **Comprehensive media query coverage** -- every CSS file includes `prefers-reduced-motion`, `forced-colors`, `prefers-color-scheme: dark`, and responsive breakpoints. The `reduced-transparency.css` is a nice extra.

7. **Logical CSS properties** -- zero instances of `margin-left`, `padding-right`, `border-left`, etc. All directional properties use `inline-start`/`inline-end`/`inset-block`/`inset-inline`.

8. **Touch target compliance** -- `.lang-switcher__btn` and `.sidebar__item` both have `min-height: 44px` / `min-width: 44px`, meeting the WCAG 2.5.5 AAA target size.

9. **JSONL hardening** -- both `parseClaims()` and `parseQuizJsonl()` validate every field type before accepting a record, with silent skip on malformed lines. No blind `JSON.parse()` without validation.

10. **Print stylesheet** -- hides navigation, sidebar, skip-link; adds URL annotations to links; sets page margins; prevents page-break inside cards.

11. **`color-mix()` fallback** -- `.claim-badge--weak` and `.topbar` both provide a solid-color fallback before the `color-mix()` declaration, supporting Safari < 16.2.

12. **Zustand selector usage** -- all store consumers use granular selectors (e.g., `useRunsStore((s) => s.runs)`) rather than subscribing to the entire store, preventing unnecessary re-renders.

---

## Summary

The viewer codebase is well-engineered for a v0.1 SPA. The 3 High findings are all contrast ratio issues in light mode that can be fixed by darkening 3 token values. The 8 Medium findings are real but none are blocking -- the most impactful are the iOS Safari `100vh` issue and the VirtualList `top` vs `transform` performance concern. The 6 Low findings are polish items.

The strongest aspects are the accessibility infrastructure (skip-link, roving tabindex, aria-live regions, forced-colors support) and the state management discipline (AbortController cleanup, race guards, TTL caching, selector-based subscriptions). The CSS architecture is exemplary -- 100% token-driven, logical properties only, comprehensive media query coverage across all stylesheets.

**Recommended priority**: Fix P1-1/P1-2/P1-3 (token color adjustments, 3 lines changed) -> P2-2 (100dvh, 2 lines) -> P2-1 (VirtualList transform, 2 lines) -> P2-3 (heading hierarchy, 1 line).
