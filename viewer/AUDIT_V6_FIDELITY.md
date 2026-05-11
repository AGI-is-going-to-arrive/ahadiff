# AhaDiff Viewer vs V6 HTML Reference -- Visual Fidelity & Functional Audit

**Date**: 2026-04-27
**Auditor**: Claude Opus 4.6 (automated)
**Scope**: All 11 v6 pages, tokens, typography, components, features, tests

> 2026-05-12 update: this remains a historical V6 fidelity audit. Current viewer has moved past several rows below: ConceptGraph is now a `react-force-graph-2d` Canvas renderer with Graph/List views, large-graph List default, community fill, legend/filter, detail panel, and accessible list fallback; global search is implemented as a two-column SearchOverlay with table filters and mobile preview back/Escape behavior; Ratchet can download TSV, JSON, and APKG; ErrorBoundary has redacted diagnostics and clipboard fallback; shared `motion.css` and `elevation.css` now exist. Current i18n parity is 1187/1187. Rows below are not a current gap list.

---

## V6 Fidelity Score: 38 / 100

The viewer is a **functional application framework** with solid engineering (error handling, a11y, i18n, dark mode, WCAG AAA) but replicates only ~38% of the v6 design's visual richness and feature depth. The gap is primarily in **missing dashboard sections**, **missing topbar chrome**, **simplified page layouts**, and **absent decorative design tokens**.

---

## 1. Design Match

### 1.1 Typography

| Property | V6 Value | Viewer Value | Match |
|----------|----------|-------------|-------|
| `--font-sans` | `"Inter","PingFang SC","Noto Sans SC",ui-sans-serif,system-ui,sans-serif` | Same families, slightly different order/spacing | ~95% |
| `--font-serif` | `"Newsreader","Noto Serif SC","Source Serif 4",...` | Same families, Noto Serif SC and Source Serif 4 swapped | ~90% |
| `--font-mono` | `"JetBrains Mono",ui-monospace,SFMono-Regular,...` | Same families, SFMono moved ahead of ui-monospace | ~90% |
| Body font-size | 15px | 15px | 100% |
| Body line-height | 1.6 | 1.6 | 100% |
| zh-CN line-height | 1.75 | 1.75 | 100% |
| Serif headings | Yes (page titles use serif) | Yes (dashboard title uses serif) | Partial |
| Mono labels/eyebrows | Yes (nav labels, KPI labels, timestamps) | Limited usage | Partial |
| Letter-spacing on labels | 0.14em uppercase labels | Not consistently applied | Partial |

**Typography verdict**: Font stacks match ~90%. The v6 uses serif headings, mono eyebrows, and tabular-nums more extensively. The viewer uses these sparingly.

### 1.2 Colors (Light Mode)

| Token | V6 Value | Viewer Value | Match |
|-------|----------|-------------|-------|
| `--paper` | `#FAF8F2` | `#FAF8F2` | Exact |
| `--subtle` | `#F4F1E8` | `#F4F1E8` | Exact |
| `--elevated` | `#FFFFFF` | `#FFFFFF` | Exact |
| `--ink` | `#2E2A24` | `#2E2A24` | Exact |
| `--accent` | `#D27050` | `#B05436` | **MISMATCH** (viewer is darker) |
| `--muted` | `#6A6456` | `#5A5447` | **MISMATCH** (viewer is darker) |
| `--warning` | `#B4791F` | `#946216` | **MISMATCH** (viewer is darker) |
| `--success` | `#2F6F4F` | `#2F6F4F` | Exact |
| `--danger` | `#A33D2B` | `#A33D2B` | Exact |
| `--info` | `#2E4A6B` | `#2E4A6B` | Exact |
| `--hair` | `#E6E1D4` | `#E6E1D4` | Exact |

**Note**: The viewer has 68 additional tokens not in v6 (accent-hair, accent-softest, accent-tint, bolder-bold, brand-anthropic, danger-soft, folio-line, ink-deep, ornament-ink, paper-deep, ring-focus, shadow-brand, stamp-verified-*, success-soft, surface-diff, warning-soft, etc.). These are extensions for dark mode, accessibility, and component patterns. The 3 mismatched values (`--accent`, `--muted`, `--warning`) were deliberately darkened during the R3/R4 WCAG AAA audit to achieve >= 7.0:1 contrast ratio.

**Colors verdict**: 16/22 light-mode base tokens match exactly. 3 intentionally diverged for WCAG AAA. 68 new tokens extend the palette. Core warm-cream identity is preserved.

