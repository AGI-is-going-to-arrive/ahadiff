# v1.0 Frontend Architecture Research Report

> Research-only. No code changes. Based on reading all gap analysis docs, V6 HTML reference, Blueprint HTML, and current viewer source.

> Current-state note (2026-05-02): sections 11.4 and 11.6 were written before the latest viewer follow-up. The frontend now has a shared `GraphifyCard` backed by `viewer/src/state/graph-store.ts` with 30s TTL, 15s request timeout, in-flight dedupe, `AbortController`, and invalidate-then-refetch behavior. This closes the basic cross-page freshness/status card gap where the card is mounted. It does **not** close the full V6 Graphify source card, provenance display, CLI polish, or real large-graph signoff work.
> Current-state note (2026-05-09): this remains a research snapshot, not the current implementation ledger. The v0.1 SRS UI intentionally hides Easy and keeps only Wrong / Hard / Good visible; Topbar Learn Run now opens the lazy-loaded Learn Mode Dialog with 10 capture modes, `/api/learn/estimate` preflight, and working-tree Path scope; Settings has a 7-tab shape with Preferences for language, appearance, `learnability_threshold`, and `desired_retention`. Settings tabs consume `?tab=provider` / `?tab=capture` / `?tab=integrations`; Integrations and Skills now use the protected install API for preview/install/uninstall with manifest-hash confirmation, pending/success/error states, and re-detect after writes. Ratchet TSV export is implemented. SearchOverlay-generated `#/concepts?focus=...` and `#/review?card=...` links are consumed by the target pages. ConceptGraph no longer has cluster/group-by-kind mode: it now exposes Graph / List only, defaults 201+ nodes to List, keeps Full graph available, supports full-graph pan/zoom without hard viewport bounds, and strips local home/system prefixes from displayed node file paths. Task progress now uses SSE first with polling fallback. The PWA manifest has same-origin `id` / `scope` and SVG + 192/512 PNG icons; the offline shell still needs its own E2E/signoff. See `doc/FRONTEND_GAP_REPORT.md` for the current closed/open gap list.
> Current-state note (2026-05-10): SearchOverlay now has table scope filter chips wired to `/api/search?tables=...` with radio-style arrow-key navigation. Settings now shows usage per model and audit load-more pagination. Run Detail shows extra metadata plus localized degraded flags, and Dashboard shows stable concepts / last run KPI. The CI description in this research note is older than the current workflow; `.github/workflows/frontend-ci.yml` now runs Chromium desktop full E2E plus Firefox and WebKit desktop smoke/a11y.

---

## 1. Proposed Frontend Staging (v1.0 one-shot, internal stages)

v1.0 frontend is one Full Scope milestone. F1-F5 below are execution batches inside the same v1.0 delivery, not a Core/Full split.

### Stage F1: Chrome + Layout Foundation (~1,200 LOC, 1-2 days)

**Scope**: Sidebar 3-section grouping, Topbar chrome, mobile hamburger/drawer, global responsive breakpoints.

**Gate criteria**: Sidebar shows 3 labeled sections (Workspace/Practice/System) with bilingual labels + English abbreviation; Topbar has breadcrumb + "New Run" button; mobile <768px shows hamburger + sidebar drawer + backdrop; all existing Playwright tests still pass.

**Dependency**: No backend changes needed. Pure CSS + TSX refactor.

**Work items**:
| Item | Current | Target | LOC | Risk |
|------|---------|--------|-----|------|
| Sidebar 3-section grouping | Single flat `<div class="sidebar__section">` with one "Navigation" label | 3 `<nav>` with `nav-label`: `工作区·Workspace`, `学习·Practice`, `系统·System` | ~80 TSX + ~40 CSS | Low — additive |
| Sidebar bilingual nav items | `<span class="sidebar__icon">▤</span><span>{t(key)}</span>` | `<span class="ic">◎</span><span>首页</span><span class="en">Landing</span>` (icon + Chinese + English abbrev) | ~60 TSX + ~30 CSS | Medium — i18n key structure change |
| Sidebar status bar footer | Not present | `<div class="side-foot">` with green dot + host:port read from serve status/config, defaulting to `127.0.0.1:8765`, plus version | ~30 TSX + ~20 CSS | Low — needs serve info from API |
| Sidebar brand block move | Brand in Topbar | Brand block (`brand-mark` + `brand-name`) in sidebar header per V6 | ~40 TSX + ~20 CSS | Medium — layout shift |
| Topbar breadcrumb | Brand mark + brand name only | `<div class="crumb">repo / page</div>` with react-router location | ~40 TSX + ~20 CSS | Low |
| Topbar "New Learn Run" button | Not present | `<button class="btn primary">+ New Run</button>` | ~10 TSX | Low |
| Topbar search bar shell (visual only) | Not present | `<div class="search" role="search">` with Cmd+K hint, non-functional | ~60 TSX + ~30 CSS | Low |
| Mobile hamburger + drawer | Bottom nav bar at <768px (horizontal scroll) | V6: hamburger button shows, sidebar becomes fixed drawer with backdrop + translateX transition | ~80 TSX + ~60 CSS | **High** — current mobile uses bottom-nav pattern; V6 uses drawer. Major restructure of `@media (max-width: 767px)` block |
| 7 responsive breakpoints | Only 767px breakpoint | V6: 540/720/768/780/900/1024/1280px | ~120 CSS | Medium — cascade complexity |

**Impact on existing tests**: Smoke tests check heading visibility + element counts. Sidebar restructure will break selectors like `.sidebar__section`, `.sidebar__label`, `.sidebar__item`. Need to update ~15 selectors in smoke/walkthrough tests. Estimated ~60 LOC test updates.

### Stage F2: Page Layout Refactors (~1,100 LOC, 1-2 days)

**Scope**: Lesson 3-column layout, Diff split layout, Settings tab sidebar, Dashboard enrichment.

**Gate criteria**: Lesson shows TOC/prose/rail 3-column grid collapsing to 1-col on mobile; Diff shows diff+claim-inspector split; Settings has tab sidebar navigation; Dashboard has 4 KPIs + verdict filter.

**Dependency**: Some backend API additions needed (see notes per item).

