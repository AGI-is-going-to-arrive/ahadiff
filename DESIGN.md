# AhaDiff design contracts

## Goals

AhaDiff turns a bounded, reproducible change into evidence-linked lessons,
questions, and spaced-repetition material. Local artifacts and verifiable source
anchors are the authority. Generated explanations and optional LLM judgments do
not replace deterministic verification.

## Existing architecture

- `git/capture.py` normalizes Git changes, patches, file comparisons, and
  supported directory comparisons into run artifacts. Patch and file comparison
  inputs also work in a workspace without Git.
- `core/orchestrator.py` coordinates capture, claim extraction and verification,
  lessons, quizzes, evaluation, finalization, and concept updates. A run's
  finalized artifacts establish what the viewer may present as completed work.
- `llm/provider.py` handles request normalization, validation, budgets, cache
  identity, transport, audit, and usage. Adapters construct protocol-specific
  payloads; `llm/adapters/thinking.py` owns verified thinking controls.
- The local serve API protects writes with loopback/origin checks, a write
  token, and the appropriate repository or global configuration lock. The
  viewer consumes typed API contracts and maintains English/Chinese messages.

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
native files, localized usage, lifecycle, and source information. Guide is read
only and must show loading, empty, or retry states instead of fabricated
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

## Change history

- 2026-09-07: refreshed model and harness evidence, separated default/off
  thinking, synchronized provider/role/probe/cache semantics, unified the
  guidance catalogue, and repaired watcher, Windows file/database, and layered
  configuration handling.

Broader snapshot or standalone-document learning remains a proposal, not an
implemented contract. Those inputs need their own reproducible evidence anchors
before being described as verified learning.
