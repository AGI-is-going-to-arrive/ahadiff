# V6 Alignment Gap Analysis — Viewer vs V6 HTML Reference

> Generated 2026-04-27. Covers all 12 pages, 30 components, 5 CSS token files, state/API layer, i18n catalog.
> 2026-04-27 Codex update: this gap analysis is now v1.0 Full Scope input, not a v0.2/Core shortlist. Default serve port is `8765`; UI should read host:port from serve status/config. Diff, ConceptGraph, tokens, and Review scaffolding rows must be rechecked against current Viewer before implementation tasks are frozen.
> 2026-05-01 update: §8 Settings was rechecked against the current React viewer after Phase 4D. The old flat-layout findings are no longer current; remaining Settings gaps are called out row by row.
> 2026-05-07 update: Settings is now a 7-tab surface (`Account / Provider / Capture / Privacy / Audit / Preferences / Integrations`). Preferences owns language, appearance, `learnability_threshold`, and `desired_retention`. For the latest closed/open frontend gaps, use `doc/FRONTEND_GAP_REPORT.md`; older rows below remain historical V6 comparison notes unless explicitly updated.
> 2026-05-08 update: ConceptGraph was rechecked after the then-current viewer graph change. At that point it used SVG + d3-force, had Graph/List views, defaulted 201+ nodes to List while keeping Full graph available, included a side detail panel, and supported full-graph pan/zoom without hard viewport bounds. That note is now historical.
> 2026-05-09 update: Skills and Settings Integrations now use the protected install API. They preview the manifest, confirm the manifest hash on install/uninstall, show pending/success/error states, and re-detect after writes. Settings also consumes `?tab=provider` / `?tab=capture` / `?tab=integrations`; Concepts consumes `?focus=...`; Review consumes `?card=...`. Real-current-repo install/uninstall was not executed during validation; write tests used temp repos and browser mocks.
> 2026-05-11 update: Review was rechecked after the viewer review-fix. Review now has Again / Hard / Good / Easy buttons with `1`-`4` shortcuts, at-risk concept copy, and mastery tier bars. Quiz now has Prev / Mark wrong / Next, mode chips, and a progress table; it still does not have the V6 side evidence panel, and its SRSCard still renders Good / Hard / Wrong.
> 2026-05-11 ConceptGraph update: ConceptGraph now uses `react-force-graph-2d` Canvas, keeps Graph/List with large graphs defaulting to List, adds community fill, legend/filter UI, node details, cross-view search links, and a semantic list fallback for Canvas accessibility. It still does not have the exact V6 SVG markers/minimap or full source/provenance polish.
> 2026-05-11 AI Tool Guidance update: Settings still uses the internal `integrations` tab id and `?tab=integrations` deep link, but the visible UX is now “AI 工具指引 / AI Tool Guidance”. The page writes or removes repo-local agent guidance only; it does not install the AhaDiff CLI again and does not write global user directories. Target cards now include scope copy, write/remove commands, inline manifest preview, manifest hash, and action lists. Ratchet also has TSV + JSON export buttons, and Audit entries are displayed newest-first.
> 2026-05-13 V6 alignment review-fix update: AppShell / Sidebar / Topbar now import the shared `components.css` V6 compatibility layer, Landing and Lesson expose `data-page` for scoped V6 CSS, Dashboard empty/full states share the Learn dialog shortcut guard, and Lesson now has a real TOC / prose / rail reader with scroll-spy, `aria-current`, Scaffolding tabpanel wiring, and text wrapping. Settings, Dashboard, ProviderCard, and Landing also received forced-colors, reduced-motion, long-text, and responsive-grid fixes. The detailed closed/open status is tracked in `doc/FRONTEND_GAP_REPORT.md`; older rows below remain historical comparison notes unless explicitly updated.

---

## 1. Global Chrome (AppShell / Topbar / Sidebar)

