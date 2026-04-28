# V6 HTML Deep Analysis Report

> Source: `AhaDiff Warm v6.html` (3009 lines) — analyzed 2026-04-27
> Cross-checked against: `viewer/AUDIT_V6_FIDELITY.md`

---

## 1. Global CSS Variables (`:root`)

### 1.1 Light Mode (V6 Exact Values)

```css
:root {
  --paper:       #FAF8F2;
  --subtle:      #F2EFE7;   /* Viewer uses #F4F1E8 — MISMATCH */
  --elevated:    #FFFFFF;
  --ink:         #1C1B18;   /* Viewer uses #2E2A24 — MISMATCH */
  --ink-2:       #38362F;   /* Viewer has no --ink-2, uses --ink for everything */
  --muted:       #6A6456;   /* Viewer uses #5A5447 (WCAG darkened) */
  --muted-2:     #8F8878;   /* Viewer has no --muted-2 */
  --hair:        #E6E3D8;   /* Viewer uses #E6E1D4 — close but not exact */
  --hair-strong: #D5D0BF;   /* Viewer has this token */
  --accent:      #D27050;   /* Viewer uses #B05436 (WCAG darkened) */
  --accent-ink:  #B04E28;   /* Viewer maps to --accent in light mode */
  --accent-soft: #F4E4D9;   /* Viewer has this */
  --accent-softer: #FAF0E8; /* Viewer has no --accent-softer */
  --add-bg:      #E4EFE0;   /* Viewer has this */
  --add-fg:      #2F6F4F;
  --del-bg:      #F6DCD5;
  --del-fg:      #A33D2B;
  --success:     #2F6F4F;
  --warning:     #B4791F;   /* Viewer uses #946216 (WCAG darkened) */
  --danger:      #A33D2B;
  --info:        #2E4A6B;
}
```

**V6-only tokens not in viewer**: `--ink-2`, `--muted-2`, `--accent-softer`, `--accent-ink` (as separate token).

**Viewer-only tokens not in V6**: 66 additional tokens for dark mode, WCAG AAA, and component patterns (see CLAUDE.md changelog).

### 1.2 V6 Extended Tokens (v6 Polish Layer, line 558+)

```css
:root {
  --sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:16px; --sp-5:20px;
  --sp-6:24px; --sp-7:28px; --sp-8:32px; --sp-10:40px; --sp-12:48px;
  --sp-16:64px; --sp-20:80px;
  --dur-fast:.12s; --dur-normal:.2s; --dur-slow:.35s;
  --ease-out:cubic-bezier(.25,.46,.45,.94);
  --ease-out-expo:cubic-bezier(.19,1,.22,1);
}
```

### 1.3 Font Stacks (V6 Exact)

```css
--font-sans:  "Inter","PingFang SC","Noto Sans SC",ui-sans-serif,system-ui,sans-serif;
--font-serif: "Newsreader","Noto Serif SC","Source Serif 4",ui-serif,Georgia,serif;
--font-mono:  "JetBrains Mono",ui-monospace,SFMono-Regular,"Sarasa Mono SC",monospace;
```

### 1.4 V6 Has NO Dark Mode

V6 HTML is **light-only**. No `@media (prefers-color-scheme: dark)` block exists. The viewer's dark mode is entirely new.

---

## 2. Responsive Breakpoints (V6)

| Breakpoint | What changes |
|------------|-------------|
| `max-width: 1024px` | Sidebar becomes fixed drawer (translateX), `.mobile-nav-btn` shows, reader goes single-column, hero grid stacks, search bar shrinks to 160px |
| `max-width: 900px` | Settings layout stacks, provider grid goes 1-col, `.ba` grid stacks |
| `max-width: 780px` | Mode summary grid goes 2-col |
| `max-width: 768px` | KPI grid/agent grid/states strip go 1-col, page-head stacks vertically, ALL page two-column layouts collapse to 1fr, topbar search hidden, hero padding reduced |
| `max-width: 720px` | Mode summary grid goes 1-col |
| `max-width: 540px` | (in bolder overlay: specific hero adjustments) |
| `min-width: 1025px` | Drawer backdrop forced hidden |
| `min-width: 1280px` | (bolder overlay: wider adjustments) |

---

## 3. Page-by-Page Structure

### 3.1 Global Chrome