**Work items**:
| Item | Current | Target | LOC | Risk |
|------|---------|--------|-----|------|
| Lesson 3-column grid | Single column with EvidencePanel below | `grid-template-columns: 220px 1fr 320px` (TOC / prose / rail), responsive collapse to 1fr | ~80 CSS + ~40 TSX | **High** — significant LessonPage restructure |
| Lesson TOC sidebar | Not present | Sticky left column with section headings, scroll spy, active section highlight | ~100 TSX + ~40 CSS | Medium — needs scroll intersection observer |
| Lesson prose typography | Basic pre-formatted text | V6: serif font 17px, line-height 1.8, structured sections (TL;DR, What changed, Why it matters, Claims, Walkthrough) | ~60 CSS | Low |
| Lesson "Mark as learned" + PASS badge | Not present | Primary button + `<span class="badge pass">PASS · 88</span>` in header | ~30 TSX + ~15 CSS | Low — needs signal API |
| Diff split layout | Single column with BottomMiniPanel | `grid-template-columns: 1fr 380px` (diff + claim inspector) | ~30 CSS + ~20 TSX | Medium |
| Diff Claim Inspector panel | BottomMiniPanel shows stats only | Sticky right panel with claim list, click to highlight hunk | ~120 TSX + ~60 CSS | **High** — new component + claim-hunk linking |
| Settings tab sidebar | Single-page flat layout | V6: 8 tabs (Account/Keys/Privacy/Install/VCR/Audit/Provider/About) with sidebar nav | ~80 TSX + ~40 CSS | Medium |
| Settings Mode Summary card | Flat field list | Generate/Judge/Embed 3-column grid | ~60 TSX + ~30 CSS | Medium — needs provider config API |
| Dashboard 4th KPI | 3 KPIs | V6: lesson score median, claims verified, reviews due, spec alignment | ~30 TSX + ~15 CSS | Low — needs 1 new API field |
| Dashboard verdict filter tabs | Not present | All/PASS/CAUTION/FAIL tabs on runs table | ~50 TSX + ~20 CSS | Low |
| Dashboard 5 sections | 2 sections (chart + runs) | V6: Quality trajectory + Spec alignment + Recent runs + Weak concepts + Audit cost | ~120 TSX + ~60 CSS | Medium — some need new API endpoints |

**Impact on existing tests**: LessonPage, DiffViewerPage, SettingsPage, DashboardPage tests will need layout-aware selector updates. Estimated ~80 LOC test updates.

### Stage F3: New Components + Features (~1,200 LOC, 1-2 days)

**Scope**: Calendar heatmap, search overlay (Cmd+K functional), provider grid, audit log table, 4th SRS "Easy" button, scaffolding state display, misconception cards, concept graph improvements.

**Gate criteria**: Heatmap renders review activity; Cmd+K opens search modal; SRS has 4 rating buttons; scaffolding level badge visible on cards; concept graph has typed nodes + filter chips.

**Dependency**: Multiple new backend endpoints needed (usage/audit API, search API, `ReviewAnswer` type expansion).

**New components**:
| Component | Complexity | LOC | Backend Dependency |
|-----------|-----------|-----|--------------------|
| CalendarHeatmap | Medium | ~120 TSX + ~50 CSS | New `/api/review/activity` endpoint returning 30-day card-per-day counts |
| SearchOverlay (Cmd+K modal) | **High** | ~200 TSX + ~80 CSS | New `/api/search` endpoint (claims + concepts + commits) |
| ProviderGrid | Medium | ~80 TSX + ~40 CSS | Extend `/api/config` to include provider matrix |
| AuditLogTable | Medium | ~100 TSX + ~40 CSS | New `/api/audit/recent` endpoint from `audit.jsonl` |
| SpecAlignmentPanel | Low | ~60 TSX + ~30 CSS | Extend run detail with spec alignment score |
| WeakConceptsSection | Low | ~50 TSX + ~20 CSS | Extend `/api/concepts` with weakness filter |
| DashboardVerdictFilterTabs | Low | ~50 TSX + ~20 CSS | None — client-side filter |

**Impact on existing tests**: New components need new test suites. Existing tests unaffected.

### Stage F4: Zod + PWA + Polish (~430 LOC, 1 day)

**Scope**: Zod runtime validation, PWA support, visual polish, i18n completion, accessibility audit.

**Gate criteria**: All API responses validated by Zod; PWA installable with offline shell; WCAG AAA maintained; all new i18n keys at parity.

**Work items**:
| Item | LOC | Notes |
|------|-----|-------|
| Zod schemas + integration | ~200 | See Section 4 below |
| PWA: manifest.json + service worker + vite-plugin-pwa | ~80 | See Section 10 below |
| Visual polish: animation timing, transition easing, micro-interactions | ~80 CSS | Low risk |
| i18n key completion | ~50 JSON | See Section 8 below |
| axe-core accessibility audit test | ~20 | Add to Playwright |

---

## 2. Structural Refactors (P0-P1) — Detailed Analysis

### 2.1 Sidebar 3-Section Grouping

**Current structure** (`Sidebar.tsx`):
```
sidebar > sidebar__section > sidebar__label("Navigation") > [sidebar__item * N]
```

**Target structure** (V6):
```
sidebar > sidebar__brand-block
        > nav.nav-section[aria-label="Workspace"]
            > nav-label("工作区 · Workspace")
            > nav-item[data-goto="landing"] > ic + 首页 + .en(Landing)
            > nav-item[data-goto="dashboard"] > ...
            > nav-item[data-goto="lesson"] > ...
            > nav-item[data-goto="diff"] > ...
            > nav-item[data-goto="ratchet"] > ...
        > nav.nav-section[aria-label="Practice"]
            > nav-label("学习 · Practice")
            > nav-item[data-goto="quiz"] > ...
            > nav-item[data-goto="review"] > ...
            > nav-item[data-goto="graph"] > ...
        > nav.nav-section[aria-label="System"]
            > nav-label("系统 · System")
            > nav-item[data-goto="settings"] > ...
            > nav-item[data-goto="skills"] > ...
            > nav-item[data-goto="onboarding"] > ...
        > side-foot (status bar)
```

**Approach**: Refactor `Sidebar.tsx` to group nav items into 3 sections with a `NAV_SECTIONS` config array. Each nav item gets a bilingual structure: icon + Chinese label + English abbreviation. The English abbreviation uses `.en` class with mono font, auto margin-left (V6 line 66: `.nav-item .en{color:var(--muted-2);font-family:var(--font-mono);font-size:10px;margin-left:auto;letter-spacing:.08em;text-transform:uppercase}`).