### 1.1 Topbar

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Breadcrumb (`repo/page`) | `<div class="crumb">knowledge-return / Runs</div>` mono font, separator | Brand mark + brand name only (`Topbar.tsx`: `Δ知` + `Brand.name`) | **MISSING**: No breadcrumb, no dynamic page name |
| Search bar (Cmd+K) | `<div class="search" role="search">⌕ 搜索 claim/concept/commit… <kbd>⌘K</kbd></div>` min-width 280px, hover state | Not present | **MISSING**: Entire search UI absent |
| "Docs" button | `<button class="btn ghost">文档 Docs</button>` | Not present | **MISSING** |
| "New Learn Run" button | `<button class="btn primary">+ 新建 Learn Run</button>` | Not present | **MISSING** |
| Sticky blur backdrop | `background:rgba(250,248,242,.88); backdrop-filter:saturate(1.4) blur(8px)` | Has `backdrop-filter` in AppShell.css but simpler | **PARTIAL**: Needs blur+saturate tuning |
| Language switcher | Not in V6 topbar (V6 has it in sidebar footer) | In topbar (`LanguageSwitcher.tsx`) | **DIVERGENT**: Viewer placed it in topbar; V6 had none in topbar |

**Work estimate**:
- Breadcrumb component: ~40 LOC TSX + ~20 LOC CSS. Needs react-router location awareness. **P0**
- Search bar (visual shell only, no backend): ~60 LOC TSX + ~30 LOC CSS + ~5 i18n keys. **P1**
- Search bar (functional Cmd+K modal): ~200 LOC TSX + ~80 LOC CSS + new API endpoint. **P2**
- Docs button: ~5 LOC. **P2**
- New Learn Run button: ~10 LOC + link/action logic. **P1**
- Backdrop tuning: ~5 LOC CSS. **P3**

### 1.2 Sidebar

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| 3 sections (Workspace/Practice/System) | 3 `<nav class="nav-section">` with labels: `工作区·Workspace`, `学习·Practice`, `系统·System` | Single flat `<div class="sidebar__section">` with one label | **MISSING**: No section grouping |
| Section labels | `<div class="nav-label">工作区 · Workspace</div>` bilingual | Single `Shell.nav_label` = "Navigation" | **MISSING**: No bilingual section headers |
| Nav item format | `<span class="ic">◎</span><span>首页</span><span class="en">Landing</span>` — icon + Chinese + English abbreviation | `<span class="sidebar__icon">▤</span><span>{t(key)}</span>` — icon + single localized label | **MISSING**: No English abbreviation subtitle |
| Brand block | `brand-mark` (gradient square `Δ知`) + `brand-name` + `brand-en` tagline | In Topbar, not sidebar | **DIVERGENT**: V6 brand is in sidebar header; viewer put it in topbar |
| Status bar at bottom | `<div class="side-foot">` with green dot + host:port read from serve status/config, default `127.0.0.1:8765`, + version | Not present | **MISSING** |
| Active state | `border-left:2px solid var(--accent)` + accent color icon+en text | `sidebar__item--active` has left border + accent bg | **PARTIAL**: Close but missing `.en` color treatment |
| Landing page link | Separate nav item `data-goto="landing"` with `◎` icon | No dedicated landing nav; `/welcome` is separate | **PARTIAL**: Has welcome but not V6's Landing placement |
| Mobile drawer | `sidebar.open` + `sidebar-backdrop` + hamburger toggle | Not implemented | **MISSING**: No mobile responsive sidebar |

**Work estimate**:
- 3-section grouping + bilingual labels: ~60 LOC TSX refactor + ~6 i18n keys. **P0**
- English abbreviation per nav item: ~30 LOC TSX + ~12 i18n keys + ~15 LOC CSS. **P1**
- Brand block move to sidebar: ~30 LOC TSX + ~20 LOC CSS. **P0**
- Status bar footer: ~40 LOC TSX + ~20 LOC CSS + 1 API call (serve status). **P1**
- Mobile hamburger + drawer + backdrop: ~80 LOC TSX + ~60 LOC CSS. **P0**

