from __future__ import annotations

import pytest

from ahadiff.safety.ignore import AllowlistPolicy
from ahadiff.safety.redact import redaction_pipeline, scan_text_for_secrets


def _rule_ids(text: str) -> set[str]:
    return {finding.rule_id for finding in scan_text_for_secrets(text, policy=AllowlistPolicy())}


def test_url_embedded_secret_is_detected_and_redacted() -> None:
    url = "https://api.example.com/v1?api_key=sk-secret123"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert any(
        finding.rule_id == "URL_EMBEDDED_SECRET"
        and finding.secret_type == "url_embedded_secret"
        and finding.severity == "hard_block"
        for finding in result.findings
    )
    assert "[REDACTED:url_embedded_secret]" in result.redacted_text
    assert url not in result.redacted_text


@pytest.mark.parametrize(
    "query",
    (
        "token=tok123",
        "password=p4ssword",
        "secret=hidden123",
        "credential=cred123",
        "auth=bearer123",
        "api-key=key123",
        "api_key=key123",
        "safe=1&token=tok123",
    ),
)
def test_url_embedded_secret_query_variants_are_detected(query: str) -> None:
    url = f"https://api.example.com/v1?{query}"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert "URL_EMBEDDED_SECRET" in {finding.rule_id for finding in result.findings}
    assert "[REDACTED:url_embedded_secret]" in result.redacted_text
    assert url not in result.redacted_text


def test_url_userinfo_secret_is_detected_and_redacted() -> None:
    url = "https://user:pass@host.com/path"

    result = redaction_pipeline(url, policy=AllowlistPolicy())

    assert any(
        finding.rule_id == "URL_USERINFO_SECRET"
        and finding.secret_type == "url_userinfo_secret"
        and finding.severity == "hard_block"
        for finding in result.findings
    )
    assert "[REDACTED:url_userinfo_secret]" in result.redacted_text
    assert url not in result.redacted_text


@pytest.mark.parametrize(
    "query",
    (
        "API_KEY=secret",
        "Token=abc123",
        "SECRET=xyz",
        "Auth=bearer",
        "PASSWORD=p4ss",
    ),
)
def test_url_embedded_secret_case_insensitive(query: str) -> None:
    url = f"https://api.example.com/v1?{query}"
    assert "URL_EMBEDDED_SECRET" in _rule_ids(url)


@pytest.mark.parametrize(
    "url",
    (
        "https://example.com/token/path",
        "https://example.com/api/v1",
        "https://example.com/auth/callback",
    ),
)
def test_benign_urls_are_not_flagged_by_url_secret_rules(url: str) -> None:
    rule_ids = _rule_ids(url)

    assert "URL_EMBEDDED_SECRET" not in rule_ids
    assert "URL_USERINFO_SECRET" not in rule_ids