**i18n impact**: Currently nav items use `t('Nav.dashboard')` etc. For bilingual display, each item needs both `label_zh` and `label_en` regardless of locale (V6 always shows both). This is a design choice, NOT a locale switch — the sidebar always shows dual-language labels. Simplest approach: hardcode the English abbreviations as part of the nav config since they're decorative, not localized content.

**CSS changes**: Replace `.sidebar__section`/`.sidebar__label`/`.sidebar__item` with `.nav-section`/`.nav-label`/`.nav-item` to match V6 class names, or keep existing BEM naming with the V6 visual styles. Recommend keeping BEM naming for consistency with the rest of the codebase but applying V6's visual treatment.

**Mobile impact**: Current mobile (<768px) turns sidebar into horizontal bottom nav. V6 uses hamburger + drawer. This is the **highest-risk refactor** — the entire mobile sidebar paradigm changes. Current behavior:
- `<768px`: sidebar becomes `position:fixed; bottom:0; flex-direction:row` (bottom tab bar)
- V6: sidebar becomes `position:fixed; translateX(-100%)` (hidden drawer) + hamburger button in topbar + backdrop overlay

**Estimated test breakage**: ~15 selectors in smoke/walkthrough tests reference `.sidebar__section`, `.sidebar__label`, `.sidebar__item`. All need updating.

### 2.2 Topbar Chrome

**Current** (`Topbar.tsx`): `topbar > topbar__brand (Δ知 + 知返 AhaDiff) > topbar__spacer > LanguageSwitcher`

**Target** (V6): `topbar > crumb (repo/page) > search (Cmd+K) > spacer > btn(Docs) + btn(New Run) + LanguageSwitcher`

**Approach**: 
1. Move brand block to sidebar header (per V6 design)
2. Add `<Breadcrumb />` component using `useLocation()` from react-router
3. Add search bar shell (`role="search"`, non-functional in F1, functional Cmd+K modal in F3)
4. Add "Docs" ghost button + "New Run" primary button
5. Keep LanguageSwitcher in topbar (diverges from V6 which has none in topbar — pragmatic choice since sidebar footer on mobile drawer is less accessible)

**Breadcrumb logic**: Parse `useLocation().pathname` to derive `repo / page` display. For run-scoped pages (`/run/:runId/lesson`), show `知返 / Lesson / {run_id_short}`.

### 2.3 Mobile Responsiveness

**Current state**: Single breakpoint at 767px. Sidebar becomes horizontal bottom nav. No hamburger/drawer.

**V6 breakpoints** (7 total):
| Breakpoint | Effect |
|-----------|--------|
| `max-width: 1024px` | Sidebar → fixed drawer, hamburger shows, reader → single-column, search shrinks to 160px |
| `max-width: 900px` | Settings stacks, provider grid → 1-col |
| `max-width: 780px` | Mode summary grid → 2-col |
| `max-width: 768px` | KPI/agent grid → 1-col, page headers stack, ALL 2-col layouts → 1fr, search hidden |
| `max-width: 720px` | Mode summary → 1-col |
| `max-width: 540px` | Compact adjustments |
| `min-width: 1025px` | Drawer backdrop forced hidden |

**Approach**: Replace bottom-nav pattern with V6 drawer pattern:
1. Add `.mobile-nav-btn` (hamburger) to Topbar, hidden at `>=1025px`
2. Sidebar gets `transform: translateX(-100%)` at `<1025px`, toggled by state
3. Add `.sidebar-backdrop` overlay div
4. Breakpoint cascade: 1024 → 900 → 780 → 768 → 720 → 540

**Risk**: **HIGH**. This inverts the current mobile paradigm. Current Playwright tests at 375px/360px viewport check for bottom-nav behavior. All mobile tests need rewriting for drawer behavior.

### 2.4 Lesson 3-Column Layout

**Current** (`LessonPage.tsx`): Single column. EvidencePanel and ScaffoldingTabs rendered below lesson content.

**Target** (V6): `grid-template-columns: 220px 1fr 320px`:
- **Left 220px**: TOC sidebar (sticky) with section headings, scroll spy, active highlight
- **Center 1fr**: Prose body with structured sections (TL;DR, What changed, Why it matters, Claims, Walkthrough, Quiz, Concepts, Misconceptions, Sources), serif font 17px, line-height 1.8
- **Right 320px**: Claim Inspector (sticky) + ScaffoldingTabs + evidence source hunk

**Approach**:
1. Extract `LessonTOC` component with `IntersectionObserver` scroll spy
2. Restructure `LessonPage` grid to 3-column
3. Move EvidencePanel and ScaffoldingTabs into right rail
4. Add responsive collapse: at `<1024px` → 1fr (TOC collapses to inline dropdown, rail goes below prose)
5. Prose typography: add `.prose` class with V6 styling

**Backend dependency**: Lesson content is currently raw markdown. Structured sections (TL;DR, What changed, etc.) require prompt engineering to generate labeled sections, or frontend parsing of markdown headings. Recommend frontend parsing of `## TL;DR`, `## What Changed`, etc. from lesson markdown.

### 2.5 Diff Split Layout

**Current** (`DiffViewerPage.tsx`): Single column with DiffView + BottomMiniPanel stats.

**Target**: `grid-template-columns: 1fr 380px` (diff + claim inspector panel)

**Approach**:
1. Add `ClaimInspector` component (sticky right panel)
2. List all claims for the run with verdict badges
3. Click claim → scroll DiffView to matching hunk + highlight
4. Responsive: at `<1024px` → claim inspector moves below diff

**Backend dependency**: Claims are already available via `/api/run/:id/claims`. Hunk-claim linking needs claim's `file:line` evidence to map to diff hunks — this data exists in `ClaimRecord` but needs exposure in the API response.

### 2.6 Settings 8-Tab Sidebar

**Current** (`SettingsPage.tsx`): Flat layout with config fields + doctor checks.

**Target**: Left sidebar with 8 tabs: Account / Keys / Privacy / Install / VCR / Audit / Provider / About

**Approach**:
1. Add `SettingsTabs` component with vertical tab list
2. Each tab renders a content panel
3. Router: use `?tab=keys` query param (no route change) or hash fragments
4. Provider grid: 3-column (Generate/Judge/Embed) with model + endpoint + status per cell
5. Audit log table: last 20 provider calls with time/model/tokens/cost