### 1.3 Mobile Responsiveness

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Hamburger button | `<button class="mobile-nav-btn">☰</button>` shown at ≤1024px | Not present | **MISSING** |
| Sidebar drawer | Fixed position, `transform:translateX(-100%)` slide-in | Not present | **MISSING** |
| Backdrop overlay | `.sidebar-backdrop` with blur + opacity transition | Not present | **MISSING** |
| Escape key close | `document.addEventListener('keydown', ...)` | Not present | **MISSING** |
| Search hide at 768px | `.topbar .search{display:none}` | N/A (no search) | N/A |
| KPI grid collapse | `grid-template-columns:1fr` at 768px | Has `@media (max-width:767px)` in Dashboard.css | **OK** |

**Work estimate**:
- Full mobile nav system: ~120 LOC TSX + ~80 LOC CSS. **P0**

---

## 2. Dashboard Page

### 2.1 Page Header

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Eyebrow | `§ Runs Dashboard` mono uppercase | Not present | **MISSING** |
| Title + repo slug | `运行记录 · knowledge-return` serif + mono repo name | `Dashboard.title` serif, no repo name | **PARTIAL** |
| Subtitle | "过去30天共147次learn run。仓库main分支领先SPEC.md 6/8个需求。" | `Dashboard.subtitle` generic | **PARTIAL** |
| Right actions | chip "last 30 days" + "导出 CSV" button + "+ New Learn Run" button | Not present | **MISSING** |

### 2.2 KPI Cards

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Card count | 4 cards | 3 cards (total runs, pass rate, weakest dim) | **PARTIAL** |
| "Lesson score median" | `82.4` with `▲ 4.2 vs 上周 · PASS ratio 71%` delta | Not present | **MISSING**: No median score KPI |
| "Claims verified" | `2,418 / 2,704` with `89.4% · 186 weak · 100 not proven` | Not present | **MISSING**: No claims KPI (needs backend data) |
| "Reviews due today" | `27` with `4 overdue · 3 at-risk 概念` | Not present | **MISSING**: Needs review queue API |
| "Spec alignment" | `6/8` with CAUTION badge | Not present | **MISSING**: Needs spec data |
| Left accent bar | Tone-coded (success/warning/danger) | Implemented (`kpi-card--success` etc.) | **OK** |
| Hover lift + shadow | `translateY(-2px)` + `shadow-lg` | Implemented | **OK** |

### 2.3 Dashboard Sections

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Quality trajectory chart | SVG line chart in `.card` with gradient fill, labeled axes, PASS point highlight | `RatchetChart` SVG component | **PARTIAL**: Exists but simpler than V6 |
| Spec alignment card | Table with done/pending/missing badges | Not present | **MISSING** |
| Recent runs table | 8 columns (commit/lesson/score/verdict/claims/spec/cost/status) with filter tabs (All/PASS/CAUTION/FAIL) | 5 columns (ref/verdict/overall/weakest_dim/date), no filter | **PARTIAL**: Missing 3 columns + filter tabs |
| Weak concepts section | Chip cloud + "2 concept 已连续答错≥2次" hint | Not present | **MISSING** |
| Audit cost (24h) section | Provider call log table (provider/model/calls/cost) | Not present | **MISSING**: Needs usage.sqlite API |

**Work estimate (Dashboard total)**:
- Eyebrow + repo name + right actions: ~40 LOC TSX + ~20 LOC CSS + ~5 i18n keys. **P0**
- 4th KPI (claims or reviews): ~20 LOC TSX + new API. **P1** (backend dependency)
- Verdict filter tabs: ~50 LOC TSX + ~20 LOC CSS + ~4 i18n keys. **P0**
- Weak concepts section: ~60 LOC TSX + ~30 LOC CSS + new API. **P1** (backend dependency)
- Audit cost section: ~80 LOC TSX + ~30 LOC CSS + new API. **P2** (backend dependency)
- Spec alignment card: ~60 LOC TSX + ~30 LOC CSS. **P2** (backend dependency)
- Runs table extra columns: ~30 LOC TSX. **P1**

---

