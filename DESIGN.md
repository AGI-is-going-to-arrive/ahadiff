# AhaDiff design contracts

## Goals

AhaDiff turns a bounded, reproducible change or a single Markdown document into
evidence-linked lessons, questions, and spaced-repetition material. Local artifacts and verifiable source
anchors are the authority. Generated explanations and optional LLM judgments do
not replace deterministic verification.

The author of a change is not an input constraint. Personal fixes, peer edits,
coding exercises, AI edits, and text/configuration revisions share the same
bounded-change workflow. The product teaches from before/after evidence; it
does not infer demonstrated execution or learning effectiveness from a score.

## Existing architecture

- `git/capture.py` normalizes Git changes, patches, file comparisons, and
  supported directory comparisons into run artifacts. Patch and file comparison
  inputs also work in a workspace without Git.
- `core/orchestrator.py` coordinates capture, claim extraction and verification,
  lessons, quizzes, evaluation, finalization, and concept updates. A run's
  finalized artifacts establish what the viewer may present as completed work.
  Run-local concepts from patch or file inputs are written before the first
  finalized checksum. Review database updates and Git concept projections stay
  after publication and do not mutate the sealed run directory.
- `llm/provider.py` handles request normalization, validation, budgets, cache
  identity, transport, audit, and usage. Adapters construct protocol-specific
  payloads; `llm/adapters/thinking.py` owns verified thinking controls.
- The local serve API protects writes with loopback/origin checks, a write
  token, and the appropriate repository or global configuration lock. The
  viewer consumes typed API contracts and maintains English/Chinese messages.

Page frames keep their reading-width cap centered within the area beside the
sidebar. Diff columns divide the available content width, so a wide viewport
cannot squeeze the code column by growing the inspector beyond the page cap.
Compact graph summaries retain content-based sizing inside flex toolbars.

## Learning source and onboarding decisions

Welcome, Onboarding, and Guide expose the same five choices: Git changes,
Two files, Paste a diff, Saved snapshot, and One Markdown document. All choices
open the shared Learn Mode dialog. Snapshot comparison retains `file_compare`
semantics; one Markdown file has a distinct `document` source and a document
evidence view. Lessons, quizzes, review, concepts, and quality history consume
the source kind instead of assuming every run has a patch. AI tool guidance remains an optional Git workflow.

An ordinary directory starts with `ahadiff serve`, which creates local state
as needed, followed by provider setup in Settings. The CLI `init` and `doctor`
commands still require a Git repository. Documentation must preserve this
distinction rather than require beginners to initialize Git for file learning.

Browser file inputs carry separate before/after UTF-8 contents and filenames
to the local capture API. They retain `file_compare` semantics and Notebook
cell-aware capture rather than degrading the input into a context-poor pasted
patch. Matching filenames are valid. The browser accepts at most 256 KiB per
file, 512 KiB combined, and a 1 MiB serialized request; pasted patches retain
their 64 KiB input bound. Draft contents are not stored in browser persistence.

Preview runs the normal safety and capture path without an LLM request.
The preview display is bounded at 64 KiB and distinguishes display truncation
from clipped capture. Source edits invalidate the prior preview. A preview
failure does not submit a learn run. Starting learning uses the configured
provider/privacy policy and persists the usual sanitized run artifacts.

File, pasted-patch, snapshot, and document entry points enable an explicit,
reversible force-learn choice for small exercises. This bypasses the learnability skip only; evidence
verification, safety gates, and deterministic verdict rules remain in force.

## Explicit snapshots, document evidence, and review context

`core/snapshots.py` persists immutable, explicitly selected baselines under
`.ahadiff/snapshots/`. It stores only the sanitized UTF-8 / NFC / LF learning
representation. Snapshot names and file basenames are portable; one file is
limited to 256 KiB, the store to 100 records and 16 MiB of record bytes.
No watcher, chat capture, source overwrite, or automatic baseline replacement
is part of this feature. Snapshot recovery restores a comparison reference,
not a complete original-file backup.

The version-1 record binds an ID, name, filename, source, creation time, size,
and content hash. Learn binds `snapshot_id` to `content_hash`; deletion binds
the selected record to `record_hash`. A deleted snapshot leaves existing runs
intact. A list may expose a corrupt/unsupported record as unavailable, and an
unsafe record without a readable record hash cannot be deleted through that
interface. Read/write/delete use bounded, no-follow, regular-file, hardlink,
reparse, lock, and atomic-write protections. Browser writes use the existing
same-origin token boundary. Restarting the app never silently replaces a
baseline or migrates an unknown snapshot version.