#### Sidebar (`.sidebar`, line 54, width from grid: 248px)
- **Background**: `linear-gradient(180deg, var(--subtle) 0%, #EEEADF 100%)`
- **Brand block** (`.brand`): padding 22px 22px 18px, flex row, gap 12px
  - **Brand mark** (`.brand-mark`): 38x38px, border-radius 10px, gradient `accent → accent-ink`, white text, serif font 18px, text "Δ知"
  - **Brand name** (`.brand-name`): serif font 17px weight 600
  - **Brand tagline** (`.brand-en`): mono 10px, letter-spacing .14em, uppercase, "Ship · Learn · Ratchet"
- **3 Nav sections** (`nav.nav-section`): padding 14px 12px 4px
  - **Section labels** (`.nav-label`): mono 10px, letter-spacing .14em, uppercase, color `--muted-2`
  - Workspace: Landing(◎), Runs(▤), Lessons(❦), Diff(⇌), Ratchet(▲)
  - Practice: Quiz(?), Review(⟲), Graph(◈)
  - System: Onboard(➊), Skills(✦), Settings(⚙)
- **Nav items** (`.nav-item`): flex, gap 10px, padding 8px 10px, border-radius 8px, font-size 14px
  - `.ic` span: 16x16px, opacity .75
  - `.en` label: mono 10px, auto margin-left, letter-spacing .08em, uppercase, color `--muted-2`
  - Hover: background `--accent-softer`, translate X(1px) (bolder layer)
  - Active: background #fff, box-shadow `0 1px 0 var(--hair), 0 4px 12px -8px rgba(120,80,50,.22)`, .ic color `--accent`
- **Status bar** (`.side-foot`): margin-top auto, padding 14px 16px, flex row, gap 10px
  - Green dot (`.dot`): 8x8px, border-radius 50%, background `--success`, glow ring
  - Mode text: "Hybrid · Local embed + BYOK"
  - Version: mono, "v1.1.0"

#### Topbar (`.topbar`, line 76)
- **Layout**: flex, gap 16px, padding 14px 32px, sticky top:0, z-index 5
- **Background**: `rgba(250,248,242,.88)` + `backdrop-filter: saturate(1.4) blur(8px)`
- **Breadcrumb** (`.crumb`): mono 12px, color `--muted`, items: "knowledge-return / Runs"
- **Mobile hamburger** (`.mobile-nav-btn`): hidden by default, 36x36px, shown at <=1024px
- **Search bar** (`.topbar .search`): margin-left auto, min-width 280px, flex, gap 8px, background `--subtle`, border `--hair`, border-radius 8px, padding 7px 12px, font-size 13px
  - Contains: search icon "⌕", placeholder text, `<kbd>⌘K</kbd>`
  - Hidden at <=768px
- **Buttons**:
  - "文档 Docs" (`.btn.ghost`): transparent bg, `--muted` color
  - "+ 新建 Learn Run" (`.btn.primary`): `--accent` bg, white text, box-shadow

#### Button System (`.btn`)
- Base: height 34px, padding 0 14px, border-radius 8px, font-size 13px, weight 500, border `--hair-strong`, bg #fff
- Hover: bg `--accent-softer`, border `#E0B89E`, translateY(-1px), shadow
- Active: translateY(0), no shadow
- `.btn.primary`: bg `--accent`, color #fff, border `--accent`
- `.btn.ghost`: transparent bg/border, color `--muted`

### 3.2 Dashboard Page (`data-page="dashboard"`)

**Page head**: eyebrow "§ Runs Dashboard", serif h1 "运行记录" + mono repo name, sub with run count

**Right actions**: chip "last 30 days", btn "导出 CSV", btn.primary "+ New Learn Run"

**DEMO DATA banner** (`.demo-banner.dashboard-note`): dashed border `#E3CDA1`, bg `#FBF5E6`

**4 KPI cards** (`.kpi-grid`, 4 columns):
1. "Lesson score · median" → 82.4, delta "▲ 4.2 vs 上周 · PASS ratio 71%"
2. "Claims verified" → 2,418/2,704, delta "89.4% · 186 weak · 100 not proven"
3. "Reviews due today" → 27, delta "4 overdue · 3 at-risk 概念"
4. "Spec alignment" → 6/8, delta with CAUTION badge