## 3. Lesson Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| 3-column reader layout | `grid-template-columns:220px 1fr 320px` (TOC / prose / rail) | Single column with EvidencePanel below | **MAJOR GAP**: No 3-column grid |
| TOC sidebar | Sticky, with active section highlighting, scroll spy | Not present | **MISSING** |
| Prose sections | TL;DR / What changed / Why it matters / Claims / Walkthrough / Quiz / Concepts / Misconceptions / Sources | Only claims list + lesson content | **PARTIAL**: Missing structured sections |
| Right rail | Claim Inspector panel (sticky), evidence source hunk, scaffolding tabs | EvidencePanel + ScaffoldingTabs exist but in single column | **PARTIAL**: Components exist, layout wrong |
| Print button | `🖶 Print` button in header right | Not present | **MISSING** |
| "Mark as learned" button | Primary button in header | Not present | **MISSING** |
| PASS badge in header | `<span class="badge pass">PASS · 88</span>` | Not present | **MISSING** |
| `.prose` typography | Serif font 17px, line-height 1.8, highlight spans with dashed underline | Basic pre-formatted text | **PARTIAL**: Needs prose typography |
| Claim highlight interaction | Click claim → highlight in prose + show in rail | ClaimBadge + EvidencePanel with selection | **PARTIAL**: Exists but no prose highlighting |

**Work estimate**:
- 3-column reader grid + responsive collapse: ~80 LOC CSS + ~40 LOC TSX refactor. **P0**
- TOC component with scroll spy: ~100 LOC TSX + ~40 LOC CSS. **P1**
- Right rail layout: ~30 LOC CSS. **P0**
- Prose typography (`.prose` class): ~40 LOC CSS. **P0**
- Header PASS badge + actions: ~30 LOC TSX + ~2 i18n keys. **P1**
- Structured sections: ~60 LOC TSX (dependent on lesson API format). **P1**

---

## 4. Diff Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Split layout | `grid-template-columns:1fr 380px` (diff + claim inspector) | Single column with DiffView + BottomMiniPanel | **MAJOR GAP**: No split layout |
| Claim Inspector panel | Sticky right panel with claim list, click to highlight hunk | BottomMiniPanel shows stats only | **MISSING** |
| File tree header | File path + stats in header | Has stats in BottomMiniPanel | **PARTIAL** |
| Hunk highlighting | Click claim → scroll to hunk + highlight | Not present | **MISSING** |
| Line numbers | Dual column (old/new) line numbers | DiffView has line numbers | **OK** |

**Work estimate**:
- Split layout grid: ~30 LOC CSS. **P0**
- Claim Inspector sidebar: ~120 LOC TSX + ~60 LOC CSS + API integration. **P1**
- Hunk-claim linking: ~80 LOC TSX. **P2**

---

## 5. Quiz Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Quiz card with question | Present in V6 | SRSCard component implemented | **OK** |
| Multiple choice | Present | Implemented | **OK** |
| Answer reveal | Color-coded | Implemented | **OK** |
| SRS rating | good/hard/wrong | Implemented with `rated` gate | **OK** |
| Progress counter | `Q x/y` | Implemented in header | **OK** |
| Evidence panel alongside | Side panel in V6 | Not present | **MISSING** |
| Visual progress bar | V6 had visual bar | Header counter + progress table | **PARTIAL** |
| Keyboard shortcuts | V6 had keyboard nav | A-D answer shortcuts and 1/2/3 SRS shortcuts; no Quiz Easy shortcut because SRSCard still hides Easy | **PARTIAL** |

**Work estimate**:
- Evidence side panel: ~60 LOC TSX + ~30 LOC CSS. **P1**
- V6-style visual bar: ~30 LOC TSX + ~20 LOC CSS. **P2** (current table already covers readable progress)
- Remaining keyboard polish: mostly V6 parity details. **P2**

---