**Backend dependency**:
- Provider grid: needs extended `/api/config` to return provider matrix (generate_model, judge_model, embed_model + their endpoints + status)
- Audit log: needs new `/api/audit/recent` endpoint reading from `audit.jsonl`
- Privacy toggle: needs new POST endpoint to toggle privacy mode
- VCR status: needs new `/api/vcr/status` endpoint (or fold into `/api/config`)

---

## 3. New UI Components Needed

| Component | Complexity | Est. LOC | Description |
|-----------|-----------|----------|-------------|
| `CalendarHeatmap` | Medium | 170 | 30-day grid (10x3), color intensity by review count. V6 uses `display:grid;grid-template-columns:repeat(10,1fr);gap:3px`. Dynamic JS fills cells. |
| `SearchOverlay` | **High** | 280 | Modal triggered by Cmd+K or click. Search input + results grouped by type (claims/concepts/commits). Needs debounced API call. |
| `ForceGraphEnhanced` | **High** | 250 | Extend current ConceptGraph with: typed node shapes (repo=grey circle, diff=rect, symbol=filled, verified=green, weak=yellow per V6 SVG), filter chips (All/This Diff/From Graphify/Learning Memory/Weak Claims), legend bar. |
| `ProviderGrid` | Medium | 120 | 3-column matrix: Generate/Judge/Embed rows × model/endpoint/status columns. |
| `AuditLogTable` | Medium | 140 | Sortable table: time, model, tokens in/out, cost, latency. Pagination. |
| `SpecAlignmentPanel` | Low | 90 | Dashboard card showing spec compliance score + breakdown. |
| `WeakConceptsSection` | Low | 70 | Dashboard card listing concepts with lowest mastery scores. |
| `ClaimInspector` | **High** | 180 | Sticky sidebar panel for Diff/Lesson pages. Claim list with verdict badges, click-to-highlight. |
| `LessonTOC` | Medium | 140 | Sticky left sidebar. Parses lesson markdown headings. IntersectionObserver scroll spy. |
| `Breadcrumb` | Low | 60 | `useLocation()` path parser → breadcrumb trail. |
| `MobileDrawer` | Medium | 140 | Sidebar drawer + backdrop + hamburger. Replaces bottom-nav. |
| `SettingsTabs` | Medium | 120 | Vertical tab navigation for Settings page. |

**Total new components**: 12, ~1,760 LOC

---

## 4. Zod Runtime Validation Plan

### Current State

- `api/types.ts`: 30+ TypeScript interfaces with NO runtime validation
- `api/client.ts`: `apiFetch<T>` casts `res.json() as T` — zero runtime checking
- `api/runs.ts`, `api/review.ts`, `api/locale.ts`, `api/config.ts`: all use `apiFetch<T>` with type assertion

### Proposed Approach

**New dependency**: `zod` (~13KB gzipped)

**Integration strategy**: Create `api/schemas.ts` with Zod schemas mirroring `api/types.ts`. Add a `safeParse` wrapper around `apiFetch`:

```typescript
// api/schemas.ts
import { z } from 'zod';

export const RunSummarySchema = z.object({
  run_id: z.string(),
  source_ref: z.string(),
  source_kind: z.string(),
  // ...
});

// api/client.ts — add validated variant
export async function apiFetchValidated<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: ApiFetchOptions,
): Promise<T> {
  const raw = await apiFetch<unknown>(path, init);
  return schema.parse(raw);
}
```

### Endpoints needing Zod schemas (priority order)

| Endpoint | Schema | Priority | Reason |
|----------|--------|----------|--------|
| `GET /api/runs` | `PaginatedRunsResponseSchema` | P0 | Most-used, complex nested type |
| `GET /api/run/:id` | `RunDetailSchema` | P0 | Complex, many optional fields |
| `GET /api/review/queue` | `ReviewQueueResponseSchema` | P0 | Drives SRS card rendering |
| `POST /api/review/rate` | `ReviewRateResponseSchema` | P1 | Write path, important to validate |
| `GET /api/run/:id/lesson` | `RunArtifactEnvelopeSchema` | P1 | Content is raw string, but envelope matters |
| `GET /api/concepts` | `PaginatedConceptsResponseSchema` | P1 | Paginated |
| `GET /api/ratchet/history` | `RatchetHistoryResponseSchema` | P2 | Read-only display |
| `GET /api/config` | `ConfigResponseSchema` | P2 | Settings display |
| `GET /api/doctor` | `DoctorResponseSchema` | P2 | Diagnostic |
| `GET /api/auth/token` | `AuthTokenResponseSchema` | P0 | Security-critical |

**Estimated LOC**: ~200 (schemas: ~150, integration: ~50)

**Migration path**: Can be done incrementally — add `apiFetchValidated` alongside existing `apiFetch`, migrate endpoint by endpoint. No big-bang needed.

---

## 5. 4th SRS "Easy" Button

### Current State

**Frontend** (`SRSCard.tsx`):
- 3 rating buttons: `good`, `hard`, `wrong` (mapped from `SrsRating` type)
- `SrsRating = 'good' | 'hard' | 'wrong' | 'archive' | 'suspend'`
- `ReviewAnswer` type in `api/types.ts`: `'good' | 'hard' | 'wrong'`

**Backend** (`review/schemas.py`):
- `ReviewAnswer = Literal["good", "hard", "wrong"]` — **no "easy"**

**FSRS library** (`review/scheduler.py`):
- Imports `from fsrs import Rating` which has: `Rating.Again (1)`, `Rating.Hard (2)`, `Rating.Good (3)`, `Rating.Easy (4)`
- `rating_for_answer()` maps: `good→Rating.Good(3)`, `hard→Rating.Hard(2)`, `wrong→Rating.Again(1)`
- **Rating.Easy (4) is NOT mapped** — the backend explicitly doesn't support it

### Changes Required

**Backend** (Codex scope):
1. `review/schemas.py`: Add `"easy"` to `ReviewAnswer = Literal["good", "hard", "easy", "wrong"]`
2. `review/scheduler.py`: Add `if answer == "easy": return Rating.Easy` to `rating_for_answer()`
3. `review/scheduler.py`: Remove or adjust the peeked constraint (currently "peeked cards cannot be reviewed as good" — need to decide if peeked+easy is also blocked)
4. Tests: Update `ReviewAnswer` validation tests

