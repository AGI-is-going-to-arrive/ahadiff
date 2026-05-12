# RFC 2.2 — Local Static Preview Export

**Status**: Draft
**Date**: 2026-05-12
**Scope**: Local-only static export of finalized learning artifacts; optional user self-hosting. No AhaDiff cloud.

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
      assets/                 viewer JS/CSS chunks (hashed, identical to `serve`)
      data/run.json           one run only; redacted; no claims raw prompts
      data/concepts.jsonl     only concepts referenced by this run
      manifest.json           run_id, privacy_mode, redaction_version, sha256 of every file
      LICENSE.txt, README.txt purpose, regeneration command, "do not host without consent"
```

Export is **per-run** by default; a `--bundle` flag may include adjacent ratchet entries that share the same `privacy_mode`. The bundle is a directory plus a deterministic `.zip` so checksums are reproducible. Nothing in the bundle references network resources (no CDNs, no remote fonts, no analytics).

## 4. Threat Model (MUST)

| # | Threat | Mitigation |
|---|--------|-----------|
| T1 | Raw secrets/code snippets leak in lesson prose | All artifacts pass `redaction_pipeline()` again at export time (defense-in-depth, even if review.sqlite was already redacted). Export aborts if `redact_failed` is observed. |
| T2 | `strict_local` run accidentally exported in full | Hard gate: when `privacy_mode == strict_local`, exporter only emits the redacted projection and stamps `manifest.privacy_mode = strict_local`. No `--include-raw` flag is offered. |
| T3 | User unknowingly publishes prompt injection bait | Lesson and concept text are re-scanned by `injection.detect()`; matches are stripped or annotated before write. |
| T4 | Self-host bundle ends up on a public origin | `README.txt` and `index.html` `<meta name="robots" content="noindex,nofollow">` plus a visible "user-hosted copy, not authoritative" banner. No AhaDiff branding implies cloud trust. |
| T5 | Tampered bundle re-imported into a new repo | `manifest.json` ships sha256 per file plus a top-level digest. Import is *not* offered in 2.2; bundles are read-only artifacts. |
| T6 | Path/symlink abuse during export write | Reuse the install module's no-follow / reparse-point guard; refuse to write outside the chosen output directory. |
| T7 | Export reveals deleted history when user later redacts review.sqlite | Exports embed `manifest.generated_at` and `redaction_version`; the UI warns that on-disk bundles are immutable copies, regenerate to refresh. |

Audit: every export is logged to `audit.jsonl` (`event=export.preview`, `run_id`, `privacy_mode`, output digest) and to `audit.private.jsonl` for the redacted detail.

## 5. Local-First Privacy Flow

1. User clicks "Export Preview" in the viewer (Lesson/Run/Ratchet page) or runs `ahadiff export preview <run_id> --out ./preview`.
2. Backend reads run, runs redaction + injection scan, computes diff between resolved bundle and what would have shipped under `explicit_remote`; shows a confirmation dialog listing redaction counts, file count, total size, `privacy_mode`.
3. User must check "I have reviewed the redacted preview and accept that any hosting is my responsibility" before the bundle is materialized. `strict_local` runs are exported with redaction enforced and the checkbox copy makes that explicit.
4. Output is the directory + a sibling `.zip`. CLI prints absolute path; viewer offers "Reveal in file manager" / "Open index.html".

## 6. Cross-Platform

- Pure-Python writer using `pathlib` and the existing safe-write helper; no shell-outs.
- Filenames are ASCII-only and case-insensitive-safe (Windows/macOS).
- `.zip` is built with `zipfile` using deterministic mtimes for reproducible digests.
- Viewer assets are the same hashed chunks emitted by `pnpm build`; `index.html` works from `file://` (HashRouter + relative asset paths, no service worker registration in exported mode).

## 7. Frontend Interaction

A single "Export Preview" button per run surfaces a modal: redaction summary, privacy mode, destination picker, confirm checkbox. Success state shows the local path and "Open" / "Copy path". No AhaDiff URL is ever produced or suggested. The modal links to `doc/self-host.md` for the user's own deployment.

## 8. Test Strategy

- Unit: redaction parity (exported bundle == `redaction_pipeline(run)`); manifest digests stable across runs (deterministic ordering); symlink/reparse-point refusal; `strict_local` always emits redacted; injection scrubbing.
- Integration: export → unzip → open `index.html` via headless browser → assert run title, lesson section, quiz options render with zero network requests (Playwright `route('**/*')` asserting only `file://` and data URIs).
- Cross-platform smoke in CI matrix (ubuntu/macos/windows): zip determinism + open-in-browser sanity.
- Negative: export with active `redact_failed` flag must abort with stable `ErrorCode`.

## 9. Release Gate

- Independent feature flag `export.preview_static` (default off in 2.2 RC, on at GA).
- **Zero changes** to `serve` binding, auth, or CSP; no new network ports.
- Ship behind `ahadiff[preview]` extra if any optional dep is required; otherwise built-in.
- Docs: `doc/self-host.md` (Caddy/nginx static config) clearly labeled "user-operated, not AhaDiff-hosted".

## 10. Out of Scope (NOT)

- No AhaDiff-hosted preview URL, CDN upload, share link, or `0.0.0.0` bind.
- No multi-tenant, accounts, or auth in the exported bundle.
- No realtime collaboration, comments, or telemetry in the bundle.
- No reuse of GitHub Actions/CI artifact storage as a public preview channel.
- No automatic re-export on every run; export is an explicit user action.