**KPI card CSS** (`.kpi`, line 139):
- bg `--elevated`, border `--hair`, border-radius 12px, padding 18px 20px
- Left accent bar: 3px, `--accent`, opacity 0 → 0.7 on hover
- Hover: translateY(-2px), shadow `0 10px 28px -18px rgba(120,80,40,.3)`
- `.lb`: mono 10px, letter-spacing .14em, uppercase
- `.vl`: serif 34px, weight 500, letter-spacing -.024em, tabular-nums
- `.delta`: font-size 12px, color `--muted`

**2-column grid** (2fr 1fr, gap 18px):
- Left: **Quality trajectory** card with SVG line chart (800x240 viewBox, gradient fill, data points with circles, axis labels in mono)
- Right: **Spec alignment** card with table (done/missing badges)

**Recent runs table** (`.card` with `.t` table):
- Header chips: All(on) / PASS / CAUTION / FAIL
- Columns: commit, lesson, score, verdict, claims, spec, cost, status
- 6 rows of demo data

**2-column grid** (1fr 1fr, gap 18px):
- Left: **Weak concepts** card with chip tags (on = at-risk)
- Right: **Audit cost (24h)** card with provider call log table

### 3.3 Lesson Page (`data-page="lesson"`)

**3-column reader layout** (`.reader`: `grid 220px 1fr 320px`, gap 28px):

**Left column — TOC** (`.reader .toc`, sticky top 72px):
- Sections: TL;DR, What changed, Why it matters, Claims verified, Walkthrough by hunk, Concepts you just used, Misconceptions, Not proven by this diff, Quiz, Sources
- Backlinks section below

**Center — Prose** (`.prose`):
- Font: serif 17px, line-height 1.8
- H2: serif 28px, weight 500, border-bottom
- Inline highlights: `.highlight` with `--accent-soft` bg, dashed bottom border
- Inline code: mono 14px, `--subtle` bg
- Claims list with inline badges (verified/weak/notproven/contradicted)
- Rejected misconception section with danger styling

**Right column — Rail** (`.reader .rail`, sticky top 72px):
- **Claims block**: badge summary (17 verified, 1 weak, 1 not proven, 1 rejected)
- **Wiki Memory block**: file tree of `.ahadiff/` structure
- **Evidence block**: file paths with line ranges
- **Learning block**: Quiz progress bar (4/5), Review due date
- **Scaffolding block**: Full/Hint/Compact toggle (`.scaffold` segmented control)
  - Gain card with with/without lesson comparison
  - Section helpfulness scores (TL;DR +0.06, Walkthrough +0.19, Background +0.02)
- **Not proven block**: bulleted list

### 3.4 Diff Page (`data-page="diff"`)

**2-column layout** (`grid 1fr 360px`, gap 18px):

**Left — Unified diff** (`.diff`):
- Header (`.hd`): flex, bg `--subtle`, mono 11px uppercase
- Rows (`.diff .row`): `grid 44px 44px 1fr` (old line num, new line num, code)
- Line numbers (`.ln`): color `--muted-2`, right-aligned, border-right dashed
- Code (`.code`): padding 2px 12px, white-space pre
- `.row.add`: bg `--add-bg`, code color `--add-fg`
- `.row.del`: bg `--del-bg`, code color `--del-fg`
- `.row.hunk`: bg `--subtle`, color `--muted`, italic
- `.row.clickable`: cursor pointer, hover: brightness(.97), outline `--accent`
- `.row.selected`: inset left 3px `--accent` shadow, brightness(.98)
- Chips in header: Unified(on) / Split, Prev file, Next file buttons

**Below diff — Selected source hunk card**: prose explanation of clicked line + claim binding

**Right — Claim Inspector** (`.card`):
- Filter chips: Shipped 19(on), Verified 17, Weak 1, Not proven 1, Rejected 1
- Claim cards (`.claim-card`): border `--hair`, border-radius 10px, padding 13px 15px
  - `.id`: mono 10.5px, letter-spacing .1em
  - `.txt`: serif 13.5px, line-height 1.55
  - `.ev`: mono 11px, color `--muted`
  - `.actions`: flex, border-top dashed, buttons (Accept/Mark wrong/Add to quiz)
  - Selected: border `--accent`, box-shadow `0 0 0 3px var(--accent-soft)`
  - Rejected card: border `#E4B8AE`, bg `#FDF1EC`, danger styling