`core/source_evidence.py` builds format anchors from persisted safe text.
`SourceAnchor` includes source kind, format, side, file identity, locator,
line range, exact-quote hash, and a bounded quote. Markdown uses headings and
paragraphs; Notebook uses cell source; JSON/TOML/YAML use key paths. Locator
identity includes content and side, so moving or renaming different text does
not make it the same evidence. Unsupported or ambiguous structure retains an
explicit weak line fallback. The format index is capped at 4,096 anchors:
diff truncation remains explicit with hunk evidence available, while document
index overflow is rejected instead of accepting a partial denominator. A locator
does not turn a semantic interpretation
or a runtime-effect claim into a verified source fact.

PyYAML moved from the existing development dependency set into runtime at the
same locked version. Packaged installations need the same YAML key-location
capability as a checkout. YAML parsing uses bounded safe node composition;
custom object construction, executing tags, and unbounded alias/depth expansion
are outside the contract. Missing or unsupported parsing remains a visible
line-evidence fallback, rather than fabricated key-level certainty.

A standalone input accepts exactly one local `.md` or `.markdown` file, at most
256 KiB, and produces `document.md` rather than an empty-file-to-text diff.
Source identity binds the sanitized document hash. The document proves quoted
text and location; its assertions about the outside world still need independent
evidence. Document runs do not opt into diff specification alignment. Their
Diff Coverage and change-novelty Learnability dimensions are N/A with zero
maximums, excluded from the overall score. A separate document-anchor coverage
gate uses validated references, without fabricating hunk coverage. PDF,
remote page fetching, and arbitrary resource ingestion are outside this pilot.

Optional review context is at most 8 KiB of UTF-8 untrusted text. Redaction and
injection filtering run before generation. `review_context.json` is separately
marked `auxiliary_untrusted`; metadata records its use and content hash.
It cannot supply file-line evidence, displace counterevidence, or promote claim
states. Cache identity and exported provenance retain whether it was used.
Browser draft bodies remain outside observable pending/retry summaries and
persistent browser state; closing or changing a source aborts its preview.

New source-aware runs declare source evidence and bind their persisted source,
anchor index, and optional review context to finalization integrity. Source and
artifact digests, locator identity, quote, side, and range are revalidated at
read boundaries. A declared artifact that is missing, malformed, unsupported,
or mismatched fails closed. Old runs without the new declaration retain the
existing hunk contract; they are neither retroactively rewritten nor silently
promoted to format evidence. CLI/API/WebUI, lesson/quiz/review, export, and MCP
must preserve source kind and keep auxiliary notes separate from proof.
The existing `finalized.json` checksum scheme covers the artifacts; no signed
trust root or new finalization version is introduced. These checks detect
missing or inconsistent local artifacts, not a local owner rewriting the entire
checksum chain. No real user database migration or automatic rewrite of
historic run content is part of this work. Explicit quiz regeneration is the
selected-run mutation described below.

## Active transfer practice

The existing guided/recall/transfer taxonomy and SRS own practice state.
New learn requests default `active_practice` to false, retaining the existing
mixed allocation.
The explicit Learn Mode option, `learn --active-practice`, and
`regenerate RUN_ID --only quiz --active-practice` request open transfer questions
for every generated item. At three or more questions, prediction, completion,
and error-reason forms must all be represented. Producer validation and bounded
retry enforce the requested mode; a mixed response is not accepted as active
practice. CLI/API/preview submission share the flag. It is non-sensitive and
may remain in a pending summary, while source changes and dialog closure reset
the local choice. An absent estimate echo remains compatible with older API
responses. Regeneration intentionally replaces the selected run's quiz/cards,
recomputes the deterministic score, and reseals artifact checksums. Omitted
practice flags preserve the recorded run mode; `--mixed-practice` overrides it
back to mixed. Stale Judge results are invalidated instead of being reused or
automatically rerun.
Transfer exercises add prediction, completion, and error-reason variants,
without executing arbitrary code. Public question responses omit reference
answers, correctness flags, explanation, and evidence until an explicit attempt
is acknowledged. Related answer-bearing content cannot leak through another
question's sidebar or a hidden front-end payload.

Multiple-choice equality is mechanically checkable. Open exercises use a
reference comparison and bounded semantic self-assessment, not exact-text
matching as proof of correctness. WebUI free-form attempts stay in page memory;
only assessment, error category, and timing metadata enter practice signals.
SRS reuses the existing review queue and ratings rather than introducing a
second scheduling database.

A repeated same-question attempt counts as delayed recall only after at least
24 hours. A first exercise attempt counts as an unseen variant only when the
question explicitly represents a new scenario. Challenge lets the learner see
and rehearse the original solution, so its patch match/coverage feedback does
not establish unseen-variant independence. Score and advisory Judge remain
artifact/evidence-quality measures. Practice measurements require their own
sample counts and denominators. Dashboard separates initial, delayed-recall,
and unseen-variant self-reports and error categories. Empty denominators remain
null/unmeasured, and the historical SRS rating-improvement ratio is not relabeled
as transfer success. Absent samples do not establish learning gain.

