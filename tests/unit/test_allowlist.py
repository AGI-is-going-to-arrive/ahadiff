from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from ahadiff.core.config import load_config, load_security_config, resolve_effective
from ahadiff.core.errors import ConfigError, SafetyError
from ahadiff.safety.gates import assert_no_unredacted_secret, enforce_privacy_mode
from ahadiff.safety.ignore import AllowlistPolicy, compute_allowlist_digest, load_allowlist_policy
from ahadiff.safety.redact import redaction_pipeline, scan_text_for_secrets

if TYPE_CHECKING:
    from pathlib import Path


def _init_git_repo(root: Path) -> None:
    (root / ".git").mkdir()


def test_load_config_accepts_security_arrays_without_marking_them_unknown(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    (repo_root / ".ahadiff" / "config.toml").write_text(
        '[security]\nallow_paths = ["tests/fixtures/**"]\nallow_exact = ["abc"]\n'
        'suppress_rules = ["HIGH_ENTROPY_STRING"]\n',
        encoding="utf-8",
    )

    snapshot = load_config(repo_root, env={"HOME": str(tmp_path / "home")})
    security = load_security_config(repo_root)

    assert snapshot.repo_unknown_keys == ()
    assert resolve_effective("security.allow_paths", snapshot=snapshot).value == (
        "tests/fixtures/**",
    )
    assert security.suppress_rules == ("HIGH_ENTROPY_STRING",)


def test_invalid_privacy_mode_is_rejected_by_config_loader(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    (repo_root / ".ahadiff").mkdir()
    (repo_root / ".ahadiff" / "config.toml").write_text(
        'privacy_mode = "totally_remote"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="privacy_mode must be one of"):
        load_config(repo_root, env={"HOME": str(tmp_path / "home")})


def test_soft_detect_can_be_allowlisted_by_hash_and_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    token = "AbC123xYz789LmNoPqRsTuVwXyZaBcDeFgHiJk45"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    (repo_root / ".ahadiff").mkdir()
    (repo_root / ".ahadiff" / "config.toml").write_text(
        f'[security]\nallow_exact = ["sha256:{token_hash}"]\nallow_paths = ["tests/fixtures/**"]\n',
        encoding="utf-8",
    )

    policy = load_allowlist_policy(repo_root)
    findings = scan_text_for_secrets(
        token,
        source_name="tests/fixtures/sample.txt",
        source_kind="resolved_file",
        path="tests/fixtures/sample.txt",
        policy=policy,
    )

    assert len(findings) == 1
    assert findings[0].rule_id == "HIGH_ENTROPY_STRING"
    assert findings[0].allowlisted is True
    assert len(compute_allowlist_digest(policy)) == 64


def test_hard_block_cannot_be_suppressed_and_privacy_gates_enforce_redaction(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _init_git_repo(repo_root)
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    (repo_root / ".ahadiff").mkdir()
    (repo_root / ".ahadiff" / "config.toml").write_text(
        f'[security]\nsuppress_rules = ["OPENAI_API_KEY"]\nallow_exact = ["{secret}"]\n',
        encoding="utf-8",
    )

    result = redaction_pipeline(f'OPENAI_API_KEY="{secret}"', repo_root=repo_root)

    assert result.blocked_remote is True
    assert any(
        finding.rule_id == "OPENAI_API_KEY" and finding.allowlisted is False
        for finding in result.findings
    )
    assert_no_unredacted_secret(result.redacted_text, result.findings)

    with pytest.raises(SafetyError, match="strict_local mode forbids remote transport"):
        enforce_privacy_mode(
            "strict_local",
            target="remote",
            text=result.redacted_text,
            findings=result.findings,
            is_redacted=True,
        )

    enforce_privacy_mode(
        "redacted_remote",
        target="remote",
        text=result.redacted_text,
        findings=result.findings,
        is_redacted=True,
    )

    with pytest.raises(SafetyError, match="unsupported transport target"):
        enforce_privacy_mode(
            "explicit_remote",
            target="bogus",  # pyright: ignore[reportArgumentType]
            text=result.redacted_text,
            findings=result.findings,
            is_redacted=True,
        )


def test_allowlist_digest_is_stable_across_rule_order() -> None:
    left = compute_allowlist_digest(
        AllowlistPolicy(
            allow_exact=("a", "b"),
            allow_paths=("tests/fixtures/**", "src/**"),
            suppress_rules=("HIGH_ENTROPY_STRING", "RULE2"),
        )
    )
    right = compute_allowlist_digest(
        AllowlistPolicy(
            allow_exact=("b", "a"),
            allow_paths=("src/**", "tests/fixtures/**"),
            suppress_rules=("RULE2", "HIGH_ENTROPY_STRING"),
        )
    )

    assert left == right