### 3.5 Ratchet Page (`data-page="ratchet"`)

**Header chips**: Results(on) / Rubric / Benchmark / Judge notes

**2-column grid** (1.3fr 1fr, gap 18px):
- Left: **Quality trajectory** SVG chart (700x240), shows kept/discarded data points
- Right: **Rubric 8-dim** card:
  - Grid layout: label 160px, bar 1fr, score 36px
  - 8 dimensions: Accuracy(18/20), Evidence(13/15), Diff Coverage(12/15), Learnability(13/15), Quiz Transfer(7/10 warning), Spec Alignment(8/10), Conciseness(7/8), Safety & Privacy(7/7)
  - Hard gates status + Weakest dimension

**results.tsv table** (`.t`): columns time/commit/version/score/verdict/status/weakest/note, 11 rows

**2-column grid** (1fr 1fr):
- Left: **Phase 2.5** card with code diff, human checkpoint buttons (Accept/Restore/Open diff/Run one more eval), radio options (clean reset/audit revert)
- Right: **Benchmark transparency** card with suite stats, pinned benchmark scores

### 3.6 Quiz Page (`data-page="quiz"`)

**Header**: chips Guided/Recall(on)/Transfer, Skip button

**2-column layout** (`grid 1fr 320px`, gap 24px):

**Left — Quiz card**:
- Progress bar (`.bar`): 6px height, `--subtle` bg, `--accent` fill, border-radius 99px
- Question card with eyebrow "QUESTION · III of V"
- Question text: serif 22px
- **Options** (`.option`): flex, gap 12px, padding 14px 16px, border-radius 10px
  - `.letter`: mono 12px, 18px wide
  - Hover: border `--accent`, translateX(2px), shadow
  - `.correct`: border `#B9D7C1`, bg `#ECF4EE`
  - `.wrong`: border `#E4B8AE`, bg `#F7E2DC`
- Explanation panel: bg `--accent-softer`, border `#EBC3AE`, border-radius 10px
- Nav buttons: Prev, Mark wrong (ghost), Next (primary)

**Right sidebar**:
- **Evidence card**: source file + line range, code preview in mono
- **Progress card**: table with Q1-Q5 status (✓/now/pending/transfer)

### 3.7 Review Page (`data-page="review"`)

**Header chips**: Cards 27, At-risk 3, FSRS v4(on), 暂停 button

**2-column layout** (`grid 1fr 340px`, gap 24px):

**Left — Flashcard** (`.flashcard`):
- Background #fff, border `--hair`, border-radius 14px, padding 36px, min-height 300px
- Tag badge (absolute top-right): "forgetting risk high" weak badge
- Concept label: mono 10.5px uppercase
- **Front** (`.front`): serif 26px, line-height 1.4
- **Back** (`.back`): border-top dashed, padding-top 20px, font-size 15px
  - Includes evidence references and negative evidence panel (danger bg)

**SRS Buttons** (`.srs-buttons`): grid 4-col, gap 10px
- Each button (`.sb`): padding 14px, border `--hair`, border-radius 10px
  - `.t`: serif 18px weight 500 (Again/Hard/Good/Easy)
  - `.d`: mono 10.5px (< 10min / 1 day / 4 days / 9 days)
  - `.kbd` for keyboard shortcut (1/2/3/4)
  - Good button: bg `--accent-soft`, border `#EBC3AE`
  - Hover: translateY(-2px), shadow

**Right sidebar**:
- **Calendar heatmap card**: 30 cells in 10-col grid, gap 3px, with less/more legend
- **Concept mastery card**: 6 bars (grid `1fr 80px`), color-coded by mastery level

### 3.8 Settings Page (`data-page="settings"`)

**2-column layout** (`.settings-layout`: `grid 184px minmax(0,960px)`, gap 24px):

**Left — Tab sidebar** (`.stabs`, sticky top 72px):
- 8 tabs: 账户/Account, 密钥/Keys, 模型/Models, 隐私/Privacy(active), 审计/Audit, 语言/Language, 外观/Appearance, 集成/Integrations
- Tab CSS (`.st`): padding 8px 12px, border-radius 8px, font-size 13px, bi-lingual labels

**Right — Settings main** (`.settings-main`, max-width 960px):

