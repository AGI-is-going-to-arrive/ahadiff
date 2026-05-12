# RFC 2.2 — Local Static Preview Export

**Status**: IMPLEMENTED SUBSET — minimal local static preview landed; full offline viewer/export mode remains future work
**Date**: 2026-05-12
**Scope**: Local-only static export of finalized learning artifacts; optional user self-hosting. No AhaDiff cloud.

**Current-code truth (2026-05-12)**:
- Implemented: `ahadiff export preview <run_id> --out <path>` and `POST /api/export/preview`.
- The implemented bundle is a minimal local static preview: `README.txt`, `index.html`, `data/run.json`, `data/concepts.json`, `manifest.json`, plus a deterministic zip built from the manifest allowlist.
- API export preview is fixed to `strict_local`; CLI exposes `--privacy-mode`.
- The writer rejects path traversal, Windows reserved names, ADS `:`, symlink/reparse/non-regular/hardlink/FIFO and zip entries not present in the manifest.
- Not implemented yet: a full Vite export/offline mode with copied hashed viewer assets, `file://` browser E2E, or a self-hosting doc.

## 1. Motivation

Users want to (a) open a polished snapshot of a run outside the live `ahadiff serve` process, (b) attach a self-contained preview to a code review, or (c) host their own static copy on infrastructure they already control. `ahadiff serve` is frozen at `127.0.0.1`; this RFC adds an export-to-static-files path that respects the same privacy contract without ever introducing an AhaDiff-hosted surface.

## 2. Target / Non-target Users

- **Target**: developers who own the repo and want a local HTML snapshot of a single `run_id` (lesson + concepts + ratchet + quiz answers) for self-hosting, archival, or offline review.
- **Non-target**: anyone needing AhaDiff-hosted sharing, multi-tenant SaaS, public preview URLs, real-time collaboration, or org-wide search. Those are explicitly out of scope.

## 3. Data Model

```
finalized run (review.sqlite + runs/<run_id>/ + concepts.jsonl)
  -> redaction_pipeline() (per privacy_mode)
  -> static_export_bundle/  (deterministic file tree)
      index.html              entry; routes baked as #/run/<id>, #/lesson, ...
      assets/                 future full viewer export target; not present in the current minimal preview
      data/run.json           one run only; redacted; no claims raw prompts
      data/concepts.jsonl     only concepts referenced by this run
      manifest.json           run_id, privacy_mode, sha256/size for every emitted file
      LICENSE.txt, README.txt purpose, regeneration command, "do not host without consent"
```

Export is **per-run**. There is no `--bundle` flag today. The current bundle is a directory plus a deterministic `.zip` so checksums are reproducible. Nothing in the current preview references network resources.

## 4. Threat Model (MUST)

| # | Threat | Mitigation |
|---|--------|-----------|
| T1 | Raw secrets/code snippets leak in lesson prose | All artifacts pass `redaction_pipeline()` again at export time (defense-in-depth, even if review.sqlite was already redacted). Export aborts if `redact_failed` is observed. |
| T2 | `strict_local` run accidentally exported in full | Hard gate: when `privacy_mode == strict_local`, exporter only emits the redacted projection and stamps `manifest.privacy_mode = strict_local`. No `--include-raw` flag is offered. |
| T3 | User unknowingly publishes prompt injection bait | Lesson and concept text are re-scanned through the existing prompt-injection helpers; do not reference a non-existent `injection.detect()` API. |
| T4 | Self-host bundle ends up on a public origin | `README.txt` and `index.html` `<meta name="robots" content="noindex,nofollow">` plus a visible "user-hosted copy, not authoritative" banner. No AhaDiff branding implies cloud trust. |
| T5 | Tampered bundle re-imported into a new repo | `manifest.json` ships sha256 per file plus a top-level digest. Import is *not* offered in 2.2; bundles are read-only artifacts. |
| T6 | Path/symlink abuse during export write | Reuse the install module's no-follow / reparse-point guard, plus an export-specific output-root containment check for every generated file. |
| T7 | Export reveals deleted history when user later redacts review.sqlite | Exports embed `manifest.generated_at` and `redaction_version`; the UI warns that on-disk bundles are immutable copies, regenerate to refresh. |

Audit: every export is logged to `audit.jsonl` (`event=export.preview`, `run_id`, `privacy_mode`, output digest) and to `audit.private.jsonl` for the redacted detail.

## 5. Local-First Privacy Flow

1. User clicks "Export Preview" in the viewer (Lesson/Run/Ratchet page) or runs a new CLI command such as `ahadiff export preview <run_id> --out ./preview` after the CLI contract is added.
2. Backend reads run, runs redaction + injection scan, computes diff between resolved bundle and what would have shipped under `explicit_remote`; shows a confirmation dialog listing redaction counts, file count, total size, `privacy_mode`.
3. Current WebUI Export modal requests the backend preview and displays the returned manifest/path metadata; there is not yet a destination picker or self-host confirmation copy.
4. Output is the directory + a sibling `.zip`. CLI prints the generated paths.

## 6. Cross-Platform

- Pure-Python writer using `pathlib`, an export-root containment helper, and the existing safe-write guard; no shell-outs.
- Filenames are ASCII-only and case-insensitive-safe (Windows/macOS).
- `.zip` is built with `zipfile` using deterministic mtimes for reproducible digests.
- The current minimal `index.html` is handwritten static HTML, not the full React viewer export. Full `file://` viewer mode remains future work.
- Windows reserved names, long paths, reparse points, hardlinks, and parent symlink swaps are negative tests, not assumptions.

## 7. Frontend Interaction

A single "Export Preview" button per run surfaces a modal: redaction summary, privacy mode, destination picker, confirm checkbox. Success state shows the local path and "Open" / "Copy path". No AhaDiff URL is ever produced or suggested. The modal links to `doc/self-host.md` for the user's own deployment.

## 8. Test Strategy

- Unit: manifest digests stable across runs (deterministic ordering); symlink/reparse/non-regular/hardlink/FIFO refusal; strict-local API behavior; manifest allowlist zip writing.
- Not yet verified: export → unzip → open full React viewer via headless browser with zero HTTP(S) requests.
- Cross-platform smoke in CI matrix (ubuntu/macos/windows): zip determinism + open-in-browser sanity.
- Negative: export with active `redact_failed` flag must abort with stable `ErrorCode`.

## 9. Release Gate

- Current code does not add an `export.preview_static` feature flag.
- **Zero changes** to `serve` binding, auth, or CSP; no new network ports.
- Future full offline viewer mode must prove that `/api/auth/token` and `/api/locale` bootstrap paths are not called.
- Ship behind `ahadiff[preview]` extra if any optional dep is required; otherwise built-in.
- Docs: `doc/self-host.md` (Caddy/nginx static config) clearly labeled "user-operated, not AhaDiff-hosted".

## 10. Out of Scope (NOT)

- No AhaDiff-hosted preview URL, CDN upload, share link, or `0.0.0.0` bind.
- No multi-tenant, accounts, or auth in the exported bundle.
- No realtime collaboration, comments, or telemetry in the bundle.
- No reuse of GitHub Actions/CI artifact storage as a public preview channel.
- No automatic re-export on every run; export is an explicit user action.