**Frontend**:
1. `api/types.ts`: Add `'easy'` to `ReviewAnswer`
2. `SRSCard.tsx`: Add 4th button between "good" and the secondary actions
3. `review-store.ts`: No changes needed — `rate(answer)` already accepts any `ReviewAnswer`
4. `i18n`: Add `SRS.easy` key (both en + zh-CN)
5. CSS: Add `.srs-card__rating-btn--easy` with appropriate color (suggest V6 green-teal)

**Button order** (V6): Again / Hard / Good / Easy (left to right, worst to best)

**Estimated LOC**: ~20 frontend + ~10 backend + ~4 i18n + ~10 tests = ~44 total

**Risk**: Low. The FSRS library already supports Rating.Easy. It's a straightforward addition.

---

## 6. Scaffolding State Display

### Current Backend

`lesson/scaffolding.py` computes scaffolding level:
- `stability < 3d` OR learning/relearning state → `"full"`
- `3d <= stability < 14d` → `"hint"`
- `stability >= 14d` AND `recent_successes >= 2` → `"compact"`

`DueReviewCard` already includes `scaffolding_level: str` field, exposed via `/api/review/queue`.

### Frontend Display

**Current**: `ReviewPage.tsx` and `SRSCard.tsx` do NOT display scaffolding level. The data is available in the card but unused.

**Proposed UI**:
1. **Badge on SRS card**: Show `full|hint|compact` badge with color coding:
   - `full` (green): "Full scaffolding" — new/unstable concept
   - `hint` (amber): "Hint mode" — intermediate retention
   - `compact` (blue): "Minimal" — strong retention
2. **Tooltip**: Show stability days + recent success count
3. **Review queue grouping**: Optionally group/sort cards by scaffolding level

**LOC**: ~30 TSX + ~20 CSS + ~6 i18n keys = ~56

**Backend dependency**: None — data already exposed. May want to add `stability` and `recent_successes` to `DueReviewCard` response for tooltip display (currently only `scaffolding_level` string is returned).

---

## 7. Misconception Cards UI

### Blueprint Definition

From Blueprint HTML: When a safety question is answered wrong, generate a "misconception card" that targets the specific misunderstanding.

### Current State

There is no `misconception` card type in the backend. `DueReviewCard` has a `scaffolding_level` but no `card_type` field. The quiz system generates questions but doesn't track specific misconceptions.

### Proposed UI Treatment

**Option A — Badge-based** (recommended for v1.0):
- Add optional `card_type: 'normal' | 'misconception'` field to `DueReviewCard`
- Misconception cards get a distinct visual treatment: red-tinted border, warning icon, "Misconception" badge
- The question text already conveys the misconception; no structural change to the quiz format

**Option B — Separate queue**:
- Show misconception cards in a separate section of the review page
- More complex, requires queue filtering

**LOC**: ~40 TSX + ~20 CSS + ~4 i18n keys = ~64 (Option A)

**Backend dependency**: Needs `card_type` field added to `DueReviewCard` response. Backend logic to classify cards as misconception-type when generated from wrong safety answers.

---

## 8. New i18n Keys Estimate

### Current State

- 189 keys in both `en.json` and `zh-CN.json` (100% parity)
- v0.2 added keys for 6 new pages (Review, Ratchet, Landing, Settings, Onboarding, Skills)

### New Keys Needed for v1.0

| Area | New Keys | Examples |
|------|----------|---------|
| Sidebar sections | 6 | `Nav.section_workspace`, `Nav.section_practice`, `Nav.section_system`, `Nav.status_serving`, `Nav.version` |
| Sidebar bilingual labels | 12 | `Nav.landing_en`, `Nav.dashboard_en`, `Nav.lesson_en`, etc. (English abbreviations) |
| Topbar | 4 | `Topbar.search_placeholder`, `Topbar.new_run`, `Topbar.docs`, `Breadcrumb.home` |
| Search overlay | 6 | `Search.title`, `Search.placeholder`, `Search.no_results`, `Search.type_claims`, `Search.type_concepts`, `Search.type_commits` |
| SRS Easy button | 1 | `SRS.easy` |
| Scaffolding display | 6 | `Scaffolding.full`, `Scaffolding.hint`, `Scaffolding.compact`, `Scaffolding.full_desc`, `Scaffolding.hint_desc`, `Scaffolding.compact_desc` |
| Misconception cards | 2 | `Review.misconception`, `Review.misconception_desc` |
| Settings tabs | 8 | `Settings.tab_account`, `Settings.tab_keys`, `Settings.tab_privacy`, etc. |
| Settings new sections | 10 | `Settings.provider_grid_title`, `Settings.audit_log_title`, `Settings.privacy_toggle`, etc. |
| Dashboard new sections | 8 | `Dashboard.spec_alignment`, `Dashboard.weak_concepts`, `Dashboard.audit_cost`, `Dashboard.verdict_all`, `Dashboard.verdict_pass`, `Dashboard.verdict_caution`, `Dashboard.verdict_fail` |
| Lesson TOC | 3 | `Lesson.toc_title`, `Lesson.mark_learned`, `Lesson.print` |
| Calendar heatmap | 3 | `Review.calendar_title`, `Review.calendar_30day`, `Review.reviews_count` |
| Accessibility | 4 | New ARIA labels for drawer, search, heatmap, tabs |

**Total**: ~73 new keys (both en + zh-CN)

**New parity target**: 189 + 73 = **~262 keys**

---

## 9. Playwright Test Strategy

### Current State

- 5 test files: smoke (17), i18n (8), media-features (4), cross-browser (18), walkthrough (5) = **52 test cases**
- Run across 5 viewports × 3 browsers = **495 total executions** (some tests × viewports)
- Viewports: 360, 375, 768, 1024, 1440
- Browsers: Chromium, Firefox, WebKit

### New Test Scenarios for v1.0

