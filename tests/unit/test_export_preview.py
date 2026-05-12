from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

from ahadiff.core.errors import InputError
from ahadiff.export.preview import (
    ExportManifest,
    build_zip_bytes,
    export_preview,
)
from ahadiff.export.writer import ensure_output_contained, safe_write_export_file
from ahadiff.serve import ServeState, create_app

_AUTH = {"X-AhaDiff-Token": "test-token", "origin": "http://localhost:8765"}


def _write_finalized_run(
    state_dir: Path,
    run_id: str,
    *,
    lesson_text: str | None = None,
) -> Path:
    run_dir = state_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "finalized.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "keep",
                "verdict": "PASS",
                "overall": 80.0,
                "finalized_at": "2026-05-12T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "head_ref": "abc123",
                "base_ref": "def456",
                "content_lang": "en",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "score.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "overall": 80.0,
                "rubric_version": "v0.2",
                "verdict": "PASS",
            }
        ),
        encoding="utf-8",
    )
    lesson_dir = run_dir / "lesson"
    lesson_dir.mkdir()
    (lesson_dir / "lesson.full.md").write_text(
        lesson_text or "# Lesson\n\nLearned about export.",
        encoding="utf-8",
    )
    quiz_dir = run_dir / "quiz"
    quiz_dir.mkdir()
    (quiz_dir / "quiz.jsonl").write_text(
        json.dumps({"id": "q1", "question": "What is exported?"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "claims.jsonl").write_text(
        json.dumps({"id": "c1", "text": "Export creates manifest"}) + "\n",
        encoding="utf-8",
    )
    return run_dir


def _concepts_jsonl(state_dir: Path, run_id: str) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "concepts.jsonl").write_text(
        json.dumps(
            {
                "concept": "export",
                "term": "export",
                "term_key": "export",
                "display_name": "Export",
                "introduced_by_run": run_id,
                "updated_by_runs": [run_id],
            }
        )
        + "\n"
        + json.dumps(
            {
                "concept": "other",
                "term": "other",
                "term_key": "other",
                "display_name": "Other",
                "introduced_by_run": "run_other",
                "updated_by_runs": ["run_other"],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_export_engine_generates_manifest_and_data(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_basic_export"
    _write_finalized_run(state_dir, run_id)
    _concepts_jsonl(state_dir, run_id)

    output_dir = tmp_path / "preview"
    manifest = export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
        privacy_mode="strict_local",
    )

    assert isinstance(manifest, ExportManifest)
    assert manifest.run_id == run_id
    assert manifest.privacy_mode == "strict_local"
    assert manifest.file_count == 4
    assert manifest.total_bytes > 0
    assert (output_dir / "manifest.json").is_file()
    assert (output_dir / "README.txt").is_file()
    assert (output_dir / "index.html").is_file()
    assert (output_dir / "data" / "run.json").is_file()
    assert (output_dir / "data" / "concepts.json").is_file()

    payload = json.loads((output_dir / "data" / "run.json").read_text("utf-8"))
    assert payload["finalized"]["run_id"] == run_id
    assert payload["lessons"]["lesson_full"].startswith("# Lesson")

    concepts_payload = json.loads((output_dir / "data" / "concepts.json").read_text("utf-8"))
    concept_terms = {entry["term"] for entry in concepts_payload["concepts"]}
    assert "export" in concept_terms
    assert "other" not in concept_terms


def test_manifest_digest_excludes_manifest_and_validates(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_digest"
    _write_finalized_run(state_dir, run_id)

    output_dir = tmp_path / "preview"
    manifest = export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )

    manifest_payload = json.loads((output_dir / "manifest.json").read_text("utf-8"))
    file_entries = manifest_payload["files"]
    paths = {entry["path"] for entry in file_entries}
    assert "manifest.json" not in paths

    expected_hasher = hashlib.sha256()
    for entry in sorted(file_entries, key=lambda item: item["path"]):
        expected_hasher.update(
            f"{entry['path']}\x00{entry['sha256']}\x00{entry['size']}\n".encode()
        )
    assert manifest_payload["digest"] == expected_hasher.hexdigest()
    assert manifest.digest == manifest_payload["digest"]


def test_export_rejects_missing_run(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    with pytest.raises(InputError, match="run not found"):
        export_preview(
            run_id="run_missing",
            output_path=tmp_path / "preview",
            state_dir=state_dir,
        )


def test_export_rejects_non_finalized_run(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_dir = state_dir / "runs" / "run_pending"
    run_dir.mkdir(parents=True)
    with pytest.raises(InputError, match="not finalized"):
        export_preview(
            run_id="run_pending",
            output_path=tmp_path / "preview",
            state_dir=state_dir,
        )


def test_export_rejects_invalid_privacy_mode(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_mode"
    _write_finalized_run(state_dir, run_id)
    with pytest.raises(InputError, match="privacy_mode"):
        export_preview(
            run_id=run_id,
            output_path=tmp_path / "preview",
            state_dir=state_dir,
            privacy_mode="public",
        )


def test_export_redacts_secrets_in_strict_local(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_secret"
    _write_finalized_run(
        state_dir,
        run_id,
        lesson_text="See OPENAI_API_KEY=sk-livefake1234567890abcdEF1234567890abcdEF",
    )
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
        privacy_mode="strict_local",
    )
    rendered = (output_dir / "data" / "run.json").read_text("utf-8")
    assert "sk-livefake1234567890abcdEF1234567890abcdEF" not in rendered


def test_safe_write_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "preview"
    root.mkdir()
    with pytest.raises(InputError, match="'\\.\\.'"):
        safe_write_export_file(root, "../escape.txt", b"x")
    with pytest.raises(InputError, match="absolute"):
        safe_write_export_file(root, "/abs.txt", b"x")
    with pytest.raises(InputError, match="empty"):
        safe_write_export_file(root, "", b"x")


def test_safe_write_rejects_windows_reserved_names(tmp_path: Path) -> None:
    root = tmp_path / "preview"
    root.mkdir()
    for reserved in ("CON.txt", "AUX", "NUL", "COM1", "LPT9"):
        with pytest.raises(InputError, match="reserved device name"):
            safe_write_export_file(root, reserved, b"x")


def test_safe_write_rejects_trailing_dot_or_space(tmp_path: Path) -> None:
    root = tmp_path / "preview"
    root.mkdir()
    with pytest.raises(InputError, match="end with"):
        safe_write_export_file(root, "name.", b"x")
    with pytest.raises(InputError, match="end with"):
        safe_write_export_file(root, "name ", b"x")


def test_safe_write_rejects_ads_colon(tmp_path: Path) -> None:
    root = tmp_path / "preview"
    root.mkdir()
    with pytest.raises(InputError, match="':'"):
        safe_write_export_file(root, "name:stream", b"x")


def test_ensure_output_contained_blocks_escape(tmp_path: Path) -> None:
    root = tmp_path / "preview"
    root.mkdir()
    with pytest.raises(InputError, match="escapes output root"):
        ensure_output_contained(root, root.parent / "outside.txt")


def test_zip_is_deterministic_across_tz(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_zip"
    _write_finalized_run(state_dir, run_id)
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )

    saved_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "UTC"
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()
        zip_utc = build_zip_bytes(output_dir)
        os.environ["TZ"] = "America/Los_Angeles"
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()
        zip_pst = build_zip_bytes(output_dir)
    finally:
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()

    assert hashlib.sha256(zip_utc).hexdigest() == hashlib.sha256(zip_pst).hexdigest()

    with zipfile.ZipFile(io.BytesIO(zip_utc)) as zf:
        for info in zf.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)


def test_no_raw_audit_or_keys_leaked(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_priv"
    run_dir = _write_finalized_run(state_dir, run_id)
    (run_dir / "claims.raw.jsonl").write_text(
        json.dumps({"raw_prompt": "API_KEY=zzz"}) + "\n",
        encoding="utf-8",
    )
    (state_dir / "audit.private.jsonl").write_text("private\n", encoding="utf-8")

    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )

    payload = json.loads((output_dir / "data" / "run.json").read_text("utf-8"))
    assert "claims_raw" not in payload
    rendered = (output_dir / "data" / "run.json").read_text("utf-8")
    assert "claims.raw" not in rendered
    assert "audit.private" not in rendered


def test_route_returns_manifest_payload(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_route_test"
    _write_finalized_run(state_dir, run_id)

    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.post(
        "/api/export/preview",
        headers=_AUTH,
        json={"run_id": run_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["privacy_mode"] == "strict_local"
    assert body["file_count"] == 4
    assert len(body["manifest_digest"]) == 64
    assert body["path"] == f"exports/{run_id}"
    assert str(tmp_path) not in body["path"]

    audit_text = (state_dir / "audit.jsonl").read_text(encoding="utf-8")
    audit_records = [json.loads(line) for line in audit_text.splitlines() if line.strip()]
    matched = [rec for rec in audit_records if rec.get("event_type") == "export.preview"]
    assert matched
    assert matched[-1]["run_id"] == run_id
    assert matched[-1]["digest"] == body["manifest_digest"]


def test_route_rejects_missing_run_id(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.post("/api/export/preview", headers=_AUTH, json={})
    assert response.status_code == 422
    assert response.json()["error_code"] == "INPUT_VALIDATION"


def test_route_rejects_unknown_run(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.post(
        "/api/export/preview",
        headers=_AUTH,
        json={"run_id": "run_does_not_exist"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "RUN_NOT_FOUND"


def test_route_requires_write_token(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    state_dir.mkdir()
    client = TestClient(
        create_app(ServeState(state_dir=state_dir, token="test-token")),
        base_url="http://localhost:8765",
    )
    response = client.post(
        "/api/export/preview",
        json={"run_id": "run_x"},
    )
    assert response.status_code in {401, 403}


def _supports_symlinks(tmp_path: Path) -> bool:
    target = tmp_path / "_probe_target"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "_probe_link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    finally:
        if link.exists() or link.is_symlink():
            link.unlink()
        target.unlink()
    return True


def test_export_rejects_symlinked_finalized_json(tmp_path: Path) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlinks unsupported on this platform")
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_symlink_finalized"
    run_dir = _write_finalized_run(state_dir, run_id)
    real = run_dir / "finalized.real.json"
    target = run_dir / "finalized.json"
    target.rename(real)
    target.symlink_to(real)

    with pytest.raises(InputError, match="symlink"):
        export_preview(
            run_id=run_id,
            output_path=tmp_path / "preview",
            state_dir=state_dir,
        )


def test_export_rejects_symlinked_jsonl_artifact(tmp_path: Path) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlinks unsupported on this platform")
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_symlink_quiz"
    run_dir = _write_finalized_run(state_dir, run_id)
    real = run_dir / "quiz" / "quiz.real.jsonl"
    target = run_dir / "quiz" / "quiz.jsonl"
    target.rename(real)
    target.symlink_to(real)

    with pytest.raises(InputError, match="symlink"):
        export_preview(
            run_id=run_id,
            output_path=tmp_path / "preview",
            state_dir=state_dir,
        )


def test_export_rejects_fifo_artifact(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("mkfifo unsupported on this platform")
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_test_fifo"
    run_dir = _write_finalized_run(state_dir, run_id)
    target = run_dir / "claims.jsonl"
    target.unlink()
    os.mkfifo(str(target))

    with pytest.raises(InputError, match="regular file"):
        export_preview(
            run_id=run_id,
            output_path=tmp_path / "preview",
            state_dir=state_dir,
        )


def test_zip_only_includes_manifest_listed_files(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_zip_whitelist"
    _write_finalized_run(state_dir, run_id)
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )

    # Drop a stray file into the output directory and a nested location.  The
    # zip must not include either because manifest.files does not list them.
    (output_dir / "stowaway.txt").write_bytes(b"sneaky")
    (output_dir / "data").mkdir(exist_ok=True)
    (output_dir / "data" / "extra.json").write_bytes(b"{}")

    archive_bytes = build_zip_bytes(output_dir)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = sorted(zf.namelist())
    assert "stowaway.txt" not in names
    assert "data/extra.json" not in names
    # manifest + 4 declared files
    assert "manifest.json" in names
    assert "README.txt" in names
    assert "index.html" in names
    assert "data/run.json" in names
    assert "data/concepts.json" in names
    assert len(names) == 5


def test_zip_rejects_symlinked_listed_file(tmp_path: Path) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlinks unsupported on this platform")
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_zip_symlink_swap"
    _write_finalized_run(state_dir, run_id)
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )

    # Replace a listed file with a symlink pointing outside the output root.
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"leaked")
    listed = output_dir / "README.txt"
    listed.unlink()
    listed.symlink_to(outside)

    with pytest.raises(InputError, match="symlink"):
        build_zip_bytes(output_dir)


def test_zip_rejects_digest_mismatch_after_export(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_zip_toctou"
    _write_finalized_run(state_dir, run_id)
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )

    # Tamper with a listed file's content (preserving size) so manifest digest
    # no longer matches what we read off disk.
    listed = output_dir / "data" / "run.json"
    original = listed.read_bytes()
    tampered = bytearray(original)
    # Flip a stable byte without changing length.
    tampered[0] = (tampered[0] + 1) % 256
    listed.write_bytes(bytes(tampered))

    with pytest.raises(InputError, match="digest mismatch"):
        build_zip_bytes(output_dir)


def test_zip_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_zip_traversal"
    _write_finalized_run(state_dir, run_id)
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )
    outside = tmp_path / "outside-secret.txt"
    outside.write_bytes(b"secret")
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["files"] = [
        {
            "path": "../outside-secret.txt",
            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            "size": outside.stat().st_size,
        }
    ]
    manifest["digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InputError, match=r"\.\."):
        build_zip_bytes(output_dir)


def test_export_rejects_symlinked_output_root(tmp_path: Path) -> None:
    if not _supports_symlinks(tmp_path):
        pytest.skip("symlinks unsupported on this platform")
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_symlink_output"
    _write_finalized_run(state_dir, run_id)
    outside_dir = tmp_path / "outside-preview"
    outside_dir.mkdir()
    output_link = tmp_path / "preview-link"
    output_link.symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        export_preview(
            run_id=run_id,
            output_path=output_link,
            state_dir=state_dir,
        )


def test_zip_rejects_missing_manifest(tmp_path: Path) -> None:
    state_dir = tmp_path / ".ahadiff"
    run_id = "run_zip_no_manifest"
    _write_finalized_run(state_dir, run_id)
    output_dir = tmp_path / "preview"
    export_preview(
        run_id=run_id,
        output_path=output_dir,
        state_dir=state_dir,
    )
    (output_dir / "manifest.json").unlink()

    with pytest.raises(InputError, match="manifest"):
        build_zip_bytes(output_dir)
