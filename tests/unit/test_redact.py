from __future__ import annotations

import base64
import gzip
import json
import multiprocessing as mp
from typing import TYPE_CHECKING

from ahadiff.safety import redact as redact_module
from ahadiff.safety.audit import append_audit_record, build_redaction_audit_record
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline, scan_text_for_secrets

if TYPE_CHECKING:
    from pathlib import Path


def _base64_encode_layers(value: str, *, layers: int) -> str:
    encoded = value
    for _ in range(layers):
        encoded = base64.b64encode(encoded.encode("utf-8")).decode("ascii")
    return encoded


def _append_audit_record_in_subprocess(args: tuple[str, dict[str, object], int, int]) -> None:
    from pathlib import Path

    path_text, record, rotate_bytes, max_backups = args
    append_audit_record(
        Path(path_text),
        record,
        rotate_bytes=rotate_bytes,
        max_backups=max_backups,
    )


def test_redaction_pipeline_accepts_empty_diff() -> None:
    result = redaction_pipeline("", policy=AllowlistPolicy())

    assert result.redacted_text == ""
    assert result.findings == ()
    assert result.blocked_remote is False
    assert len(result.allowlist_digest) == 64


def test_redaction_pipeline_scans_raw_patch_and_resolved_snapshot() -> None:
    secret = "ghp_abcdefghijklmnopqrstuvwxyzABCDE"
    result = redaction_pipeline(
        'print("safe")\n',
        resolved_files={"src/secret.py": f'token = "{secret}"\n'},
        policy=AllowlistPolicy(),
    )

    assert result.primary_target.redacted_text == 'print("safe")\n'
    assert any(
        finding.source_kind == "resolved_file" and finding.rule_id == "GITHUB_TOKEN"
        for finding in result.findings
    )
    assert result.blocked_remote is True


def test_redaction_pipeline_redacts_branch_and_tag_names() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    result = redaction_pipeline(
        "diff --git a/a.py b/a.py\n",
        branch_names=(f"feature/{secret}",),
        tag_names=(f"release-{secret}",),
        policy=AllowlistPolicy(),
    )

    kinds = {finding.source_kind for finding in result.findings}
    assert {"branch_name", "tag_name"} <= kinds


def test_redaction_pipeline_detects_base64_wrapped_secret() -> None:
    encoded = base64.b64encode(b"sk-abcdefghijklmnopqrstuvwxyz123456").decode("ascii")
    result = redaction_pipeline(f'API_KEY = "{encoded}"', policy=AllowlistPolicy())

    assert any(finding.rule_id == "BASE64_WRAPPED_SECRET" for finding in result.findings)
    assert "[REDACTED:base64_wrapped_secret]" in result.redacted_text


def test_redaction_pipeline_detects_multiline_split_github_token() -> None:
    result = redaction_pipeline(
        'token = "ghp_abcdefghijklmno\npqrstuvwxyzABCDE"\n',
        policy=AllowlistPolicy(),
    )

    github_findings = [finding for finding in result.findings if finding.rule_id == "GITHUB_TOKEN"]
    assert len(github_findings) == 1
    assert github_findings[0].line == 1
    assert result.blocked_remote is True
    assert "[REDACTED:github_token]" in result.redacted_text
    assert "ghp_abcdefghijklmno" not in result.redacted_text
    assert "pqrstuvwxyzABCDE" not in result.redacted_text
    assert result.redacted_text.count("\n") == 2


