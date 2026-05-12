# RFC 2.5 — APKG Stable GUID + Custom CSS

- Status: Draft
- Date: 2026-05-12
- Owner: AhaDiff core (backend = Codex, viewer = Claude)
- Scope: `/api/export/apkg`, `src/ahadiff/review/apkg_export.py`

## 1. Target Users
Devs who already review AhaDiff cards in Anki Desktop / AnkiDroid / AnkiMobile. They re-export after each learn run and expect updates to *replace* prior cards, not duplicate them.

## 2. Problem
`apkg_export.py` already uses `genanki.guid_for(row["card_id"])`, but the spec is not pinned. If we later derive cards from `(run_id, concept)` or recycle `card_id`s during DB migration, GUIDs silently shift and Anki creates duplicates. CSS is a single inline literal — no diff-aware styling (changed/added/removed lines), no dark-mode hook, no template versioning.

## 3. Design

### 3.1 Stable GUID
- Canonical input: the current `cards.id` value, surfaced by the APKG exporter as `row["card_id"]`. Today quiz card ids are deterministic `card_<12-hex-digest>` values derived from `(run_id, question_id-or-question, concept)`, not UUIDv4.
- Algorithm: `genanki.guid_for(f"ahadiff:v1:{card_id}")` — namespace prefix prevents collision with non-AhaDiff decks and lets us bump to `v2` if card identity semantics ever change.
- Contract test: same `card_id` across two exports → byte-identical GUID; different `card_id` → different GUID. A migration that changes `cards.id` semantics must explicitly document whether it intentionally causes one duplication event.

### 3.2 Custom CSS template
- Storage: `src/ahadiff/review/templates/anki_card.css` (packaged resource, shipped in wheel). Loaded via `importlib.resources` at export time; **not** user-editable in v1 (avoids untrusted CSS shipping into third-party Anki).
- Content: diff-line classes (`.ahadiff-add`, `.ahadiff-del`, `.ahadiff-ctx`), claim-status pills (verified/weak/contradicted), monospace block for `display_path:source_ref`, dark-mode via `@media (prefers-color-scheme: dark)`.
- Versioning: CSS file carries `/* ahadiff-css-version: 1 */`; model GUID stays stable, so updating CSS just restyles existing cards in place.

## 4. Security Boundary
- Anki renders cards via QtWebEngine (desktop) / WebView (mobile) — effectively a browser. CSS is low-risk but `qfmt`/`afmt` HTML is **not**: card content already passes through `redaction_pipeline()` and existing `html.escape()` in `_front`/`_back`. RFC adds no new sinks.
- GUID input is the existing `card_id` digest only — no path, no secret, no diff content. Even if APKG is shared, GUID leaks nothing beyond "this card exists".
- Custom CSS is read-only packaged resource. Users cannot inject CSS via API; future user-CSS feature is explicitly out-of-scope.

## 5. Local-First Privacy
APKG already embeds lesson Q/A. Export must honor `privacy_mode`:
- `strict_local` (default): allow export (file stays local).
- `redacted_remote`: allow export, but cards already redacted at generation.
- `explicit_remote`: allow export, identical behavior.
No new privacy surface — APKG is a file the user downloads; no upload, no telemetry.

## 6. Cross-Platform
`genanki` produces a plain SQLite-in-zip APKG that Anki Desktop (Win/macOS/Linux), AnkiDroid, AnkiMobile, and AnkiWeb all accept. CSS is plain CSS3 — no platform branches.

## 7. Test Strategy
1. Unit: `test_guid_stability` — export twice, assert identical GUIDs for same `card_id`; mutate `card_id`, assert different GUID.
2. Unit: `test_css_loaded` — CSS file present, version comment matches, byte-length non-empty.
3. Unit: `test_namespace_prefix` — assert GUID input string starts with `ahadiff:v1:`.
4. Integration: existing `/api/export/apkg` smoke test still passes (no schema change).
5. Manual smoke (release checklist, not CI): import APKG into Anki Desktop 25.x and AnkiDroid 2.20.x; re-export and confirm zero duplicate notes.

## 8. Release Gate
- No new dependency.
- `/api/export/apkg` response shape unchanged (still `200 application/octet-stream` or `501 FEATURE_UNAVAILABLE`).
- Backward compatibility: users who already imported v0 APKGs get **one** duplication event on first v1 export because current code uses `genanki.guid_for(row["card_id"])` without the `ahadiff:v1:` namespace. Documented in `CHANGELOG`. No silent data loss.
- Coverage: `apkg_export.py` ≥90% line coverage.

## 9. What NOT to Do
- No Anki sync / AnkiWeb upload. File export only.
- No user-supplied CSS in v1.
- No card-type proliferation (cloze, image occlusion) — stays Basic.
- No editing existing decks in place — every export is a fresh `.apkg` the user imports.

## 10. Open Questions
- Should we ship a second model for misconception cards (ABCD)? Deferred to RFC 2.6.
- Auto-prune `result_events` for deleted `card_id`s before export? Current DB uses `cards.id TEXT PRIMARY KEY`; no UUIDv4/non-recycling contract is documented yet, so this remains deferred.
