from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ahadiff.contracts import ClaimRecord, SourceHunk, compute_runtime_eval_bundle_version
from ahadiff.core.errors import InputError
from ahadiff.git.line_map import build_line_map, serialize_line_map_payload

from .evaluator import ScoreReport, evaluate_run
from .rubric import load_rubric

BenchmarkEntryKind = Literal["eval", "integration"]
BenchmarkVisibility = Literal["private", "public"]

_REQUIRED_EVAL_FILES = (
    "diff.patch",
    "ground_truth.md",
    "qa_probe.jsonl",
    "expected_concepts.json",
)
_REQUIRED_INTEGRATION_FILES = (
    "diff.patch",
    "expected_artifacts_manifest.json",
    "expected_results_snapshot.json",
)


@dataclass(frozen=True)
class BenchmarkEntry:
    entry_id: str
    kind: BenchmarkEntryKind
    group: str
    path: Path
    capability_level: int
    degraded: bool
    language: str
    tags: tuple[str, ...]

    @property
    def required_files(self) -> tuple[str, ...]:
        if self.kind == "eval":
            return _REQUIRED_EVAL_FILES
        return _REQUIRED_INTEGRATION_FILES


@dataclass(frozen=True)
class BenchmarkManifest:
    schema_version: int
    suite_id: str
    suite_digest: str
    visibility: BenchmarkVisibility
    entries: tuple[BenchmarkEntry, ...]
    path: Path

    @property
    def root(self) -> Path:
        return self.path.parent


@dataclass(frozen=True)
class BenchmarkReport:
    suite_id: str
    suite_digest: str
    eval_bundle_version: str
    model_id: str
    api_family_version: str
    output_lang: str
    comparable_entry_count: int
    excluded_degraded_count: int
    mean_score: float
    claim_verification_rate: float
    dimension_means: dict[str, float]
    entries: tuple[dict[str, object], ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "suite_id": self.suite_id,
            "suite_digest": self.suite_digest,
            "eval_bundle_version": self.eval_bundle_version,
            "model_id": self.model_id,
            "api_family_version": self.api_family_version,
            "output_lang": self.output_lang,
            "comparable_entry_count": self.comparable_entry_count,
            "excluded_degraded_count": self.excluded_degraded_count,
            "mean_score": self.mean_score,
            "claim_verification_rate": self.claim_verification_rate,
            "dimension_means": self.dimension_means,
            "entries": list(self.entries),
        }


def load_benchmark_manifest(path: Path) -> BenchmarkManifest:
    payload = _load_json_object(path)
    schema_version = payload.get("schema_version")
    suite_id = payload.get("suite_id")
    suite_digest = payload.get("suite_digest")
    visibility = payload.get("visibility")
    raw_entries = payload.get("entries")
    if schema_version != 1:
        raise InputError("benchmark manifest schema_version must be 1")
    if not isinstance(suite_id, str) or not suite_id:
        raise InputError("benchmark manifest suite_id must be a non-empty string")
    if not isinstance(suite_digest, str) or len(suite_digest) != 64:
        raise InputError("benchmark manifest suite_digest must be a 64-character sha256 hex")
    if visibility not in {"private", "public"}:
        raise InputError("benchmark manifest visibility must be private or public")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise InputError("benchmark manifest entries must be a non-empty list")
    raw_entry_items = cast("list[object]", raw_entries)
    entries = tuple(_parse_entry(item, path.parent) for item in raw_entry_items)
    return BenchmarkManifest(
        schema_version=schema_version,
        suite_id=suite_id,
        suite_digest=suite_digest,
        visibility=cast("BenchmarkVisibility", visibility),
        entries=entries,
        path=path,
    )