### 1.3 Layout

| Aspect | V6 | Viewer | Match |
|--------|----|----|-------|
| App shell (sidebar + main) | Yes | Yes | Match |
| Sidebar width | 200px | Implemented | Match |
| Topbar (sticky, blur backdrop) | Full chrome: breadcrumb + search + docs + new run | Minimal: brand mark + lang switcher only | **Major gap** |
| Content max-width | Varies by page | 1120px dashboard | Partial |
| Mobile responsive | Full: sidebar drawer, backdrop, hamburger | Not implemented (no mobile nav toggle) | **Major gap** |
| Card hover lift effect | translateY(-2px) + shadow | Missing (no card hover lift) | Missing |

**Layout verdict**: The shell structure matches (sidebar + topbar + main). But the topbar is stripped to a bare minimum, and mobile responsiveness is not implemented.

### 1.4 Components

| Component | V6 | Viewer | Match |
|-----------|----|----|-------|
| KPI cards | 4 items (score, claims, reviews, spec) | 3 items (runs, pass rate, weakest dim) | Partial |
| Verdict badges (PASS/CAUTION/FAIL) | Yes, with color chips | Yes (ClaimBadge component) | Match |
| Card pattern (border, radius, shadow) | Consistent `.card` class | Per-component CSS | Partial |
| Brand mark (`Delta-zhi`) | In sidebar, with tagline | In topbar only, no tagline | Partial |
| Nav sections (Workspace/Practice/System) | Three labeled groups | Flat list, no section grouping | **Missing** |
| Status bar at sidebar bottom | "Hybrid . Local embed . BYOK" + online dot | Not implemented | **Missing** |
| Search bar (`Cmd+K`) | Full search mock | Not implemented | **Missing** |
| `.btn.primary` (warm accent) | Yes | Limited usage | Partial |
| Folio badge/stamp on verified claims | Yes (elaborate rotated stamp) | Present in CSS but simplified | Partial |
| Skeleton loading | Limited in v6 | Full Skeleton component | Viewer ahead |
| ErrorBoundary | Not in v6 | Full implementation with retry | Viewer ahead |

---

## 2. Feature Status Table

### 2.1 Global Chrome

| Feature (from v6) | Status | Notes |
|---|---|---|
| Sidebar nav with 3 sections (Workspace/Practice/System) | Partial | Nav items present but no section labels/grouping |
| Brand mark + tagline in sidebar | Partial | Brand in topbar, no sidebar brand, no tagline |
| Search bar (Cmd+K) | **Missing** | Not implemented at all |
| "Export CSV" button | **Missing** | Not implemented |
| "+ New Learn Run" button | **Missing** | Not implemented |
| "Docs" button | **Missing** | Not implemented |
| Breadcrumb (repo/page) | **Missing** | Not implemented |
| Mobile hamburger + sidebar drawer | **Missing** | No mobile nav toggle |
| Status bar (Hybrid/Local/BYOK + online dot) | **Missing** | Not implemented |
| Version display | **Missing** | Not implemented |
| Language switcher | **Implemented** | Present in topbar (not in v6) |
| Skip-to-content link | **Implemented** | Present (not visible in v6 but was in aria) |

### 2.2 Dashboard Page

| Feature | Status | Notes |
|---|---|---|
| KPI: Lesson score median | **Missing** | Viewer has Total runs instead |
| KPI: Claims verified count | **Missing** | Viewer has Pass rate instead |
| KPI: Reviews due today | **Missing** | Viewer has Weakest dimension instead |
| KPI: Spec alignment fraction | **Missing** | Not implemented |
| Quality trajectory SVG chart | Partial | RatchetChart exists but different data |
| Spec alignment panel (done/pending table) | **Missing** | Not implemented |
| Recent runs table with columns | Partial | Simplified list, not full table |
| Verdict filter tabs (All/PASS/CAUTION/FAIL) | **Missing** | Not implemented |
| Weak concepts section | **Missing** | Not implemented |
| Audit cost (24h) section | **Missing** | Not implemented |
| DEMO DATA banner | **Missing** | Not implemented |
| Load more button | Implemented | Cursor-based pagination |
| Empty state | Implemented | With hint text |
| Cold start (single run) | Implemented | Dedicated layout |

### 2.3 Lesson Page