def test_base64_wrapped_hard_block_secrets_do_not_bypass_with_entropy_suppression() -> None:
    jwt_like = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4iLCJpYXQiOjE1MTYyMzkwMjJ9."
        "c2lnbmF0dXJlLXBsYWNlaG9sZGVy"
    )
    db_url = "postgres://user:pass@example.com/db"
    slack = "https://hooks.slack.com/services/T000/B000/XXXXXXXXXXXXXXXX"

    for raw_secret in (jwt_like, db_url, slack):
        encoded = base64.b64encode(raw_secret.encode("utf-8")).decode("ascii")
        result = redaction_pipeline(
            f'token = "{encoded}"',
            policy=AllowlistPolicy(suppress_rules=("HIGH_ENTROPY_STRING",)),
        )

        assert result.blocked_remote is True
        assert encoded not in result.redacted_text
        assert any(finding.severity == "hard_block" for finding in result.findings)


def test_recursive_base64_wrapped_hard_block_secrets_still_block_when_entropy_is_suppressed() -> (
    None
):
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"

    for layers in (2, 3):
        encoded = _base64_encode_layers(secret, layers=layers)
        result = redaction_pipeline(
            f'API_KEY = "{encoded}"',
            policy=AllowlistPolicy(suppress_rules=("HIGH_ENTROPY_STRING",)),
        )

        assert result.blocked_remote is True
        assert any(finding.rule_id == "BASE64_WRAPPED_SECRET" for finding in result.findings)
        assert encoded not in result.redacted_text
        assert "[REDACTED:base64_wrapped_secret]" in result.redacted_text


def test_high_entropy_secondary_scan_skips_uuid_and_hashes() -> None:
    payload = "\n".join(
        (
            "id = 550e8400-e29b-41d4-a716-446655440000",
            "sha = da39a3ee5e6b4b0d3255bfef95601890afd80709",
        )
    )

    findings = scan_text_for_secrets(payload, policy=AllowlistPolicy())
    assert all(finding.rule_id != "HIGH_ENTROPY_STRING" for finding in findings)


def test_high_entropy_exemptions_cover_bundle_and_sourcemap_fragments() -> None:
    assert redact_module._is_high_entropy_exempt(  # pyright: ignore[reportPrivateUsage]
        "__webpack_require__sourceMappingURL"
    )
    assert redact_module._is_high_entropy_exempt(  # pyright: ignore[reportPrivateUsage]
        "AAAACAACEAAEGAAGIAAI"
    )


def test_audit_record_rotates_when_size_threshold_is_exceeded(tmp_path: Path) -> None:
    result = redaction_pipeline(
        'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"',
        policy=AllowlistPolicy(),
    )
    record = build_redaction_audit_record(result, privacy_mode="redacted_remote")
    audit_path = tmp_path / "audit.jsonl"

    append_audit_record(audit_path, record, rotate_bytes=1, max_backups=1)
    append_audit_record(audit_path, record, rotate_bytes=1, max_backups=1)

    assert audit_path.exists()
    assert (tmp_path / "audit.1.jsonl.gz").exists()
    assert not (tmp_path / "audit.jsonl.rotation-src").exists()


def test_audit_record_rotation_is_stable_under_multiprocess_contention(tmp_path: Path) -> None:
    result = redaction_pipeline(
        'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"',
        policy=AllowlistPolicy(),
    )
    base_record = build_redaction_audit_record(result, privacy_mode="redacted_remote")
    audit_path = tmp_path / "audit.jsonl"
    process_count = 8
    max_backups = process_count + 1
    ctx = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")

    records: list[tuple[str, dict[str, object], int, int]] = []
    for index in range(process_count):
        record: dict[str, object] = dict(base_record)
        record["event_id"] = f"evt-{index}"
        records.append((str(audit_path), record, 1, max_backups))

    with ctx.Pool(process_count) as pool:
        pool.map(_append_audit_record_in_subprocess, records)

    event_ids: set[str] = set()
    if audit_path.exists():
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                event_ids.add(json.loads(line)["event_id"])
    for rotated_path in tmp_path.glob("audit.*.jsonl.gz"):
        with gzip.open(rotated_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    event_ids.add(json.loads(line)["event_id"])

    assert len(event_ids) == process_count
    assert not (tmp_path / "audit.jsonl.rotation-src").exists()