## 6. Review Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Flashcard flip | Flip button + space key | Implemented | **OK** |
| SRS rating | Wrong/Hard/Good/Easy with intervals | Implemented with `1`-`4` shortcuts | **OK** |
| Progress + remaining count | Card x/y + remaining | Implemented | **OK** |
| Calendar heatmap | V6 had review calendar | Not present | **MISSING** |
| Concept mastery bars | V6 had mastery visualization | Implemented with warning/danger tiers | **OK** |
| Session summary | V6 had end-of-session stats | Basic "all done" message | **PARTIAL** |

**Work estimate**:
- Calendar heatmap: ~150 LOC TSX + ~60 LOC CSS + new API. **P2** (backend dependency)
- Session summary enhancement: ~40 LOC TSX + ~3 i18n keys. **P2**

---

## 7. Ratchet Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Trajectory chart | SVG chart present | RatchetChart implemented | **OK** |
| 8-dim radar | Rubric dimensions display | Shows all 8 dimensions | **OK** |
| History list | Paginated with verdict badges | Implemented with cursor pagination | **OK** |
| results.tsv / results.json raw export | V6 had downloadable raw data section | TSV and JSON download buttons are present on Ratchet; neither is a full inline raw table. | **PARTIAL** |
| Phase 2.5 section | Structural rewrite history | Not present | **MISSING** |
| Benchmark transparency | V6 had benchmark section | Not present | **MISSING** |
| Iteration timeline (kept/reverted) | Visual timeline | Simplified list only | **PARTIAL** |

**Work estimate**:
- results TSV/JSON inline preview: ~60 LOC TSX + ~30 LOC CSS + API if needed later. **P2**
- Phase 2.5 display: ~40 LOC TSX. **P3**
- Iteration timeline: ~100 LOC TSX + ~50 LOC CSS. **P2**

---

## 8. Settings Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Config display | Present | ConfigField component | **OK** |
| Doctor checks | Present | Implemented with icons | **OK** |
| API key status | Present | Configured/missing badges | **OK** |
| Tab sidebar | V6: Account / Keys / Models / Privacy / Audit / Language / Appearance / Integrations | Implemented as 7 tabs: Account / Provider / Capture / Privacy / Audit / Preferences / AI Tool Guidance. Language + Appearance are merged into Preferences; deep link remains `?tab=integrations`. | **OK, current shape differs from old V6 split** |
| Mode summary card | V6: 4-cell mode summary with accent left border and footer | No longer rendered in `SettingsPage.tsx`; privacy mode is edited directly in Privacy, while usage/provider summary lives in Provider/Audit surfaces. | **DIVERGENT, intentional current UI** |
| Privacy toggle | V6: switch UI with 38×22px knob | Privacy mode and serve port are writable; local-only/redaction/audit rows are status-style controls derived from current config. | **PARTIAL** |
| Provider grid | V6: 3-column Generate/Judge/Embed matrix | Implemented provider grid from `/api/providers`, with eyebrow/meta rows and accent highlight | **OK** |
| Audit log table | V6: Last 20 provider calls with time/model/tokens/cost | Implemented from `/api/audit?limit=20`, newest-first, with 8 visible columns and real audit field projection | **OK** |
| AI Tool Guidance target list | V6: AI tool integrations | Implemented from `/api/install/targets` plus protected preview/install/uninstall POST routes; supports `?tab=integrations`, write/remove command copy, inline manifest preview, manifest-hash confirmation, pending/success/error, and re-detect after writes. Copy now says project guidance, not CLI install. | **OK** |

**Work estimate**:
- Tab sidebar layout: landed; current implementation uses 7 tabs, not the older 8-tab split.
- Mode summary card: superseded by direct Privacy + Provider/Audit sections.
- Provider grid: landed in Phase 4D against existing `/api/providers`.
- Audit log table: landed in Phase 4D against `/api/audit?limit=20`; current ordering is newest-first.
- Privacy controls: privacy mode and serve port are writable; derived status rows remain read-only by design.

---

## 9. Onboarding Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| 4-step stepper | Horizontal steps with done/current/pending states | Implemented with stepper CSS | **OK** |
| Doctor check integration | Step completion based on doctor | Implemented | **OK** |
| CLI command display | Code blocks with install commands | Present | **OK** |
| Step detail content | Rich content per step | Basic title + description | **PARTIAL** |

