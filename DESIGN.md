# AhaDiff design contracts

## Goals

AhaDiff turns a bounded, reproducible change into evidence-linked lessons,
questions, and spaced-repetition material. Local artifacts and verifiable source
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

Welcome, Onboarding, and Guide expose the same three choices: Git changes,
Two files, and Paste a diff. All choices open the shared Learn Mode dialog and
produce the existing run artifacts consumed by Lesson, Diff, Quiz, Review,
Concepts, and Ratchet. AI tool guidance remains an optional Git workflow.

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

File and pasted-patch entry points enable an explicit, reversible force-learn
choice for small exercises. This bypasses the learnability skip only; evidence
verification, safety gates, and deterministic verdict rules remain in force.

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
  diff preview, and synchronized beginner guidance around ordinary workspaces.
  These changes are pending publication; the source version remains 1.3.8.

Broader snapshot or standalone-document learning remains a proposal, not an
implemented contract. Those inputs need their own reproducible evidence anchors
before being described as verified learning.