def compute_suite_digest(manifest: BenchmarkManifest) -> str:
    chunks: list[bytes] = [
        f"schema_version={manifest.schema_version}".encode(),
        f"suite_id={manifest.suite_id}".encode(),
        f"visibility={manifest.visibility}".encode(),
    ]
    for entry in sorted(manifest.entries, key=lambda item: item.entry_id):
        chunks.append(
            json.dumps(
                {
                    "id": entry.entry_id,
                    "kind": entry.kind,
                    "group": entry.group,
                    "path": entry.path.as_posix(),
                    "capability_level": entry.capability_level,
                    "degraded": entry.degraded,
                    "language": entry.language,
                    "tags": list(entry.tags),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for filename in entry.required_files:
            fixture_path = manifest.root / entry.path / filename
            if not fixture_path.is_file():
                raise InputError(
                    f"benchmark fixture {entry.entry_id} is missing required file: {filename}"
                )
            relative_path = fixture_path.relative_to(manifest.root).as_posix()
            chunks.append(
                relative_path.encode("utf-8")
                + b"\n"
                + hashlib.sha256(fixture_path.read_bytes()).hexdigest().encode("ascii")
            )
    return hashlib.sha256(b"\n---\n".join(chunks)).hexdigest()


def verify_suite_digest(manifest: BenchmarkManifest) -> str:
    actual_digest = compute_suite_digest(manifest)
    if actual_digest != manifest.suite_digest:
        raise InputError(
            "benchmark manifest suite_digest mismatch: "
            f"expected {manifest.suite_digest}, got {actual_digest}"
        )
    return actual_digest


def run_benchmark_suite(
    manifest_path: Path,
    *,
    suite: str = "local",
    model_id: str = "deterministic-fixture",
    api_family_version: str = "none",
    output_lang: str = "en",
) -> BenchmarkReport:
    if suite != "local":
        raise InputError("only the local benchmark suite is available in this build")
    manifest = load_benchmark_manifest(manifest_path)
    verify_suite_digest(manifest)
    eval_entries = tuple(entry for entry in manifest.entries if entry.kind == "eval")
    if len(eval_entries) != 20:
        raise InputError(
            f"local benchmark suite must contain 20 eval entries, found {len(eval_entries)}"
        )

    entry_payloads: list[dict[str, object]] = []
    comparable_reports: list[ScoreReport] = []
    with tempfile.TemporaryDirectory(prefix="ahadiff-benchmark-") as temp_dir:
        temp_root = Path(temp_dir)
        for entry in eval_entries:
            run_path = _materialize_eval_fixture(manifest.root, entry, temp_root)
            report = evaluate_run(run_path)
            entry_payloads.append(
                {
                    "id": entry.entry_id,
                    "group": entry.group,
                    "language": entry.language,
                    "degraded": entry.degraded,
                    "overall": round(report.overall, 2),
                    "verdict": report.verdict,
                    "weakest_dim": report.weakest_dim,
                    "claim_verification_rate": _claim_verification_rate(run_path),
                }
            )
            if not entry.degraded:
                comparable_reports.append(report)

    return _build_report(
        manifest=manifest,
        reports=tuple(comparable_reports),
        all_entries=tuple(entry_payloads),
        excluded_degraded_count=len(eval_entries) - len(comparable_reports),
        model_id=model_id,
        api_family_version=api_family_version,
        output_lang=output_lang,
    )


def write_benchmark_report(path: Path, report: BenchmarkReport, *, overwrite: bool = True) -> Path:
    if path.exists() and not overwrite:
        raise InputError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _parse_entry(raw_value: object, manifest_root: Path) -> BenchmarkEntry:
    if not isinstance(raw_value, dict):
        raise InputError("benchmark manifest entry must be a JSON object")
    payload = cast("dict[str, object]", raw_value)
    entry_id = _required_string(payload, "id")
    kind = _required_string(payload, "kind")
    group = _required_string(payload, "group")
    raw_path = _required_string(payload, "path")
    capability_level = payload.get("capability_level")
    degraded = payload.get("degraded")
    language = _required_string(payload, "language")
    raw_tags = payload.get("tags", [])
    if kind not in {"eval", "integration"}:
        raise InputError(f"benchmark manifest entry {entry_id} has invalid kind: {kind}")
    if not isinstance(capability_level, int) or capability_level < 1:
        raise InputError(f"benchmark manifest entry {entry_id} has invalid capability_level")
    if not isinstance(degraded, bool):
        raise InputError(f"benchmark manifest entry {entry_id} has invalid degraded flag")
    if not isinstance(raw_tags, list):
        raise InputError(f"benchmark manifest entry {entry_id} has invalid tags")
    raw_tag_items = cast("list[object]", raw_tags)
    if any(not isinstance(item, str) for item in raw_tag_items):
        raise InputError(f"benchmark manifest entry {entry_id} has invalid tags")
    entry_path = _safe_relative_path(raw_path)
    fixture_root = manifest_root / entry_path
    if not fixture_root.is_dir():
        raise InputError(f"benchmark fixture directory does not exist: {raw_path}")
    return BenchmarkEntry(
        entry_id=entry_id,
        kind=cast("BenchmarkEntryKind", kind),
        group=group,
        path=entry_path,
        capability_level=capability_level,
        degraded=degraded,
        language=language,
        tags=tuple(cast("list[str]", raw_tag_items)),
    )


def _safe_relative_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise InputError(f"benchmark fixture path must be relative and local: {raw_path}")
    return path


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InputError(f"benchmark manifest entry is missing {key}")
    return value


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"benchmark JSON file is invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise InputError(f"benchmark JSON file must contain an object: {path}")
    return cast("dict[str, Any]", payload)


def _load_jsonl_objects(path: Path) -> tuple[dict[str, Any], ...]:
    payloads: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise InputError(f"invalid JSONL line {index}: {path}") from exc
        if not isinstance(payload, dict):
            raise InputError(f"expected JSON object on line {index}: {path}")
        payloads.append(cast("dict[str, Any]", payload))
    return tuple(payloads)


def _materialize_eval_fixture(
    manifest_root: Path,
    entry: BenchmarkEntry,
    temp_root: Path,
) -> Path:
    fixture_root = manifest_root / entry.path
    patch_text = (fixture_root / "diff.patch").read_text(encoding="utf-8")
    concepts = _expected_concepts(fixture_root / "expected_concepts.json")
    qa_items = _load_jsonl_objects(fixture_root / "qa_probe.jsonl")
    run_path = temp_root / ".ahadiff" / "runs" / entry.entry_id
    run_path.mkdir(parents=True, exist_ok=True)
    metadata = {
        "run_id": entry.entry_id,
        "source_kind": "patch_file",
        "source_ref": f"benchmark:{entry.entry_id}",
        "capability_level": entry.capability_level,
        "degraded_flags": {"benchmark_degraded": entry.degraded} if entry.degraded else {},
        "learnability": {"score": 0.78 if entry.degraded else 0.92},
        "source_detail": {"benchmark_group": entry.group, "language": entry.language},
        "privacy_mode": "strict_local",
    }
    (run_path / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_path / "patch.diff").write_text(patch_text, encoding="utf-8")
    (run_path / "line_map.json").write_text(
        json.dumps(serialize_line_map_payload(build_line_map(patch_text)), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    claims = _claims_for_entry(entry=entry, concepts=concepts)
    (run_path / "claims.jsonl").write_text(
        "\n".join(json.dumps(claim.model_dump(mode="json"), ensure_ascii=False) for claim in claims)
        + "\n",
        encoding="utf-8",
    )
    _write_lesson_artifacts(run_path, entry=entry, concepts=concepts)
    _write_quiz_artifacts(run_path, entry=entry, claims=claims, qa_items=qa_items)
    return run_path


def _expected_concepts(path: Path) -> tuple[str, ...]:
    payload = _load_json_object(path)
    raw_concepts = payload.get("concepts")
    if not isinstance(raw_concepts, list) or not raw_concepts:
        raise InputError(f"expected_concepts.json must contain non-empty concepts: {path}")
    raw_concept_items = cast("list[object]", raw_concepts)
    concepts = [item for item in raw_concept_items if isinstance(item, str) and item]
    if not concepts:
        raise InputError(f"expected_concepts.json contains no usable concepts: {path}")
    return tuple(concepts)


def _claims_for_entry(
    *,
    entry: BenchmarkEntry,
    concepts: tuple[str, ...],
) -> tuple[ClaimRecord, ...]:
    return tuple(
        ClaimRecord(
            claim_id=f"{entry.entry_id}_claim_{index}",
            run_id=entry.entry_id,
            text=f"The fixture demonstrates {concept}.",
            status="verified" if not entry.degraded else "weak",
            confidence="high" if not entry.degraded else "medium",
            source_hunks=[SourceHunk(file="src/app.py", start=1, end=5, side="new")],
            symbols=[concept],
            extractor="python_ast" if entry.language == "python" else "regex",
        )
        for index, concept in enumerate(concepts, start=1)
    )


def _write_lesson_artifacts(
    run_path: Path,
    *,
    entry: BenchmarkEntry,
    concepts: tuple[str, ...],
) -> None:
    lesson_dir = run_path / "lesson"
    lesson_dir.mkdir()
    concept_text = ", ".join(concepts)
    (lesson_dir / "lesson.full.md").write_text(
        f"TL;DR\n\n{entry.entry_id} covers {concept_text}.\n\n"
        "What Changed\n\nThe patch adds a small deterministic behavior change.\n\n"
        "Why\n\nThe fixture anchors claims to changed lines.\n\n"
        "Walkthrough\n\nRead the added lines in src/app.py.\n\n"
        "Claims\n\nEach concept maps to one verified claim.\n\nSources\n\nsrc/app.py:1\n",
        encoding="utf-8",
    )
    (lesson_dir / "lesson.hint.md").write_text(
        f"Hint: focus on {concepts[0]} in src/app.py.\n",
        encoding="utf-8",
    )
    (lesson_dir / "lesson.compact.md").write_text(
        f"{entry.entry_id}: {concept_text}.\n",
        encoding="utf-8",
    )


def _write_quiz_artifacts(
    run_path: Path,
    *,
    entry: BenchmarkEntry,
    claims: tuple[ClaimRecord, ...],
    qa_items: tuple[dict[str, Any], ...],
) -> None:
    quiz_dir = run_path / "quiz"
    quiz_dir.mkdir()
    questions: list[dict[str, object]] = []
    for index in range(3):
        claim = claims[index % len(claims)]
        qa_item = qa_items[index % len(qa_items)] if qa_items else {}
        raw_question = qa_item.get("question")
        question = (
            raw_question if isinstance(raw_question, str) else f"What does {entry.entry_id} test?"
        )
        questions.append(
            {
                "question": question,
                "answer": qa_item.get("answer", "The fixture anchors behavior to changed lines."),
                "source_claims": [claim.claim_id],
                "evidence": [{"file": "src/app.py", "line": 2}],
                "concepts": list(claim.symbols or [entry.group]),
            }
        )
    (quiz_dir / "quiz.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in questions) + "\n",
        encoding="utf-8",
    )


def _claim_verification_rate(run_path: Path) -> float:
    records: list[dict[str, object]] = []
    for line in (run_path / "claims.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(cast("dict[str, object]", payload))
    if not records:
        return 0.0
    verified_count = sum(1 for item in records if item.get("status") in {"verified", "weak"})
    return round(verified_count / len(records), 4)


def _build_report(
    *,
    manifest: BenchmarkManifest,
    reports: tuple[ScoreReport, ...],
    all_entries: tuple[dict[str, object], ...],
    excluded_degraded_count: int,
    model_id: str,
    api_family_version: str,
    output_lang: str,
) -> BenchmarkReport:
    if not reports:
        raise InputError("benchmark suite has no comparable eval entries")
    dimensions = load_rubric().dimensions
    dimension_means: dict[str, float] = {}
    for dimension in dimensions:
        values = [
            item.score
            for report in reports
            for item in report.dimensions
            if item.name == dimension.name
        ]
        dimension_means[dimension.name] = round(sum(values) / len(values), 2) if values else 0.0
    claim_rates = [
        rate
        for entry in all_entries
        if entry.get("degraded") is False
        for rate in [_entry_claim_verification_rate(entry)]
        if rate is not None
    ]
    return BenchmarkReport(
        suite_id=manifest.suite_id,
        suite_digest=manifest.suite_digest,
        eval_bundle_version=compute_runtime_eval_bundle_version(),
        model_id=model_id,
        api_family_version=api_family_version,
        output_lang=output_lang,
        comparable_entry_count=len(reports),
        excluded_degraded_count=excluded_degraded_count,
        mean_score=round(sum(report.overall for report in reports) / len(reports), 2),
        claim_verification_rate=round(sum(claim_rates) / len(claim_rates), 4),
        dimension_means=dimension_means,
        entries=all_entries,
    )


def _entry_claim_verification_rate(entry: dict[str, object]) -> float | None:
    value = entry.get("claim_verification_rate")
    if isinstance(value, int | float):
        return float(value)
    return None


__all__ = [
    "BenchmarkEntry",
    "BenchmarkManifest",
    "BenchmarkReport",
    "compute_suite_digest",
    "load_benchmark_manifest",
    "run_benchmark_suite",
    "verify_suite_digest",
    "write_benchmark_report",
]
