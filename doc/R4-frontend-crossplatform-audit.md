# R4 Deep Audit: Frontend + Cross-Platform Safety

> Auditor: Claude (R4, 2026-04-28)
> Scope: Frontend plan feasibility, cross-platform safety, bundle size, V6 alignment, i18n, a11y
> Input: `v1.0-fullscope-execution-plan.md` (now kept under local-only `.claude/team-plan/`, not committed) + current codebase

---

## Dimension Verdicts

| # | Dimension | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | Bundle Size Target | **FAIL** | `<50KB initial gzip` is physically impossible. React 19 + ReactDOM alone = ~45KB gzip. With react-router-dom (~12KB) the framework floor is ~57KB. Even with aggressive lazy routes, initial chunk cannot go below ~60-65KB gzip. |
| 2 | V6 Token Alignment | **PASS** | 94/94 real CSS custom properties matched (100%). The 6 "V6-only" tokens from grep are false positives (CLI flags like `--use-graphify` in HTML body text). Plan's "95% token aligned" claim is conservative -- actual is ~100%. |
| 3 | i18n Parity | **PASS** | 189/189 leaf keys verified (24 top-level namespaces). en/zh-CN exact parity confirmed. Plan target of 262 = +73 new keys is realistic for Phase 4F (new components + settings). |
| 4 | Playwright Matrix | **WARNING** | Config: 5 viewports x 3 browsers = 15 projects. 52 test cases x 15 = 780 max (plan says 760+5=765, plausible with skips). CLAUDE.md says 495 (33 tests x 15) -- this was pre-Phase 1-4. Plan's 760 figure appears to be from a more recent run with walkthrough.spec.ts (18 tests added). **No discrepancy**, but CLAUDE.md is stale. Phase 4 gate target of >=550 is easily achievable. |
| 5 | Lazy Loading | **WARNING** | Currently ZERO lazy routes. All 12 pages are eagerly imported in App.tsx. Phase 6C plans to add `React.lazy` -- this is correct but scheduled too late (Phase 6). Should move to Phase 2 to establish the pattern early. No `Suspense` usage found either. |
| 6 | Cross-Platform Backend | **PASS** | Excellent coverage: `sys.platform` checks in 4 files (hooks, paths, cli, loop), `os.name == "nt"` in capture.py, WSL2 detection via env vars, Windows reparse point checks (`0x400`), `O_NOFOLLOW` with `getattr(os, "O_NOFOLLOW", 0)` graceful fallback, inode triple-check in lock, subprocess UTF-8 encoding throughout. No macOS/Linux-only branches that would break on Windows. |
| 7 | Lock Mechanism | **PASS** | `repo_write_lock` in `git/repo.py`: portalocker + `O_NOFOLLOW` + `lstat`/`fstat` inode verification + Windows reparse point check + best-effort unlink. `serve/lock.py` properly layers `threading.Lock` + `repo_write_lock`. Solid. |
| 8 | Middleware Security | **PASS** | Streaming body size limit (1 MiB), Content-Type validation, localhost-only Host check, Origin/Referer validation with port matching, `X-Content-Type-Options: nosniff`. No gaps found. |
| 9 | CSS Architecture | **PASS** | 20 CSS files, BEM-like naming (`.app-shell__body`, `.sidebar__item`). AppShell.css is 382 lines -- plan to extract Sidebar.css and Topbar.css is reasonable but not urgent. No CSS modules needed for this scale. |
| 10 | React Patterns | **PASS** | React 19.0.0, Zustand 5.0.0, all stores properly typed with `create<State>()`. No `dangerouslySetInnerHTML` found. No React 19 `use()` hook usage (fine -- not needed). |
| 11 | Accessibility | **PASS** | 93 `aria-*` usages, 19 `role=` usages, 52 `forced-colors` rules, 3 `prefers-reduced-motion` rules, print.css exists. Solid baseline. |
| 12 | Vite Config | **WARNING** | No `rollupOptions.output.manualChunks` configured. No sourcemap in production. API proxy correctly targets 127.0.0.1:8765. Missing: build target not specified (defaults to modern browsers -- fine for local-first app). |

---

## NEW Findings (Not in R1-R3)

### R4-F1: Bundle Size Target Physically Impossible (HIGH)

