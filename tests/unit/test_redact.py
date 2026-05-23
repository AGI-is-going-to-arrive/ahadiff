from __future__ import annotations

import base64
import gzip
import json
import multiprocessing as mp
from typing import TYPE_CHECKING, Any

import pytest

from ahadiff.git.parser import parse_unified_diff
from ahadiff.safety import audit as audit_module
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


def test_redaction_pipeline_preserves_diff_prefix_for_leading_entropy_tokens() -> None:
    patch = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,2 +1,2 @@\n"
        "-UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \\\n"
        "+UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest \\\n"
        " keep\n"
    )

    result = redaction_pipeline(patch, policy=AllowlistPolicy())

    assert "-[REDACTED:high_entropy_string] uv run pytest \\" in result.redacted_text
    assert "+[REDACTED:high_entropy_string] uv run pytest \\" in result.redacted_text
    parse_unified_diff(result.redacted_text)


def test_redaction_pipeline_redacts_line_start_entropy_outside_diff() -> None:
    token = "UV_CACHE_DIR=/tmp/ahadiff-uv-cache"

    result = redaction_pipeline(f"+{token}\n-{token}\n", policy=AllowlistPolicy())

    assert result.redacted_text == (
        "+[REDACTED:high_entropy_string]\n-[REDACTED:high_entropy_string]\n"
    )
    assert token not in result.redacted_text


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


@pytest.mark.parametrize(
    "query",
    (
        "access_token=secret123",
        "refresh_token=secret123",
        "id_token=secret123",
        "client_secret=secret123",
        "auth_token=secret123",
        "bearer_token=secret123",
        "api_secret=secret123",
        "app_secret=secret123",
        "oauth_token=secret123",
        "oauth-token=secret123",
        "oauth_token_secret=secret123",
        "OAUTH_TOKEN_SECRET=secret123",
        "access-token=secret123",
        "CLIENT_SECRET=secret123",
    ),
)
def test_url_embedded_secret_redacts_oauth_query_names(query: str) -> None:
    url = f"https://api.example.test/callback?{query}&state=ok"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_EMBEDDED_SECRET" in {finding.rule_id for finding in result.findings}
    assert "[REDACTED:url_embedded_secret]" in result.redacted_text
    assert "secret123" not in result.redacted_text


@pytest.mark.parametrize(
    "query",
    (
        "api_key=secret123",
        "secret=secret123",
        "password=secret123",
        "token=secret123",
        "credential=secret123",
        "auth=secret123",
    ),
)
def test_url_embedded_secret_still_redacts_existing_query_names(query: str) -> None:
    url = f"https://api.example.test/v1?safe=1&{query}"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_EMBEDDED_SECRET" in {finding.rule_id for finding in result.findings}
    assert "secret123" not in result.redacted_text


def test_url_embedded_secret_does_not_match_partial_query_names() -> None:
    url = "https://api.example.test/v1?xaccess_token=secret123&safe=1"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_EMBEDDED_SECRET" not in {finding.rule_id for finding in result.findings}


@pytest.mark.parametrize(
    "fragment",
    (
        "access_token=secret123",
        "id_token=secret123",
        "refresh_token=secret123",
        "oauth_token=secret123",
        "oauth_token_secret=secret123",
    ),
)
def test_url_embedded_secret_redacts_fragment_tokens(fragment: str) -> None:
    url = f"https://api.example.test/callback#{fragment}&state=ok"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_EMBEDDED_SECRET" in {finding.rule_id for finding in result.findings}
    assert "secret123" not in result.redacted_text


def test_url_embedded_secret_does_not_match_partial_fragment_names() -> None:
    url = "https://api.example.test/callback#xaccess_token=secret123&state=ok"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_EMBEDDED_SECRET" not in {finding.rule_id for finding in result.findings}


def test_url_userinfo_secret_redaction_is_unchanged() -> None:
    url = "https://user:secret123@api.example.test/v1?safe=1"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_USERINFO_SECRET" in {finding.rule_id for finding in result.findings}
    assert "[REDACTED:url_userinfo_secret]" in result.redacted_text
    assert "secret123" not in result.redacted_text


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