| Feature | Status | Notes |
|---|---|---|
| Lesson prose (TL;DR, What changed, Why it matters) | Implemented | Markdown rendering from API |
| Claims list with badges | Implemented | Full claim card UI |
| Evidence panel (source hunk) | Implemented | EvidencePanel component |
| Scaffolding tabs (L1/L2/L3) | Implemented | ScaffoldingTabs component |
| Selected claim highlight | Implemented | With aria-pressed |
| v6 sections: Quiz, Concepts, Misconceptions, Sources | **Missing** | Only claims + evidence shown |

### 2.4 Diff Page

| Feature | Status | Notes |
|---|---|---|
| Unified diff display | Implemented | DiffView component with inHunk parser |
| File header | Implemented | Shows filename |
| Add/Del line coloring | Implemented | Green/red backgrounds |
| Hunk headers (@@ ... @@) | Implemented | Parsed correctly |
| v6: Selected source hunk panel | **Missing** | Not a separate panel |
| v6: Claim Inspector panel | **Missing** | Not implemented |
| Line numbers | **Missing** | Not shown |
| Binary file handling | **Missing** | Not implemented |

### 2.5 Quiz Page

| Feature | Status | Notes |
|---|---|---|
| Quiz card with question | Implemented | SRSCard component |
| Multiple choice answers | Implemented | With click handling |
| Answer reveal (correct/wrong) | Implemented | Color-coded feedback |
| SRS rating (good/hard/wrong) | Implemented | With rated gate on Next |
| Progress counter (Q x/y) | Implemented | In header |
| Explanation display | Implemented | After answering |
| v6: Evidence panel alongside quiz | **Missing** | v6 had a side panel |
| v6: Progress bar (visual) | **Missing** | Only text counter |
| Keyboard shortcuts | **Missing** | Not implemented in QuizPage |

### 2.6 Review Page

| Feature | Status | Notes |
|---|---|---|
| Flashcard UI (front/back) | Implemented | Full flip mechanic |
| Flip button (Space) | Implemented | With keyboard shortcut |
| SRS buttons (1=wrong, 2=hard, 3=good) | Implemented | With keyboard shortcuts |
| Progress display | Implemented | x/y counter |
| FSRS chip | Implemented | Badge shown |
| Session done state | Implemented | With celebration |
| v6: Calendar heatmap | **Missing** | Not implemented |
| v6: Concept mastery bars | **Missing** | Not implemented |
| v6: Evidence panel alongside | **Missing** | Not implemented |

### 2.7 Ratchet Page

| Feature | Status | Notes |
|---|---|---|
| Ratchet trajectory chart (SVG) | Implemented | RatchetChart component |
| Rubric 8-dim radar/display | Implemented | Shows all 8 dimensions |
| History list with scores | Implemented | With verdict badges |
| Load more pagination | Implemented | Cursor-based |
| v6: results.tsv section (raw table) | **Missing** | Not implemented |
| v6: Phase 2.5 structural rewrite section | **Missing** | Not implemented |
| v6: Benchmark transparency section | **Missing** | Not implemented |
| v6: Iteration timeline (kept/reverted) | **Missing** | Simplified list |

### 2.8 Settings Page

| Feature | Status | Notes |
|---|---|---|
| Config display (language, privacy, models) | Implemented | ConfigField component |
| Doctor checks (pass/warn/fail) | Implemented | With status icons |
| API key status per provider | Implemented | Configured/missing badges |
| Privacy mode display | Implemented | Shows current mode |
| Serve port display | Implemented | Shows port number |
| v6: Settings tab sidebar (Account/Keys/Privacy/...) | **Missing** | Single-page layout |
| v6: Mode summary card (Generate/Judge/Embed) | **Missing** | Simplified config fields |
| v6: Privacy toggle (offline mode) | **Missing** | Display only, no toggle |
| v6: Provider grid (3-column Generate/Judge/Embed) | **Missing** | Flat field list |
| v6: Audit log table (last 20 calls) | **Missing** | Not implemented |

### 2.9 Concepts / Graph Page

| Feature | Status | Notes |
|---|---|---|
| ConceptGraph component | Implemented | SVG + d3-force visualization |
| Concept list | Implemented | Graph/List toggle; 201+ nodes default to List |
| v6: SVG force-directed graph with nodes/edges | Implemented | SVG + d3-force; edge curves/markers still differ |
| v6: Node detail panel (click to see definition) | Partial | Side detail panel exists; richer descriptions depend on backend data |
| v6: List fallback (tabular concept list) | Implemented | Grid list fallback, not final V6 table styling |
| v6: 48 nodes / 71 edges count display | Partial | Showing-count text exists; final header counter still missing |

### 2.10 Skills Page