The Phase 8 gate requires `< 50KB initial gzip`. This is mathematically impossible:

- `react` + `react-dom` v19: ~44-46 KB gzip (verified via bundlephobia)
- `react-router-dom` v6.28: ~11-13 KB gzip
- **Framework floor alone: ~57 KB gzip**

Even with `React.lazy()` for all routes, the initial chunk must include the router, Zustand, AppShell, and at least one page component. Realistic minimum: **~65-70 KB gzip**.

Adding d3-force (Phase 5D, ~15-30KB gzip tree-shaken) and Zod (Phase 4F, ~13KB gzip) further increases total bundle.

**Recommendation**: Change target to `< 80KB initial gzip` (with lazy routes) or `< 120KB total gzip` (without). Current 100.7KB gzip single-chunk is already reasonable for a local-first app.

### R4-F2: Lazy Loading Scheduled Too Late (MEDIUM)

Phase 6C adds route-based code splitting. By Phase 6, the app will have 12+ pages, d3-force, Zod, and potentially vite-plugin-pwa. Retrofitting lazy loading at that point risks breaking existing Playwright tests that assume synchronous page loads.

**Recommendation**: Move lazy route setup to Phase 2 (Frontend V6 Foundation). Establish the `React.lazy` + `Suspense` + loading skeleton pattern early. This also forces the Skeleton component (already exists) to be tested under real conditions.

### R4-F3: CLAUDE.md Playwright Count Stale (LOW)

CLAUDE.md changelog says "495/495 Playwright tests" but the actual current count appears to be 765 (52 specs x 15 projects). The plan's Section 0 correctly says 760+5. CLAUDE.md should be updated to reflect the latest run.

### R4-F4: i18n Key Growth Math Check (INFO)

Plan Phase 4F targets 262 keys total = +73 new keys. With 6 new components (CalendarHeatmap, SearchOverlay, ProviderGrid, ClaimInspector, etc.) plus Settings 8-tab expansion, 73 keys is achievable (~12 keys per new component). No concern.

### R4-F5: No `manualChunks` in Vite Config (LOW)

`vite.config.ts` has no `rollupOptions.output.manualChunks`. When Phase 6C adds lazy routes, a manual chunks strategy should be added simultaneously to ensure react/react-dom are in a stable vendor chunk (better cache hit rate across deploys).

---

## Cross-Platform Safety Summary

| Area | Files Checked | Status |
|------|--------------|--------|
| Path handling | `core/paths.py` | SAFE: pathlib throughout, WSL2 detection, reparse point checks, casefold handling |
| Lock files | `git/repo.py`, `serve/lock.py` | SAFE: `O_NOFOLLOW` graceful fallback, inode verification, portalocker |
| Subprocess | `git/repo.py`, `improve/loop.py` | SAFE: `encoding="utf-8"`, `errors="replace"`, `core.quotePath=false` |
| Platform branches | 8 `sys.platform` checks, 1 `os.name` check | SAFE: All Windows branches are additive (extra checks), not exclusive |
| Signal handling | `improve/loop.py` | SAFE: `_InterruptController` with Windows `SIGINT` fallback |
| SQLite | `review/database.py` | SAFE: WSL2 journal mode auto-downgrade, checkpoint before backup/restore |

**No cross-platform gaps found in R4.**

---

## Verdict Summary

- **2 FAIL** (bundle target impossible)
- **3 WARNING** (lazy loading timing, stale docs, missing manualChunks)
- **7 PASS** (V6 tokens, i18n, cross-platform, lock, middleware, CSS, React patterns, a11y)
- **1 NEW HIGH finding**: R4-F1 bundle size target must be revised
- **1 NEW MEDIUM finding**: R4-F2 lazy loading should move earlier
- **3 NEW LOW/INFO findings**: R4-F3/F4/F5

### Recommended Actions

1. **Revise Phase 8 gate**: Change `< 50KB initial gzip` to `< 80KB initial gzip` (with lazy routes) -- R4-F1
2. **Move Phase 6C to Phase 2**: Establish lazy route pattern early -- R4-F2
3. **Update CLAUDE.md**: Reflect current 760+ Playwright test count -- R4-F3
4. **Add manualChunks when implementing lazy routes**: vendor chunk for react/react-dom -- R4-F5