**Work estimate**:
- Enhanced step content: ~40 LOC TSX + ~3 i18n keys. **P2**

---

## 10. Skills Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Agent card grid | 3-column grid with icons | Implemented with 13 agents | **OK** |
| Copy button with feedback | "copied ✓" animation | Implemented | **OK** |
| Install/detected status | Badge states | Implemented (installed/available/unsupported), with server-provided write/remove commands, manifest preview/hash, protected install/uninstall actions, pending/success/error, and re-detect after writes | **OK** |
| V6: Agent state machine diagram | States strip (idle/reading/diffing/...) | Not present | **MISSING** |

**Work estimate**:
- Agent state machine: ~80 LOC TSX + ~40 LOC CSS. **P3**

---

## 11. Concepts/Graph Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Force-directed graph | V6: SVG with nodes/edges, markers | Canvas ConceptGraph via `react-force-graph-2d` | **PARTIAL**: Works; V6 SVG markers/minimap still differ |
| Node count display | "48 nodes, 71 edges" | Showing-count text exists | **PARTIAL**: Header placement still differs |
| Node detail panel | Click node → definition | Side detail panel exists | **PARTIAL**: Rich descriptions depend on backend data |
| List fallback | Tabular concept list alternative | Graph/List toggle; large graphs default to List; Canvas nodes have semantic a11y list fallback | **OK** |

**Work estimate**:
- Node/edge count: ~10 LOC TSX. **P2**
- Node detail panel: ~80 LOC TSX + ~40 LOC CSS. **P1**
- List fallback: ~60 LOC TSX + ~30 LOC CSS. **P1**

---

## 12. Landing Page

| Element | V6 Reference | Viewer Current | Gap |
|---------|-------------|---------------|-----|
| Hero section | Title + lead + CTAs + demo tabs | Implemented | **OK** |
| Pipeline steps | 5-step grid | Implemented (5 steps) | **OK** |
| Before/After comparison | Raw diff vs lesson | Implemented | **OK** |
| FOLIO badge | `VERIFIED ★` rotated stamp with editorial feel | Not present | **MISSING** |
| Drop cap | `::first-letter` large decorative initial | Not present | **MISSING** |
| Feature cards | Additional feature cards in V6 | Not present | **PARTIAL** |

**Work estimate**:
- FOLIO badge: ~30 LOC CSS. **P3**
- Drop cap: ~10 LOC CSS. **P3**
- Feature cards: ~60 LOC TSX + ~30 LOC CSS + ~6 i18n keys. **P2**

---

## 13. CSS Token Alignment

### 13.1 V6 Root Tokens vs Viewer tokens.css

| Token Category | V6 Count | Viewer Count | Gap |
|---------------|----------|-------------|-----|
| Color base (paper/ink/subtle/elevated/muted/hair) | 10 | 10 | **OK** (66 v6 tokens confirmed) |
| Accent colors | 5 (accent/ink/soft/softer/softest) | 5 | **OK** |
| Diff colors (add/del bg+fg) | 4 | 4 | **OK** |
| Semantic (success/warning/danger/info) | 4 | 4 | **OK** |
| Font stacks (sans/serif/mono) | 3 | 3 | **OK** |
| Dark mode tokens | Full set | Full set with WCAG AAA ≥7.0:1 | **OK** |
| Spacing scale | Inline in V6 | `--sp-*` variables | **OK** |
| Radius scale | Inline in V6 | `--radius-*` / `--r-*` variables | **OK** |
| Duration/easing | Inline in V6 | `--duration-*` / `--ease-*` | **OK** |
| Shadow scale | 3 levels | 3 levels (sm/md/lg) | **OK** |
| V6 extended semantic tokens | `--brand-anthropic`, `--ink-deep`, etc. | Not present | **MISSING**: ~10 extended tokens |

### 13.2 V6 Typography Specifics