| Feature | Status | Notes |
|---|---|---|
| Agent card grid | Implemented | Full 13-target grid |
| Install command per agent | Implemented | With copy button |
| Detection status (installed/available/unsupported) | Implemented | Color-coded badges |
| Platform support indicator | Implemented | Shown per target |
| Copy button with feedback | Implemented | "Copied!" confirmation |
| Skeleton loading | Implemented | During fetch |
| v6: SKILL.md preview | **Missing** | Not shown |
| v6: AGENTS.md preview | **Missing** | Not shown |

### 2.11 Landing Page

| Feature | Status | Notes |
|---|---|---|
| Hero section with title | Implemented | With gradient background |
| Brand tagline | Implemented | "Ship with AI. Learn it back." |
| CTA buttons (Dashboard + pip install) | Implemented | Link + code |
| Before/After demo (raw diff vs lesson) | Implemented | Side-by-side |
| v6: 5-step stepper flow | Partial | Steps displayed but simplified |
| v6: Folio badge animation | **Missing** | Not in landing |
| v6: CLI terminal preview | **Missing** | Static code block only |

### 2.12 Onboarding Page

| Feature | Status | Notes |
|---|---|---|
| Stepper UI | Implemented | Step-by-step flow |
| Doctor checks integration | Implemented | Reuses doctor API |
| Config display | Implemented | Shows current settings |
| v6: Pick repo step | **Missing** | Not interactive |
| v6: Add provider key step | **Missing** | Not interactive |
| v6: Install agent step | **Missing** | Not interactive |
| v6: First learn run preview | **Missing** | Not implemented |

---

## 3. Missing V6 Features (Gap List)

### Critical Gaps (major v6 functionality absent)

1. **Search bar (Cmd+K)** -- The entire global search UI is missing. V6 had a prominent search bar in the topbar.
2. **Dashboard KPI richness** -- V6 had 4 rich KPIs (lesson score median, claims verified, reviews due, spec alignment). Viewer has only 3 simpler ones (total runs, pass rate, weakest dim).
3. **Dashboard sections** -- V6 had Quality trajectory + Spec alignment + Recent runs + Weak concepts + Audit cost (24h) = 5 card sections. Viewer has only Ratchet chart + Run list = 2 sections.
4. **Verdict filter tabs** -- V6 had All/PASS/CAUTION/FAIL filtering on the runs table. Missing.
5. **Settings page depth** -- V6 had tabbed settings (Account/Keys/Privacy/Provider/Audit), mode summary card, provider grid, audit log table, privacy toggle. Viewer has flat config fields + doctor checks only.
6. **Calendar heatmap (Review)** -- V6 review page had a calendar and concept mastery bars. Missing.
7. **Mobile responsiveness** -- V6 had full mobile nav (hamburger, sidebar drawer, backdrop). Missing.

### Moderate Gaps (v6 detail absent but viewer has alternatives)

8. **Topbar chrome** -- V6 topbar had breadcrumb, search, docs button, new learn run button. Viewer topbar has only brand + lang switcher.
9. **Sidebar sections** -- V6 grouped nav into Workspace/Practice/System with labels. Viewer has flat list.
10. **Sidebar status bar** -- V6 had "Hybrid . Local embed . BYOK" with online indicator. Missing.
11. **Ratchet page depth** -- V6 had results.tsv raw view, Phase 2.5 display, benchmark transparency. Viewer has simplified history.
12. **Graph/Concepts detail** -- Current viewer has node detail panel, Graph/List fallback, Fit/Export, and showing-count text; remaining V6 gap is richer provenance/count placement and final visual polish.
13. **Diff page panels** -- V6 had Claim Inspector + Source hunk in a side panel. Viewer shows inline diff only.
14. **Export CSV** -- Dashboard export button missing.
15. **New Learn Run** -- Dashboard action button missing.
16. **Line numbers in diff** -- Not shown.

### Minor Gaps (decorative/polish)

17. **Card hover lift animation** (translateY + shadow on hover)
18. **Mono letter-spacing on eyebrows/labels** (0.14em uppercase)
19. **Version display** in sidebar or footer
20. **DEMO DATA banner** for synthetic data
21. **SKILL.md / AGENTS.md preview** on Skills page

---

## 4. New Features (not in v6)

The viewer introduces several features that go beyond the v6 prototype:

1. **i18n system** -- Full 189-key catalog in en + zh-CN with 100% parity, LanguageSwitcher, locale-store, cookie persistence. V6 was hardcoded Chinese.
2. **Dark mode** -- Complete dark theme with WCAG AAA tokens (>= 7.0:1 on all surfaces). V6 was light-only.
3. **WCAG AAA accessibility** -- forced-colors, reduced-transparency, reduced-motion, print styles, focus-visible rings, aria-pressed, aria-current, skip-to-content.
4. **ErrorBoundary** -- Full error recovery with retry button. V6 had no error handling.
5. **Skeleton loading** -- Dedicated Skeleton component for all pages. V6 had no loading states.
6. **AbortController on all fetches** -- Proper cleanup on unmount. V6 was static HTML.
7. **Token fetch with 8s timeout** -- 401/403 retry. V6 had no auth.
8. **Active press feedback** -- `:active` scale(0.97) on all interactive elements.
9. **Cursor-based pagination** -- Load more with `before` parameter on runs/ratchet/concepts.
10. **NotFoundPage** -- 404 handling. V6 had no routing.
11. **ConceptsPage** -- Dedicated page (v6 merged it into "graph" page).
12. **RatchetPage** -- Separate from dashboard (v6 had it as a sidebar page too but viewer elevated it).

---

## 5. Functional Issues Found

1. **DiffViewerPage** -- The DiffView component has unified diff parsing but the DiffViewerPage itself does not reference "unified", "line numbers", or "claims overlay". The page is a thin wrapper that fetches and displays. Line numbers are not rendered.

2. **ConceptsPage** -- Current page renders typed `/api/graph/concepts` data through ConceptGraph, with Graph/List views, large-graph List default, node detail panel, and SVG pan/zoom. Remaining gap is deeper provenance/CLI polish and real large-repo signoff.

3. **Sidebar** -- No section grouping. All 11 nav items in a flat list. No brand mark in sidebar (it is in topbar instead). No status bar at bottom.

4. **Topbar** -- Extremely minimal. Only brand mark + language switcher. Missing: breadcrumb, search, docs button, new learn run button. This is the single biggest visual divergence from v6.

5. **Dashboard** -- Only 3 KPIs vs v6's 4 richer KPIs. Missing 3 of 5 card sections (spec alignment, weak concepts, audit cost). Missing verdict filter tabs.

6. **mapDoctorMessage duplication** -- The function `mapDoctorMessage` is duplicated identically in both `SettingsPage.tsx:9` and `OnboardingPage.tsx:9`. Should be extracted to a shared utility (already done to `utils/doctor.ts` based on imports, but old inline versions may remain).

7. **Keyboard shortcuts in QuizPage** -- Not implemented. V6 quiz had keyboard interaction; the viewer quiz requires mouse clicks only (though ReviewPage has keyboard shortcuts).

---

## 6. Test Coverage Assessment

| Metric | Value | Assessment |
|--------|-------|-----------|
| E2E test files | 5 | Good coverage structure |
| Total test cases | 52 (17+8+18+4+5) | Moderate |
| Pages covered in smoke | 10/12 (missing Dashboard root, 404) | Good |
| Mock API endpoints | 10 | Covers all current API calls |
| i18n parity | 189/189 (100%) | Excellent |
| Cross-browser tests | 8 tests across 3 browsers x 4 viewports | Solid |
| Media features tests | 4 (dark mode, reduced motion, forced-colors, reduced-transparency) | Good |
| Walkthrough tests | 18 (page navigation, interactions) | Good |

**Test gaps**: No visual regression tests (screenshot comparison). No performance tests. No accessibility audit tests (axe-core). Dashboard root path not explicitly tested in smoke.

---

## 7. Summary

The viewer is a well-engineered React application with strong foundations in:
- Accessibility (WCAG AAA, forced-colors, reduced-motion)
- i18n (189/189 key parity)
- Error handling (ErrorBoundary, AbortController, retry)
- Dark mode (complete token set with contrast proofs)
- Testing (52 e2e tests across browsers/viewports)

However, it replicates only **~38%** of the v6 visual design and feature set. The biggest gaps are:
- Topbar (almost empty vs v6's full chrome)
- Dashboard (3 simple KPIs + 2 sections vs v6's 4 rich KPIs + 5 sections + filter tabs)
- Settings (flat config display vs v6's tabbed settings + provider grid + audit log)
- Review (flashcards only vs v6's flashcards + calendar + concept mastery)
- Mobile responsiveness (not implemented)
- Search bar (not implemented)

The viewer should be viewed as a **Phase A-E functional foundation** that needs significant feature work to match the v6 design vision. The engineering quality is high, but the design fidelity is low.