| Test File | New Scenarios | Est. Tests |
|-----------|--------------|------------|
| `smoke.spec.ts` | Sidebar 3-section rendering, breadcrumb presence, hamburger at mobile, search bar visibility, 4 SRS buttons, scaffolding badge, verdict filter tabs | +12 |
| `layout.spec.ts` (NEW) | Lesson 3-column at 1440px, lesson 1-col at 768px, diff split at 1024px, diff stacked at 768px, settings tab navigation, dashboard 4 KPIs + 5 sections | +10 |
| `search.spec.ts` (NEW) | Cmd+K opens modal, ESC closes, type shows results, click result navigates, empty state, loading state | +8 |
| `review-srs.spec.ts` (NEW) | 4 rating buttons render, "easy" submits correctly, scaffolding badge display, misconception card styling, calendar heatmap renders | +8 |
| `mobile.spec.ts` (NEW) | Hamburger click opens drawer, backdrop click closes, drawer links navigate + auto-close, swipe-to-close (optional), no horizontal overflow at all breakpoints | +8 |
| `walkthrough.spec.ts` | Extend with: settings tab switch, lesson TOC click, diff claim-inspector click | +6 |
| `i18n.spec.ts` | New keys coverage, sidebar bilingual labels in both locales | +4 |
| `media-features.spec.ts` | Drawer/hamburger in forced-colors, search overlay in dark mode | +3 |
| `manifest.test.ts` (LANDED) + future `pwa.spec.ts` | manifest shape + icon files are covered; service worker registration / offline shell still need browser E2E | +1 landed / +2 future |
| `a11y.spec.ts` (NEW) | axe-core audit on Dashboard, Lesson, Review, Settings (0 violations) | +4 |

**Total new tests**: ~66

**New total**: 52 + 66 = **~118 test cases**, projected **~800-900 total executions** across viewport/browser matrix

### Viewport additions

Current 5 viewports are sufficient. May add `1280px` to match V6's `min-width:1280px` breakpoint. Total: 6 viewports.

---

## 10. PWA Assessment

Current implementation note (2026-05-09): the app already uses `vite-plugin-pwa` in `viewer/vite.config.ts`, with `manifest: false` so the checked-in `viewer/public/manifest.json` is the manifest source. This follow-up added same-origin `id` / `scope`, 192/512 PNG icons, and `manifest.test.ts`. `pnpm build` currently generates `sw.js`; offline-shell behavior is still not covered by E2E, so only manifest/installability is counted as closed here.

### What's Needed

1. **`manifest.json`** (~30 lines, current manifest basics closed):
   - `name`, `short_name`, `start_url: "./"`, `display: "standalone"`, `theme_color`, `background_color`
   - Icons: 192x192 + 512x512 PNG
   - `scope: "./"` (HashRouter compatible)

2. **Service Worker** via `vite-plugin-pwa`:
   - New dev dependency: `vite-plugin-pwa` (~8KB)
   - Strategy: **NetworkFirst** for API calls, **CacheFirst** for static assets
   - Offline: serve cached app shell when network unavailable; show "offline" banner for API-dependent content
   - Precache: all JS/CSS chunks + index.html

3. **Vite Config Changes** (`vite.config.ts`):
   ```typescript
   import { VitePWA } from 'vite-plugin-pwa';
   plugins: [react(), VitePWA({
     registerType: 'autoUpdate',
     manifest: { /* ... */ },
     workbox: {
       globPatterns: ['**/*.{js,css,html,ico,png,svg}'],
       runtimeCaching: [{
         urlPattern: /^\/api\//,
         handler: 'NetworkFirst',
         options: { cacheName: 'api-cache', expiration: { maxEntries: 50 } }
       }]
     }
   })]
   ```

4. **Offline Support**:
   - App shell (sidebar, topbar, routing) works offline
   - Pages show "Offline — data from last visit" with cached data
   - API calls fail gracefully with cached responses or error states

### Impact

- **New dependency**: `vite-plugin-pwa` (devDependency)
- **Build size**: +~5KB for service worker registration
- **Vite config**: ~20 lines added
- **Testing**: manifest shape and icon files are covered by `viewer/tests/unit/manifest.test.ts`; SW registration/offline shell still needs E2E coverage
- **Risk**: Low. `vite-plugin-pwa` is mature (8M+ weekly downloads). Service worker only caches; doesn't modify app behavior. HashRouter is PWA-compatible.

**Estimated total LOC**: ~80 (config + manifest + offline UI indicators)

---

## Summary Table

| Stage | LOC | Days | Backend Deps | Risk |
|-------|-----|------|-------------|------|
| F1: Chrome + Layout Foundation | ~1,200 | 1-2 | 1 new endpoint (serve status) | **High** (mobile paradigm change) |
| F2: Page Layout Refactors | ~1,100 | 1-2 | 3-4 new API fields/endpoints | **High** (3-column + split layouts) |
| F3: New Components + Features | ~1,200 | 1-2 | 4-5 new endpoints | Medium |
| F4: Zod + PWA + Polish | ~430 | 1 | None | Low |
| F5: Graphify UI + full V6 parity polish | ~2,000 | 11-16 | Graphify status/search/concepts enrichment | Medium |
| **Total** | **~5,900** | **18-23 person-days** | **12+ backend items** | v1.0 Full Scope |

**Backend API additions needed** (for Codex/backend team, v1.0 Full Scope):
1. `ReviewAnswer` type: add `"easy"` (F3)
2. `DueReviewCard`: add `stability`, `recent_successes`, optional `card_type` fields (F3)
3. `GET /api/serve/status` — version + host:port for sidebar footer (F1)
4. `GET /api/review/activity` — 30-day review counts for heatmap (F3)
5. `GET /api/search` — unified search across claims/concepts/commits (F3)
6. `GET /api/audit/recent` — last N provider calls from audit.jsonl (F3)
7. Extended `/api/config` — provider matrix (generate/judge/embed models) (F2)
8. Extended `/api/run/:id` — spec alignment score (F2)
9. `POST /api/config/privacy` — toggle privacy mode (F2)
10. Claim-hunk mapping data in `/api/run/:id/claims` response (F2)
11. Concept type classification / Graphify origin fields in `/api/concepts` (F5)
12. `GET /api/graph/status` or equivalent extension for Graphify freshness and provenance (F5)

---

## 11. Graphify Frontend Integration

### 11.1 Current State of ConceptGraph Component

The current `ConceptGraph.tsx` is a **functional SVG + d3-force graph renderer** — NOT a placeholder. Key characteristics:

**What it does render**:
- **SVG graph with d3-force**: Uses `forceSimulation`, `forceLink`, `forceManyBody`, `forceCenter`, and `forceCollide`; reduced-motion falls back to a static radial layout.
- **Graph / List views**: The UI has only Graph and List. 201+ nodes default to List, but the Full graph button remains enabled.
- **Nodes and edges**: Nodes are circles colored by `kind`; edges are weighted straight SVG lines from sanitized `/api/graph/concepts` data.
- **Filtering and legend**: Kind chips filter the graph/list; the legend mirrors the visible kind palette.
- **Node detail panel**: Click or keyboard-activate a node to show kind, shortened file path, freshness, and connected nodes in the side panel.
- **Graphify source card**: The shared `GraphifySourceCard` shows status, freshness, counts, and provenance where available.
- **Pan/zoom and fit/export**: Wheel zoom and background drag update the graph `<g>` transform; drag pauses simulation and uses `requestAnimationFrame` to avoid React re-rendering every pointer move. Fit-to-view uses the graph layer bounding box. Export writes an SVG.

**What it does NOT have** (compared to V6):
- No typed node shapes (all nodes are identical circles)
- No edge curves or arrow markers
- No cluster/community grouping UI
- No confidence/community filter surface yet, although backend metadata is preserved
- No full V6 Graphify source/provenance card with CLI command polish
- No true Canvas/WebGL renderer or minimap; current implementation stays SVG

### 11.2 ConceptsPage Current State

`ConceptsPage.tsx`:
- Fetches from `GET /api/graph/concepts` through `fetchGraphConcepts()`.
- Passes `ConceptGraphResponse { status, nodes, edges, truncated }` directly to `<ConceptGraph />`.
- Uses an `AbortController` when refetching or unmounting.
- If the response is truncated, the page can request `limit=2000` through the "show all" path.

### 11.3 Backend API: What `/api/graph/concepts` Currently Returns

The serve route in `routes_graph.py` returns a typed graph payload:

```
GET /api/graph/concepts?limit=N
→ { status, nodes, edges, truncated }
```

Each node has `id`, `name`, `kind`, `file_path`, `freshness`, and `metadata`; each edge has `id`, `source`, `target`, `relation`, and `weight`. This endpoint is the current ConceptGraph data source. The older `/api/concepts` JSONL pagination path still exists for concept ledger browsing, but it is not what the current graph page renders.

### 11.4 Graphify Freshness: 4-Value Projection

**Backend** (`routes_runs.py`):
```python
_CANONICAL_GRAPHIFY_STATUSES = frozenset({"fresh", "stale", "unavailable", "disabled"})
```

**`GraphifyStatus` dataclass** (`git/capture.py`):
- `source_path`, `imported_path`: File paths to `graphify-out/graph.json` and `.ahadiff/graphify/graph.json`
- `enabled`, `source_exists`, `imported_exists`, `has_graph`: Boolean flags
- `freshness: str | None`: Capture-time canonical 4-value projection (`fresh` / `stale` / `unavailable` / `disabled`), or `None` when there is no source graph
- `provenance: dict[str, str]`: Metadata about the Graphify source

**Frontend types** (`api/types.ts`):
- `GraphifyMode = 'full' | 'learning_only' | 'empty'`
- `RunDetail.graphify_mode`, `RunDetail.graphify_status`, `RunDetail.graphify_notes`

**Frontend display gaps**:
- The canonical 4-value freshness projection (`fresh` / `stale` / `unavailable` / `disabled`) is now surfaced by the shared `GraphifyCard` where that card is mounted
- `RunDetail.graphify_status` is still a per-run detail field; the new shared card reads `/api/graph/status` through `graph-store` rather than duplicating self-fetching logic per page
- The remaining gap is the full V6 Graphify source/provenance card and large-repo signoff, not the basic freshness badge

### 11.5 Graph Rendering Library Recommendation

**Options analysis**:

| Library | Bundle Size | Force-directed | React Integration | Typed Nodes | Zoom/Pan | LOC to implement |
|---------|------------|----------------|-------------------|-------------|----------|-----------------|
| **Custom SVG** (current) | 0 KB | No (circular only) | Native | Manual | Manual | ~400 for V6 parity |
| **d3-force** (modular) | ~15 KB | Yes, excellent | Requires ref bridging | Manual SVG | Manual | ~300 for V6 parity |
| **@react-force-graph-2d** | ~180 KB | Yes (uses d3-force) | Native React | Built-in | Built-in | ~150 for V6 parity |
| **vis-network** | ~300 KB | Yes | Wrapper needed | Built-in | Built-in | ~120 for V6 parity |
| **reactflow** | ~90 KB | No (dagre layout) | Native React | Built-in | Built-in | Not suited for force-directed |

**Recommendation: `d3-force` (modular import)**