| V6 Pattern | Viewer Status | Gap |
|------------|--------------|-----|
| `.prose` class (serif 17px, 1.8 lh) | Not present | **MISSING** |
| `.eyebrow` (mono 11px, uppercase, 0.14em spacing) | Partial (some pages use `review__eyebrow`) | **PARTIAL**: Not global utility |
| `.mono` class | Some elements use `font-family: var(--font-mono)` inline | **PARTIAL** |
| Half-pixel → whole-px fixes (v6.2) | Not applied | **MISSING** |

---

## 14. i18n Gap

Current: 189 keys across 24 top-level groups (189/189 en/zh-CN parity).

Estimated new keys needed for full V6 alignment:

| Area | New Keys | Examples |
|------|---------|---------|
| Sidebar sections | ~6 | `Sidebar.workspace`, `Sidebar.practice`, `Sidebar.system` |
| Sidebar english abbreviations | ~12 | `Nav.en_runs`, `Nav.en_lesson`, `Nav.en_diff`, ... |
| Topbar elements | ~5 | `Topbar.search_placeholder`, `Topbar.docs`, `Topbar.new_run` |
| Dashboard enriched | ~10 | `Dashboard.claims_verified`, `Dashboard.reviews_due`, `Dashboard.spec_alignment`, filter labels |
| Settings tabs | ~8 | `Settings.tab_account`, `Settings.tab_keys`, `Settings.tab_privacy`, ... |
| Graph details | ~5 | `Graph.node_count`, `Graph.edge_count`, `Graph.detail_panel`, ... |
| Review calendar | ~3 | `Review.calendar_title`, `Review.mastery_title`, ... |
| Misc | ~5 | Various new section titles |
| **Total** | **~54** | |

---

## 15. Priority Summary & Work Estimation

### P0 — Core Visual Alignment (must-have for V6 parity)

| Item | Type | LOC Estimate | Backend Dep? |
|------|------|-------------|-------------|
| Sidebar 3-section grouping | TSX refactor + CSS | ~75 | No |
| Sidebar brand block (move from topbar) | TSX + CSS | ~50 | No |
| Mobile hamburger + drawer + backdrop | New TSX + CSS | ~200 | No |
| Topbar breadcrumb | New TSX + CSS | ~60 | No |
| Lesson 3-column reader layout | CSS + TSX refactor | ~120 | No |
| Lesson prose typography | CSS | ~40 | No |
| Diff split layout | CSS | ~30 | No |
| Dashboard eyebrow + right actions | TSX + CSS | ~60 | No |
| Dashboard verdict filter tabs | TSX + CSS | ~70 | No |
| **P0 Total** | | **~705** | |

### P1 — Interaction & Data Richness

| Item | Type | LOC Estimate | Backend Dep? |
|------|------|-------------|-------------|
| Topbar search bar (visual shell) | TSX + CSS | ~90 | No |
| Topbar "New Learn Run" button | TSX | ~10 | No |
| Sidebar English abbreviations | TSX + CSS + i18n | ~57 | No |
| Sidebar status footer | TSX + CSS + API | ~60 | Yes (serve status) |
| Dashboard extra columns | TSX | ~30 | No |
| Dashboard weak concepts | TSX + CSS + API | ~90 | Yes |
| Lesson TOC with scroll spy | TSX + CSS | ~140 | No |
| Lesson header badge + actions | TSX + i18n | ~32 | No |
| Diff claim inspector sidebar | TSX + CSS + API | ~180 | Partial |
| Settings tab sidebar | TSX + CSS + i18n | ~128 | No |
| Settings mode summary card | TSX + CSS | ~90 | No |
| Graph node detail panel | TSX + CSS | ~120 | Partial |
| Graph list fallback | TSX + CSS | ~90 | Yes |
| Quiz evidence side panel | TSX + CSS | ~90 | No |
| **P1 Total** | | **~1,207** | |

### P2 — Polish & Extended Features