1. **Mode Summary card** (`.mode-summary`):
   - Left accent bar 3px `--accent`
   - 4-column mode grid: Generate(cloud BYOK), Judge(cloud BYOK), Embed(local Ollama), 代码(never sent)
   - Footer note about Offline mode fallback

2. **Privacy card**: 6 toggle fields
   - Offline mode, Redact secrets, Explicit upload, Show every LLM call, External assets, Delete local cache
   - Each field: grid `1fr auto`, padding 20px 0, border-bottom `--hair`
   - Toggle: 38x22px, `--hair-strong` bg → `--accent` when on, white knob 18px

3. **Provider card**: 3-column grid
   - Generate (Claude Sonnet 4.5), Judge (GPT-5.4-mini), Embed (nomic-embed Ollama)
   - Each cell: border `--hair`, border-radius 8px, dl metadata grid

4. **Audit log card**: table with columns time/provider/model/files sent/tokens/cost/purpose/status

### 3.9 Graph/Concepts Page (`data-page="graph"`)

**Header**: chips Graph(on)/List, buttons Fit/Export JSON, "48 nodes · 71 edges" counter

**2-column layout** (`grid 1fr 320px`, gap 18px):

**Left**:
- **Graphify source card** (`.src-card`): border-left 3px `--accent`, file status rows, CLI commands
- **Graph container** (`.graph-wrap`): bg `--subtle`, border `--hair`, border-radius 12px, min-height 560px
  - Filter chips: All(on)/This Diff/From Graphify/Learning Memory/Weak Claims
  - **SVG graph** (900x560 viewBox): force-directed with edge curves, node types:
    - Repo context: grey (#A8A39A) circles, stroke only
    - Current diff: `#F6E8DF` rect with `#D97757` stroke
    - Symbol nodes: filled `#D97757` or stroked
    - Verified concepts: `#ECF4EE` fill, `#2F6F4F` stroke
    - Weak concepts: `#F7EED9` fill, `#B4791F` stroke
  - **Legend bar**: absolute bottom, bg `rgba(255,255,255,.94)`, backdrop-filter blur(4px)

**Right sidebar**:
- **Node detail card**: concept name (serif 22px), metadata grid (first introduced, updated by, evidence, related claims, quiz performance, SRS mastery), one-liner description
- **List fallback card**: grid of `.lnode` items with name + metadata

### 3.10 Skills Page (`data-page="skills"`)

**Header**: chips All(on)/Installed 2/Available 6

**Agent grid** (`.agent-grid`: `grid repeat(3,1fr)`, gap 16px): 6 agent cards
- Each `.agent-card`: border `--hair`, border-radius 12px, bg #fff, padding 18px
  - `.a-mark`: 36x36px, border-radius 8px, mono 11px (CC/CX/CD/GM/OC/CP)
  - `.a-name`: serif 18px weight 500
  - `.a-cmd`: mono 11.5px, bg `--subtle`, with copy button
  - Status: badge "installed" (verified) or chip "available"
  - Expanded cards: manual install steps, marketplace commands

**Below**: 2-column grid (1.1fr 1fr) with SKILL.md preview and AGENTS.md preview

### 3.11 Onboarding Page (`data-page="onboarding"`)

**Header**: h1 "Plan → Implement → Learn" with accent italic

**Stepper** (`.stepper`): flex row, gap 18px
- 4 steps: Pick a repo(done ✓), Add provider key(done ✓), Install agent(current 3), First plan + learn(4)
- `.sp.done`: border `#B9D7C1`, bg `#ECF4EE`, number bg `--success`
- `.sp.current`: border `--accent`, bg `--accent-soft`, number bg `--accent`

**2-column cards**: Spec-before-code (CLI commands) + Install agent integration (4 agent cards in 2x2 grid)

**Step 4 preview card**: 3-column grid (SPEC / Diff / Verdict)

### 3.12 Landing Page (`data-page="landing"`)

**Hero section** (`.hero`): padding 72px 40px 56px, border-bottom, relative overflow hidden
- Decorative radial gradient (`.hero::after`): 420x420px, `--accent-soft`, top-right
- 2-column hero grid: 1.05fr 1fr, gap 64px
- **Left**: eyebrow, h1 serif 68px "让每个 AI Diff，讲到你 真的懂。", English subtitle serif italic 18px, lead paragraph 16.5px, CTA buttons
- **Right**: Hero demo card (`.hero-demo`) with Raw Diff / Aha Lesson tabs, claim cards preview

**Steps pipeline** (`.steps`): grid 5-col, border `--hair`, border-radius 12px
- Each step (`.st`): padding 18px 20px, border-right
  - Number: mono 10.5px, letter-spacing .14em
  - Title: serif 17px
  - Description: 12.5px, color `--muted`

**Sections**: Evidence Demo (before/after), Benchmark & Trust (4 KPIs with DEMO tags)

---

## 4. Key Component Patterns

### 4.1 Card Pattern (`.card`, line 102)
```css
background: var(--elevated);
border: 1px solid var(--hair);
border-radius: 12px;
box-shadow: 0 1px 0 rgba(180,160,130,.06), 0 4px 20px -16px rgba(120,80,40,.18);
```
- Hover: shadow `0 8px 28px -18px rgba(120,80,40,.28)`
- Header (`.ch`): padding 15px 20px, border-bottom, flex between
  - H3: serif 18px weight 500
  - Meta: mono 11px uppercase
- Body (`.cb`): padding 20px

### 4.2 Badge Pattern (`.badge`, line 110)
```css
padding: 2px 8px; height: 22px; font-size: 11px;
font-family: var(--font-mono); letter-spacing: .08em;
text-transform: uppercase; border-radius: 99px;
border: 1px solid var(--hair-strong); background: #fff;
```
- `.badge.verified`: color `--success`, border `#B9D7C1`, bg `#ECF4EE`
- `.badge.weak`: color `--warning`, border `#E3CDA1`, bg `#F7EED9`
- `.badge.notproven`: color `--muted`, border `--hair-strong`, bg `--subtle`
- `.badge.contradicted`: color `--danger`, border `#E4B8AE`, bg `#F7E2DC`
- `.badge.pass`: same as verified
- `.badge.caution`: same as weak
- `.badge.fail`: same as contradicted
- `.badge.accent`: color `--accent-ink`, bg `--accent-soft`, border `#EBC3AE`

### 4.3 Chip Pattern (`.chip`, line 160)
```css
padding: 3px 11px; border-radius: 99px; background: var(--subtle);
font-size: 12px; border: 1px solid var(--hair);
```
- `.chip.on`: bg `--accent-soft`, color `--accent-ink`, border `#E6BFA6`

### 4.4 Eyebrow Pattern (`.eyebrow`, line 49)
```css
font-family: var(--font-mono); font-size: 11px;
letter-spacing: .14em; text-transform: uppercase; color: var(--muted);
```

### 4.5 DEMO Data Tag (`.demo-tag`, line 247)
```css
font-family: var(--font-mono); font-size: 10px;
letter-spacing: .14em; text-transform: uppercase;
color: var(--warning); background: #F7EED9;
border: 1px dashed #E3CDA1; padding: 2px 8px; border-radius: 4px;
```

### 4.6 FOLIO / Verified Stamp (bolder overlay, line 1059+)
- Rotated -3deg (reduced-motion: -2deg)
- Box-shadow with `--success` tones
- `::after` pseudo-element with "FOLIO · 合格" text stamp
- Elaborate letterpress effect with shadows

---

## 5. Cross-Check with AUDIT_V6_FIDELITY.md

### 5.1 Accurately Identified Gaps (CONFIRMED)

All 7 Critical gaps are correct:
1. Search bar (Cmd+K) -- CONFIRMED missing
2. Dashboard KPI richness -- CONFIRMED (4 vs 3, different data)
3. Dashboard sections -- CONFIRMED (5 vs 2)
4. Verdict filter tabs -- CONFIRMED missing
5. Settings page depth -- CONFIRMED (8 tabs + mode summary + provider grid + audit log vs flat)
6. Calendar heatmap -- CONFIRMED missing
7. Mobile responsiveness -- CONFIRMED missing

All 9 Moderate gaps (8-16) are correct.
All 5 Minor gaps (17-21) are correct.

### 5.2 NEW Gaps the Audit MISSED

| # | Gap | V6 Feature | Severity |
|---|-----|-----------|----------|
| N1 | **Lesson TOC sidebar** | V6 has 220px sticky TOC with section links + backlinks | P1-High |
| N2 | **Lesson Rail sidebar** | V6 has 320px sticky rail with Claims/Wiki Memory/Evidence/Learning/Scaffolding/Not proven blocks | P1-High |
| N3 | **Diff dual line numbers** | V6 diff has 2 line number columns (old + new) in 44px 44px 1fr grid | P1-Medium |
| N4 | **Diff clickable rows** | V6 rows have `data-claim` attributes, click selects claim, `.selected` style | P1-Medium |
| N5 | **Diff "Selected source hunk" card** | V6 has prose explanation card below diff tied to clicked row | P2-Medium |
| N6 | **Quiz option hover animation** | translateX(2px) + shadow on hover | P3-Low |
| N7 | **Ratchet Rubric 8-dim panel** | Full 8-dimension bar chart with scores and weakest indicator | P1-High |
| N8 | **Ratchet Phase 2.5 card** | Shows structural rewrite diff + human checkpoint buttons + radio options | P1-High |
| N9 | **Ratchet Benchmark transparency card** | Pinned suite stats + individual benchmark scores | P2-Medium |
| N10 | **Review 4 SRS buttons** (Again/Hard/Good/Easy) | V6 has 4 buttons with day predictions; viewer has 3 (wrong/hard/good) | P1-Medium |
| N11 | **Settings 8 tabs** | V6 has Account/Keys/Models/Privacy/Audit/Language/Appearance/Integrations; audit lists 5 | P1-Medium |
| N12 | **Settings toggle switches** | V6 has custom toggle UI with knob animation | P2-Low |
| N13 | **Graph Graphify source card** | Shows sync status, CLI commands, file paths | P2-Medium |
| N14 | **Graph SVG with typed nodes** | Different node styles for repo context/current diff/symbols/concepts | P1-High |
| N15 | **Graph filter chips** | All/This Diff/From Graphify/Learning Memory/Weak Claims | P2-Medium |
| N16 | **Graph legend bar** | Backdrop-blurred legend at bottom with color-coded node types | P2-Medium |
| N17 | **Onboarding stepper** | 4-step horizontal stepper with done/current/pending states | P2-Medium |
| N18 | **Onboarding Step 4 preview** | 3-column SPEC/Diff/Verdict preview card | P2-Medium |
| N19 | **Landing hero demo** | Tabbed Raw Diff / Aha Lesson preview with claim cards | P1-High |
| N20 | **Landing 5-step pipeline** | Steps component with 5 workflow stages | P1-High |
| N21 | **Landing evidence demo** | Before/after comparison section | P2-Medium |
| N22 | **Landing benchmark section** | 4 KPIs with DEMO tags | P2-Medium |
| N23 | **`--ink-2` and `--muted-2` tokens** | V6 uses these for secondary text; viewer maps everything to `--ink`/`--muted` | P3-Low |
| N24 | **`--subtle` value mismatch** | V6=#F2EFE7 vs Viewer=#F4F1E8 | P3-Low |
| N25 | **`--ink` value mismatch** | V6=#1C1B18 vs Viewer=#2E2A24 | P2-Medium |
| N26 | **`--hair` value mismatch** | V6=#E6E3D8 vs Viewer=#E6E1D4 | P3-Low |
| N27 | **Sidebar gradient background** | V6 uses gradient; viewer likely uses solid color | P3-Low |
| N28 | **`.code-block` pattern** | V6 has border-left 3px accent, specific padding/sizing | P3-Low |
| N29 | **State overlays** | V6 has empty/loading/error overlays via `data-state` attribute with styled `::before` | P2-Medium |
| N30 | **Drawer backdrop** | V6 has `.drawer-backdrop` with blur, opacity transition for mobile | P1-Medium (tied to mobile) |
| N31 | **Quiz Evidence sidebar** | V6 has code evidence + progress table in right column | P1-Medium |
| N32 | **Review "Easy" 4th SRS button** | V6 has 4 ratings (Again/Hard/Good/Easy); viewer may only have 3 | P1-Medium |

### 5.3 Audit Priority Corrections

| Audit Item | Audit Priority | Should Be | Reason |
|------------|---------------|-----------|--------|
| Card hover lift (gap #17) | Minor | P2-Medium | This is a core V6 interaction pattern used on KPI, agent cards, SRS buttons, quiz options — not just decorative |
| Mobile responsiveness (gap #7) | Critical | Demote to P2 | V6 mobile is also a prototype, and the product is primarily desktop-first local dev tool |
| Search bar Cmd+K (gap #1) | Critical | Keep Critical but note: backend has no search API | This needs new backend data model before frontend can implement |

---

## 6. Typography Usage Summary

| Element | Font | Size | Weight | Extras |
|---------|------|------|--------|--------|
| Body | sans | 15px | 400 | line-height 1.6 (zh: 1.75) |
| Page titles (h1) | serif | 36px | 500 | letter-spacing -.022em |
| Card headers (h3) | serif | 18px | 500 | letter-spacing -.012em |
| Section headers (h2) | serif | 38px | 500 | (in landing sections) |
| Prose body | serif | 17px | 400 | line-height 1.8 |
| Prose h2 | serif | 28px | 500 | border-bottom |
| Prose h3 | serif | 20px | 500 | |
| Nav items | sans | 14px | 400 | |
| Eyebrows/labels | mono | 10-11px | 400 | letter-spacing .14em, uppercase |
| Nav .en labels | mono | 10px | 400 | letter-spacing .08em |
| Badges | mono | 11px | 400 | letter-spacing .08em |
| Chips | sans | 12px | 400 | |
| Table headers | mono | 10.5px | 500 | letter-spacing .14em |
| Table cells | sans | 13px | 400 | |
| KPI values | serif | 34px | 500 | tabular-nums |
| KPI labels | mono | 10px | 400 | letter-spacing .14em |
| Code blocks | mono | 12.5px | 400 | |
| Diff code | mono | 12.5px | 400 | line-height 1.6 |
| Diff line nums | mono | 11px | 400 | |
| Flashcard front | serif | 26px | 400 | line-height 1.4 |
| SRS button labels | serif | 18px | 500 | |
| Quiz question | serif | 22px | 400 | |
| Hero h1 | serif | 68px | 500 | letter-spacing -.032em |
| Brand name | serif | 17px | 600 | |
| Search bar | sans | 13px | 400 | |

---

## 7. Interactive Behaviors in V6

| Interaction | CSS/JS | Location |
|------------|--------|----------|
| Nav item hover | bg `--accent-softer` + translateX(1px) | sidebar |
| Nav item active | bg #fff + shadow | sidebar |
| Card hover | shadow lift | all cards |
| KPI hover | translateY(-2px) + accent bar opacity .7 | dashboard |
| Button hover | translateY(-1px) + shadow | global |
| Button active | translateY(0) | global |
| Chip toggle | `.on` class swap | global |
| Claim card hover | translateX(2px) + border stronger | diff/lesson |
| Claim card selected | border accent + box-shadow ring | diff/lesson |
| Diff row clickable hover | brightness(.97) + accent outline | diff |
| Diff row selected | inset 3px accent shadow | diff |
| Quiz option hover | translateX(2px) + shadow | quiz |
| SRS button hover | translateY(-2px) + shadow | review |
| Toggle switch | knob translateX(16px) | settings |
| Copy button copied | green flash | skills |
| Page transition | fadeUp animation .28s | all pages |
| Sidebar drawer | translateX(-100%) → translateX(0) | mobile |
| Backdrop fade | opacity 0 → 1 | mobile |
| Scaffold tab | bg swap (subtle → white) | lesson rail |
| Search bar hover | bg #fff + border stronger | topbar |

---

## 8. Summary Statistics

| Metric | V6 HTML | Viewer |
|--------|---------|--------|
| Pages | 11 | 12 (+ NotFound) |
| CSS variables (light) | 22 base + ~20 extended | 22 base + 66 additional |
| Dark mode | None | Full WCAG AAA |
| Responsive breakpoints | 7 (540-1280px) | Limited |
| Nav sections | 3 labeled groups | Flat list |
| Topbar elements | 4 (breadcrumb + search + docs + new run) | 2 (brand + lang switcher) |
| Dashboard KPIs | 4 | 3 |
| Dashboard sections | 5 | 2 |
| Settings tabs | 8 | 0 (flat) |
| SRS rating buttons | 4 (Again/Hard/Good/Easy) | 3 |
| Font usage | Extensive serif/mono/sans mixing | Moderate |
| Accessibility features | Basic (skip-link, aria) | Extensive WCAG AAA |
| i18n | Hardcoded Chinese | 189-key bilingual |