def test_audit_rotation_copies_snapshot_without_path_open(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    audit_path = tmp_path / "audit.jsonl"
    audit_path.write_text('{"event_id":"old"}\n', encoding="utf-8")

    def fail_path_open(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("rotation source must be copied through fd-based open")

    monkeypatch.setattr(audit_module.Path, "open", fail_path_open)

    append_audit_record(
        audit_path,
        {"event_id": "new"},
        rotate_bytes=1,
        max_backups=1,
    )

    monkeypatch.undo()
    with gzip.open(tmp_path / "audit.1.jsonl.gz", "rt", encoding="utf-8") as handle:
        assert handle.read() == '{"event_id":"old"}\n'
    assert '"event_id": "new"' in audit_path.read_text(encoding="utf-8")


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


def test_audit_gzip_copy_uses_chunked_read(tmp_path: Path, monkeypatch: Any) -> None:
    audit_path = tmp_path / "audit.jsonl"
    content = '{"event_id":"test"}\n' * 100
    audit_path.write_text(content, encoding="utf-8")

    append_audit_record(audit_path, {"event_id": "new"}, rotate_bytes=1, max_backups=1)

    rotated = tmp_path / "audit.1.jsonl.gz"
    assert rotated.exists()
    with gzip.open(rotated, "rt", encoding="utf-8") as handle:
        assert handle.read() == content


def test_audit_lock_rejects_symlink_swap_during_acquire(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import os
    from pathlib import Path

    import pytest

    from ahadiff.core.errors import InputError

    if not hasattr(os, "symlink") or not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("requires POSIX symlink no-follow support")

    audit_path = tmp_path / "audit.jsonl"
    lock_path = tmp_path / "audit.jsonl.lock"
    outside_lock = tmp_path / "outside.lock"
    outside_lock.write_text("outside\n", encoding="utf-8")
    original_open = audit_module.os.open
    swapped = False

    def swapping_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if Path(path) == lock_path and not swapped:
            swapped = True
            audit_module.os.symlink(outside_lock, lock_path)
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(audit_module.os, "open", swapping_open)

    with pytest.raises(InputError, match="symlink"):
        append_audit_record(audit_path, {"event_id": "evt-swap"})

    assert swapped is True
    assert outside_lock.read_text(encoding="utf-8") == "outside\n"


def test_ensure_state_parent_dir_creates_directory(tmp_path: Path) -> None:
    from ahadiff.core.paths import ensure_state_parent_dir

    deep_path = tmp_path / "a" / "b" / "c" / "file.txt"
    result = ensure_state_parent_dir(deep_path)
    assert result == deep_path.parent
    assert deep_path.parent.is_dir()


def test_ensure_state_parent_dir_rejects_symlink_parent(tmp_path: Path) -> None:
    import os
    import sys

    if sys.platform.startswith("win"):
        import pytest

        pytest.skip("symlink test requires Unix")

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "link"
    os.symlink(str(real_dir), str(link))

    import pytest

    from ahadiff.core.errors import InputError
    from ahadiff.core.paths import ensure_state_parent_dir

    with pytest.raises(InputError, match="symlinks"):
        ensure_state_parent_dir(link / "file.txt")


def test_validate_state_path_rejects_intermediate_symlink(tmp_path: Path) -> None:
    import os
    import sys

    if sys.platform.startswith("win"):
        import pytest

        pytest.skip("symlink test requires Unix")

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "child").mkdir()
    link = tmp_path / "link"
    os.symlink(str(real_dir), str(link))

    import pytest

    from ahadiff.core.errors import InputError
    from ahadiff.core.paths import validate_state_path_no_symlinks

    with pytest.raises(InputError, match="symlinks"):
        validate_state_path_no_symlinks(link / "child", allow_missing_leaf=False)


def test_open_state_file_rejects_symlink_target(tmp_path: Path) -> None:
    import os
    import sys

    if sys.platform.startswith("win"):
        import pytest

        pytest.skip("symlink test requires Unix")

    real_file = tmp_path / "real.txt"
    real_file.write_text("data", encoding="utf-8")
    link = tmp_path / "link.txt"
    os.symlink(str(real_file), str(link))

    import pytest

    from ahadiff.core.errors import InputError
    from ahadiff.safety.audit import (
        _open_state_file_no_follow,  # pyright: ignore[reportPrivateUsage]
    )

    with pytest.raises(InputError, match="symlinks"):
        _open_state_file_no_follow(link, os.O_RDONLY)


def test_touch_no_follow_creates_file(tmp_path: Path) -> None:
    from ahadiff.safety.audit import _touch_no_follow  # pyright: ignore[reportPrivateUsage]

    target = tmp_path / "touched.txt"
    assert not target.exists()
    _touch_no_follow(target)
    assert target.exists()