| Item | Type | LOC Estimate | Backend Dep? |
|------|------|-------------|-------------|
| Search bar functional (Cmd+K modal) | TSX + CSS + API | ~280 | Yes |
| Dashboard audit cost section | TSX + CSS + API | ~110 | Yes |
| Dashboard spec alignment card | TSX + CSS | ~90 | Yes |
| Review calendar heatmap | TSX + CSS + API | ~210 | Yes |
| Review concept mastery bars | Implemented 2026-05-11 | 0 | No |
| Settings provider grid | TSX + CSS | ~120 | No |
| Settings audit log table | TSX + CSS + API | ~140 | Yes |
| Ratchet TSV/JSON export section | TSX + CSS + API | ~90 | Yes |
| Ratchet iteration timeline | TSX + CSS | ~150 | No |
| Quiz visual progress table | Implemented 2026-05-11 | 0 | No |
| Landing feature cards | TSX + CSS + i18n | ~96 | No |
| Graph node/edge count | TSX | ~10 | No |
| V6 extended CSS tokens | CSS | ~30 | No |
| `.prose` + `.eyebrow` utility classes | CSS | ~60 | No |
| Half-pixel → whole-px fixes | CSS | ~20 | No |
| Onboarding enhanced step content | TSX + i18n | ~43 | No |
| **P2 Total** | | **~1,619** | |

### P3 — Decorative & Nice-to-Have

| Item | Type | LOC Estimate | Backend Dep? |
|------|------|-------------|-------------|
| Topbar backdrop tuning | CSS | ~5 | No |
| Landing FOLIO badge | CSS | ~30 | No |
| Landing drop cap | CSS | ~10 | No |
| Skills agent state machine | TSX + CSS | ~120 | No |
| Ratchet Phase 2.5 display | TSX | ~40 | No |
| Settings privacy toggle | TSX + API | ~30 | Yes |
| Review session summary | TSX + i18n | ~43 | No |
| Quiz keyboard shortcuts | TSX | ~40 | No |
| Diff hunk-claim linking | TSX | ~80 | No |
| **P3 Total** | | **~398** | |

---

## 16. Grand Total

The original table below was the V6 visual/frontend-only estimate. For v1.0 planning, use it as one input only: Full Scope also includes Graphify UI, new serve APIs, Zod/runtime validation, i18n upkeep, tests, performance reproducibility, and security hardening.

| Priority | LOC Estimate | New i18n Keys | Backend APIs Needed |
|----------|-------------|--------------|-------------------|
| **P0** | ~705 | ~18 | 0 |
| **P1** | ~1,207 | ~20 | 2 (serve status, weak concepts) |
| **P2** | ~1,619 | ~10 | 5 (search, audit, spec, calendar, results.tsv/results.json) |
| **P3** | ~398 | ~6 | 1 (privacy toggle) |
| **Original visual-only total** | **~3,929** | **~54** | **8** |
| **v1.0 Full Scope planning total** | **~5,900 frontend LOC** | **TBD after i18n freeze** | **12+ backend items** |

### Effort Estimate

| Scope | Days | Notes |
|-------|------|-------|
| P0 only | 3-4 days | Pure frontend, no backend dependency |
| P0 + P1 | 7-9 days | 2 new backend APIs needed |
| P0 + P1 + P2 | 14-18 days | 7 new backend APIs, significant new features |
| Full V6 parity | 16-20 days | All priorities including decorative polish |
| v1.0 Full Scope incl. Graphify UI/tests/i18n | 18-23 person-days | Use this for current v1.0 planning; calendar elapsed depends on parallel frontend agents |

---

## 17. Key Architectural Decisions Needed

1. **Brand placement**: V6 has brand in sidebar; viewer has it in topbar. Which to follow?
2. **Language switcher placement**: V6 has no topbar language switcher. Keep viewer's topbar placement or move to sidebar footer?
3. **Lesson layout**: V6's 3-column reader is the largest structural change. May require responsive breakpoints for tablet/mobile collapse.
4. **Search functionality**: Functional Cmd+K search is in v1.0 Full Scope and depends on backend FTS/Search API.
5. **Backend API gaps**: 12+ backend items are in v1.0 scope after Graphify, usage, search, audit, review, and config additions. Final count should be frozen in the implementation plan after DTO/schema review.