Rationale:
1. V6 reference uses hand-rolled SVG with force-directed positioning (the JS in V6 HTML doesn't use d3, but uses a custom force simulation). `d3-force` provides production-quality force simulation without the full d3 bundle
2. Bundle impact is minimal (~15KB vs current 0KB)
3. Keeps SVG rendering in React JSX — no canvas escape hatch needed
4. The current `ConceptGraph.tsx` already uses `d3-force`; remaining work is V6 visual parity, provenance polish, and real large-repo signoff rather than replacing a circular layout
5. Full control over node shapes (circles, rects, different fills/strokes per type) — matches V6's typed node design
6. `@react-force-graph-2d` is overkill (180KB) and abstracts away the SVG, making V6 visual fidelity harder

**Implementation status**:
```
d3-force is already in use. The current graph still renders manual SVG via React JSX; d3-selection, d3-scale, and d3-shape are still not needed.
```

### 11.6 Deep Integration: Current → V6 Target

**V6 ConceptGraph Page structure** (2-column, `grid 1fr 320px`):

```
Header: [Graph|List] chips + [Fit|Export JSON] buttons + "48 nodes · 71 edges" counter
├── Left column
│   ├── Graphify Source Card (.src-card)
│   │   └── border-left accent, file status rows, CLI commands
│   └── Graph Container (.graph-wrap)
│       ├── Filter Chips: All(on) | This Diff | From Graphify | Learning Memory | Weak Claims
│       ├── SVG Force-directed Graph (900×560 viewBox)
│       │   ├── Edges: curved paths with arrow markers
│       │   └── Nodes (5 types):
│       │       ├── Repo context: grey (#A8A39A) circles, stroke only
│       │       ├── Current diff: #F6E8DF rect with #D97757 stroke
│       │       ├── Symbol nodes: filled #D97757
│       │       ├── Verified concepts: #ECF4EE fill, #2F6F4F stroke
│       │       └── Weak concepts: #F7EED9 fill, #B4791F stroke
│       └── Legend Bar: absolute bottom, blur backdrop
└── Right column (320px)
    ├── Node Detail Card (on click)
    │   └── name (serif 22px) + metadata grid + description
    └── List Fallback Card
        └── .lnode items with name + metadata
```

**Refactoring plan** (from current → V6):

| Step | Current | Target | LOC | Priority |
|------|---------|--------|-----|----------|
| 1. 2-column layout | Single column | `grid-template-columns: 1fr 320px` | ~30 CSS | P0 |
| 2. Replace circular → force-directed | Landed for normal mode; reduced-motion keeps a static layout | Further tune d3-force for real large graphs | ~40 TSX | P1 |
| 3. Typed node shapes | All identical circles | 5 node types with different shapes/colors per V6 spec | ~80 TSX + ~40 CSS | P0 |
| 4. Edge curves + arrows | Straight `<line>` elements | `<path>` curves with `<marker>` arrowheads | ~40 TSX + ~10 CSS | P1 |
| 5. Filter chips | Kind filters landed | V6 semantic filters: All / This Diff / From Graphify / Learning Memory / Weak Claims | ~40 TSX + ~20 CSS | P1 |
| 6. Legend bar | Landed for kind palette | Align labels and placement with final V6 visual spec | ~20 CSS | P2 |
| 7. Node detail panel | Landed as side panel | Add richer descriptions / claim links when backend provides them | ~40 TSX + ~20 CSS | P1 |
| 8. Graphify source card | Shared card landed | Full `.src-card` with CLI commands and deeper provenance rows | ~40 TSX + ~20 CSS | P2 |
| 9. Header controls | Graph/List + Fit/Export landed | Add explicit "N nodes · M edges" header counter | ~15 TSX | P2 |
| 10. Zoom/Pan | Landed with unbounded transform pan/zoom | Add touch gesture polish / minimap only if still needed | ~40 TSX | P2 |
| 11. List fallback | Grid list landed and used by default for 201+ nodes | Add richer metadata/scaffolding badges | ~30 TSX + ~20 CSS | P2 |

**Total Graphify frontend LOC**: ~640 TSX + ~220 CSS = **~860 LOC**

### 11.7 Data Model Gap: Concept Types for Node Rendering

The current `Concept` interface lacks a **`concept_type`** field needed to determine node shape/color. V6 defines 5 visual types:

| V6 Node Type | Shape | Color | How to Determine |
|-------------|-------|-------|-----------------|
| Repo context | Circle (stroke only) | Grey `#A8A39A` | Concepts from Graphify graph (no `introduced_by_run`) |
| Current diff | Rect | `#F6E8DF` fill, `#D97757` stroke | Concepts with `introduced_by_run` matching current run |
| Symbol | Filled circle | `#D97757` | Concepts where `file_refs` exist (code symbols) |
| Verified | Circle | `#ECF4EE` fill, `#2F6F4F` stroke | Concepts with associated verified claims |
| Weak | Circle | `#F7EED9` fill, `#B4791F` stroke | Concepts with low SRS mastery or contradicted claims |

**Backend data available but unused by frontend**:
- `introduced_by_run` → can derive "current diff" vs "repo context"
- `source_refs` → can derive Graphify origin
- `related_claims` → need claim status to derive "verified" vs "weak"

**Backend additions needed**:
1. **Concept enrichment**: `/api/concepts` should include or derive a `concept_type` field, or expose enough metadata (claim verdicts, SRS mastery score) for frontend classification
2. **Run-scoped concepts**: `/api/run/:id/concepts` already exists — can be used to identify "current diff" concepts
3. **Graphify source info**: Need `introduced_by_graphify: boolean` or similar flag

### 11.8 Graphify Freshness Display Recommendations

**Dashboard**: Upgrade the existing shared `GraphifyCard` / `graph-store` status surface into the full V6 source/provenance card; do not treat the basic freshness badge as still missing.
- `fresh`: Green dot + "Graphify: up to date"
- `stale`: Amber dot + "Graphify: needs refresh" + link to `ahadiff graph refresh`
- `unavailable`: Grey dot + "Graphify: unavailable"
- `disabled`: Muted dot + "Graphify: disabled"

**Settings page** (under a "Graphify" tab or section):
- Show full Graphify status: enabled/disabled, source path, freshness, provenance
- CLI command hints: `ahadiff graph status` / `ahadiff graph refresh` / `ahadiff graph import`
- Toggle: `--use-graphify` / `--no-graphify` setting

**ConceptsPage**: Show Graphify source card (V6's `.src-card`) with file status and freshness badge

**LOC**: ~40 TSX + ~20 CSS + ~8 i18n keys = ~68 LOC for freshness display across Dashboard/Settings/Concepts

### 11.9 Impact on Staging Plan

The Graphify frontend integration (~860 LOC) is part of the same v1.0 milestone. It can be split across internal batches:

| Internal batch | Graphify Work | LOC |
|-------|-------------|-----|
| F2 | 2-column layout + node detail panel (structural) | ~150 |
| F3 | Force-directed simulation + typed nodes + filter chips + legend + freshness display | ~580 |
| F4 | Zoom/pan + Graphify source card + Export SVG + list fallback polish | Mostly landed; remaining work is provenance/CLI polish and large-repo signoff |

**Updated totals** (with Graphify):
| Stage | Original LOC | + Graphify | New Total |
|-------|-------------|-----------|-----------|
| F1 | ~1,200 | 0 | ~1,200 |
| F2 | ~1,100 | +150 | ~1,250 |
| F3 | ~1,200 | +580 | ~1,780 |
| F4 | ~430 | +130 | ~560 |
| **Total before full parity polish** | **~3,930** | **+860** | **~4,790** |

Full V6 parity adds additional page polish, mobile nav, tests, and i18n maintenance beyond the Graphify-only increment; use the top-level v1.0 planning estimate of **18-23 frontend person-days**.

**New backend API additions** (adding to the existing 10):
11. Concept type classification data in `/api/concepts` response (concept_type or enrichment fields)
12. Graphify freshness endpoint or extend `/api/config` with Graphify status details