## Model and reasoning decisions

Model identity, API protocol, and deployment limits are distinct. The vendored
model registry records native and route-specific limits with provenance. Live
limits, known registry data, and conservative fallbacks remain distinguishable.
Model-directory presence alone proves neither inference access nor capacity.
An unknown output maximum stays unknown in the UI. Local runtime capacity must
not be inferred from a cloud deployment of the same model.

An omitted thinking level uses the provider default. Explicit `none` requests
disabled thinking and is legal only where verified. Toggle-only models use an
explicit on/off choice; level-based models expose their supported levels.
Manual thinking budgets must fit the total output allowance. Validation and
budget normalization happen before cache lookup and dispatch. Cache identity
separates omission from disabling, and includes the applicable model profile.

Provider edits and role-model edits validate the prospective effective
configuration. A role cannot silently turn an explicit off setting into
reasoning. Creating a replacement provider remains possible when an unrelated
legacy role is already incompatible. Configuration preview uses the normal
global, repository, and environment precedence without persisting drafts.

## Guidance installation decisions

The install registry is the single catalogue for Settings and Guide. It carries
native files, localized usage, lifecycle, and source information. Installation
guidance in Guide is read-only and shows loading, empty, or retry states instead of fabricated
availability. Writing guidance does not install or authenticate a third-party
harness. A successful write remains successful if a later catalogue refresh
fails; old responses must not overwrite newer state.

Generated-file sentinels and marked sections define ownership. Previewed
manifests and hashes authorize the concrete write or removal. Symlink, reparse,
hardlink, special-file, and parent-path protections apply to updates as well as
new installs. Retired targets have explicit cleanup paths rather than new
installation recommendations.

## Platform and security boundaries

Linux read/open/close-without-write events do not trigger automatic learning.
On Windows, database creation uses parent-bound NT handles and keeps identity
and sharing protections through SQLite initialization. Native Windows input
paths are accepted only inside the workspace; ambiguous drive-relative, UNC,
ADS, and reparse paths remain rejected.

Directory comparison and Git hooks retain their documented platform limits.
Native Windows behavior requires a Windows runner; cross-platform type checks
and simulated branches do not establish native execution. LLM-generated content
is untrusted, and a high advisory judge score never overrides a failed hard gate.

Ambiguous request framing is rejected before JSON body parsing; normal chunked
requests remain subject to the same 1 MiB body limit. Request deadlines cancel
cooperative work before the first response headers. Streaming continues after
headers, and cancellation does not roll back already-started atomic thread work
or an independently submitted task.

The viewer can abort an estimate immediately. After it sends a learn submission,
it retains the acknowledgement so a cancellation can target the returned task
ID. An unknown submission outcome is not automatically retried. Completed tasks
refresh the onboarding run list, and local learning dialogs disable AppShell's
global search shortcuts.
Source buttons receive focus before opening the dialog so Safari restores the
trigger on close, including mouse and touch entry.

Onboarding checks the locally stored generation provider selection separately
from configuration-file validity. An empty or ambiguous selection is incomplete;
saved configuration alone is not evidence of successful authentication. Loading
and failed run-list refreshes stay distinct from a confirmed empty run history.
An unavailable database check does not assert that the database is unhealthy.
Notebook JSON has a fixed maximum container depth of 128 across supported Python
versions, with an iterative traversal that uses memory proportional to depth.

Production dependency manifests carry the patched runtime version floors as
well as lockfiles. Starlette's test client uses the separate httpx2 development
dependency; production provider transports continue to use httpx. Optional torch
and setuptools floors apply only to the optimizer extra. Build output reports
JavaScript transfer sizes without enforcing a fixed byte ceiling.

## Change history

- 2026-09-07: refreshed model and harness evidence, separated default/off
  thinking, synchronized provider/role/probe/cache semantics, unified the
  guidance catalogue, and repaired watcher, Windows file/database, and layered
  configuration handling.
- 2026-09-08: added shared source entry points, local file selection and safe
  diff preview, explicit persistent snapshots, active transfer practice, format
  evidence anchors, auxiliary review context, and independent Markdown learning.
  Beginner guidance covers ordinary workspaces and both viewer languages. These
  changes are pending publication; the source version remains 1.3.8.

The current source acceptance matrix is still being completed. Native Windows,
Linux, browser-matrix, packaging, and real-model execution claims require their
own current results; historical v1.3.8 checks do not validate these additions.
