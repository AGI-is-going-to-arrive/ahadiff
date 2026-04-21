from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from ahadiff.safety import redact as redact_module
from ahadiff.safety.audit import append_audit_record, build_redaction_audit_record
from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline, scan_text_for_secrets

if TYPE_CHECKING:
    from pathlib import Path


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
