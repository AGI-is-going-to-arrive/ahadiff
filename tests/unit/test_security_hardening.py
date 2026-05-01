"""Phase 7B security hardening tests: SSRF, output guard, entropy edge cases."""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address
from typing import Any

import httpx
import pytest

from ahadiff.contracts import ProviderConfig
from ahadiff.core.errors import SafetyError
from ahadiff.llm import ProviderRequest, make_provider
from ahadiff.llm import provider as provider_module
from ahadiff.llm.provider import (
    _is_non_public_ip,  # pyright: ignore[reportPrivateUsage]
    _pin_url_to_ip,  # pyright: ignore[reportPrivateUsage]
    reset_provider_runtime_state,
    transport_target_for_base_url,
    validate_remote_url,
)
from ahadiff.safety.injection import (
    scan_model_output,
    strip_model_output_fences,
)

# ---------------------------------------------------------------------------
# SSRF — private IP classification
# ---------------------------------------------------------------------------


class TestIsNonPublicIp:
    @pytest.mark.parametrize(
        "ip_str",
        [
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.0.1",
            "192.168.255.255",
            "127.0.0.1",
            "127.0.0.2",
            "169.254.1.1",
            "0.0.0.0",
        ],
    )
    def test_private_ipv4_detected(self, ip_str: str) -> None:
        addr = IPv4Address(ip_str)
        assert _is_non_public_ip(addr) is True

    @pytest.mark.parametrize(
        "ip_str",
        [
            "::1",
            "fe80::1",
            "fc00::1",
            "fd12:3456::1",
            "::ffff:127.0.0.1",
            "::ffff:192.168.1.10",
        ],
    )
    def test_private_ipv6_detected(self, ip_str: str) -> None:
        addr = IPv6Address(ip_str)
        assert _is_non_public_ip(addr) is True

    @pytest.mark.parametrize(
        "ip_str",
        [
            "8.8.8.8",
            "1.1.1.1",
            "104.16.132.229",
        ],
    )
    def test_public_ipv4_not_flagged(self, ip_str: str) -> None:
        addr = IPv4Address(ip_str)
        assert _is_non_public_ip(addr) is False

    @pytest.mark.parametrize(
        "ip_str",
        [
            "2001:4860:4860::8888",
        ],
    )
    def test_public_ipv6_not_flagged(self, ip_str: str) -> None:
        addr = IPv6Address(ip_str)
        assert _is_non_public_ip(addr) is False


# ---------------------------------------------------------------------------
# SSRF — transport_target classifies private IPs as local
# ---------------------------------------------------------------------------


class TestTransportTargetPrivateIPs:
    def test_private_10_network_is_local(self) -> None:
        assert transport_target_for_base_url("http://10.0.0.5:8000", local_hosts=()) == "local"

    def test_private_172_network_is_local(self) -> None:
        assert transport_target_for_base_url("http://172.16.0.1:8000", local_hosts=()) == "local"

    def test_private_192_168_is_local(self) -> None:
        assert transport_target_for_base_url("http://192.168.1.1:8000", local_hosts=()) == "local"

    def test_link_local_is_local(self) -> None:
        assert transport_target_for_base_url("http://169.254.1.1:8000", local_hosts=()) == "local"

    def test_ipv6_link_local_is_local(self) -> None:
        assert (
            transport_target_for_base_url("http://[fe80::1]:8000", local_hosts=()) == "local"
        )

    def test_ipv6_ula_is_local(self) -> None:
        assert (
            transport_target_for_base_url("http://[fd00::1]:8000", local_hosts=()) == "local"
        )

    def test_public_ip_is_remote(self) -> None:
        assert transport_target_for_base_url("http://8.8.8.8:8000", local_hosts=()) == "remote"


# ---------------------------------------------------------------------------
# SSRF — validate_remote_url rejects private IPs
# ---------------------------------------------------------------------------


class TestValidateRemoteUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "http://10.0.0.1:8000",
            "http://172.16.0.1:8000",
            "http://192.168.1.1:8000",
            "http://127.0.0.1:8000",
            "http://[::1]:8000",
            "http://[fe80::1]:8000",
            "http://[fc00::1]:8000",
        ],
    )
    def test_private_ip_rejected(self, url: str) -> None:
        with pytest.raises(SafetyError, match="private/reserved IP"):
            validate_remote_url(url)

    def test_public_ip_accepted(self) -> None:
        result = validate_remote_url("http://8.8.8.8:8000")
        # Literal IP — no DNS resolution, returns None.
        assert result is None

    def test_unix_socket_rejected(self) -> None:
        with pytest.raises(SafetyError, match="local transport scheme"):
            validate_remote_url("unix:///var/run/model.sock")

    def test_npipe_rejected(self) -> None:
        with pytest.raises(SafetyError, match="local transport scheme"):
            validate_remote_url("npipe://./pipe/ollama")

    def test_no_hostname_rejected(self) -> None:
        with pytest.raises(SafetyError, match="unable to determine hostname"):
            validate_remote_url("http://")

    def test_unresolved_hostname_rejected(self) -> None:
        with pytest.raises(SafetyError, match="could not be resolved"):
            validate_remote_url("http://nonexistent.invalid:1234/v1")

    def test_hostname_resolving_to_private_ip_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def resolve_private(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("127.0.0.1")]

        monkeypatch.setattr(
            provider_module,
            "_resolve_hostname_ips",
            resolve_private,
        )
        with pytest.raises(SafetyError, match="resolves to private/reserved IP"):
            validate_remote_url("https://model.example/v1")

    def test_hostname_resolving_to_public_ip_accepted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def resolve_public(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("8.8.8.8")]

        monkeypatch.setattr(
            provider_module,
            "_resolve_hostname_ips",
            resolve_public,
        )
        result = validate_remote_url("https://model.example/v1")
        assert result == "8.8.8.8"

    def test_validate_returns_first_public_ip(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def resolve_multi(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("1.2.3.4"), IPv4Address("5.6.7.8")]

        monkeypatch.setattr(
            provider_module,
            "_resolve_hostname_ips",
            resolve_multi,
        )
        result = validate_remote_url("https://api.example.com/v1")
        assert result == "1.2.3.4"


# ---------------------------------------------------------------------------
# DNS pinning — _pin_url_to_ip rewriting
# ---------------------------------------------------------------------------


class TestPinUrlToIp:
    def test_http_url_rewrite(self) -> None:
        pinned_url, host, sni = _pin_url_to_ip(
            "http://api.example.com:8000/v1/chat", "1.2.3.4"
        )
        assert pinned_url == "http://1.2.3.4:8000/v1/chat"
        assert host == "api.example.com:8000"
        assert sni is None  # No SNI for plain HTTP.

    def test_https_url_rewrite_sets_sni(self) -> None:
        pinned_url, host, sni = _pin_url_to_ip(
            "https://api.example.com/v1/chat", "93.184.216.34"
        )
        assert pinned_url == "https://93.184.216.34/v1/chat"
        assert host == "api.example.com"
        assert sni == "api.example.com"

    def test_ipv6_pinned_address_bracketed(self) -> None:
        pinned_url, host, sni = _pin_url_to_ip(
            "https://api.example.com:443/v1", "2001:db8::1"
        )
        assert pinned_url == "https://[2001:db8::1]:443/v1"
        assert host == "api.example.com:443"
        assert sni == "api.example.com"

    def test_port_preserved(self) -> None:
        pinned_url, host, _sni = _pin_url_to_ip(
            "http://api.example.com:9090/path", "10.0.0.1"
        )
        assert ":9090" in pinned_url
        assert host == "api.example.com:9090"

    def test_no_port_in_url(self) -> None:
        pinned_url, host, sni = _pin_url_to_ip(
            "https://api.example.com/v1", "8.8.8.8"
        )
        assert pinned_url == "https://8.8.8.8/v1"
        assert host == "api.example.com"
        assert sni == "api.example.com"


# ---------------------------------------------------------------------------
# DNS rebinding TOCTOU — validate + pin integration
# ---------------------------------------------------------------------------


class TestDnsRebindingPrevention:
    """Verify that validate_remote_url returns a pinned IP and that
    a second DNS lookup returning a private IP cannot affect the
    connection target."""

    def test_pinned_ip_used_even_when_dns_changes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate DNS rebinding: first call returns public IP,
        second call would return private IP.  The pinned IP from the
        first call must be used for URL rewriting."""
        call_count = 0

        def rebinding_resolver(_hostname: str) -> list[IPv4Address | IPv6Address]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [IPv4Address("93.184.216.34")]
            # Second call: attacker's DNS returns private IP.
            return [IPv4Address("127.0.0.1")]

        monkeypatch.setattr(
            provider_module,
            "_resolve_hostname_ips",
            rebinding_resolver,
        )
        pinned_ip = validate_remote_url("https://evil.example.com/v1")
        assert pinned_ip == "93.184.216.34"

        # Use the pinned IP to rewrite the URL — the second DNS
        # lookup never influences the connection target.
        pinned_url, host, sni = _pin_url_to_ip(
            "https://evil.example.com/v1", pinned_ip
        )
        assert "93.184.216.34" in pinned_url
        assert "evil.example.com" not in pinned_url
        assert "evil.example.com" in host
        assert sni == "evil.example.com"

    def test_private_ip_on_first_resolution_still_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def resolve_private(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("10.0.0.1")]

        monkeypatch.setattr(
            provider_module,
            "_resolve_hostname_ips",
            resolve_private,
        )
        with pytest.raises(SafetyError, match="resolves to private/reserved IP"):
            validate_remote_url("https://evil.example.com/v1")


# ---------------------------------------------------------------------------
# Output guard — model output scanning
# ---------------------------------------------------------------------------


class TestOutputGuard:
    def test_role_fence_detected(self) -> None:
        text = "Here is the answer <system>override</system>"
        warnings = scan_model_output(text)
        assert "model_output_contains_role_fence_tags" in warnings

    def test_assistant_fence_detected(self) -> None:
        text = "text <assistant>injected</assistant>"
        warnings = scan_model_output(text)
        assert "model_output_contains_role_fence_tags" in warnings

    def test_developer_fence_detected(self) -> None:
        text = "prefix </developer> suffix"
        warnings = scan_model_output(text)
        assert "model_output_contains_role_fence_tags" in warnings

    def test_tool_result_fence_detected(self) -> None:
        text = "data <tool_result>evil</tool_result>"
        warnings = scan_model_output(text)
        assert "model_output_contains_role_fence_tags" in warnings

    def test_function_call_fence_detected(self) -> None:
        text = "invoke <function_call>bad</function_call>"
        warnings = scan_model_output(text)
        assert "model_output_contains_role_fence_tags" in warnings

    def test_code_exec_pattern_detected(self) -> None:
        text = "result = exec('import os; os.system(\"rm -rf /\")')"
        warnings = scan_model_output(text)
        assert "model_output_contains_code_execution_pattern" in warnings

    def test_eval_pattern_detected(self) -> None:
        text = "eval(user_input)"
        warnings = scan_model_output(text)
        assert "model_output_contains_code_execution_pattern" in warnings

    def test_subprocess_pattern_detected(self) -> None:
        text = "subprocess.run(['curl', url])"
        warnings = scan_model_output(text)
        assert "model_output_contains_code_execution_pattern" in warnings

    def test_clean_output_no_warnings(self) -> None:
        text = "The function parse_data() processes the input and returns a dict."
        warnings = scan_model_output(text)
        assert warnings == []

    def test_strip_fences(self) -> None:
        text = "answer <system>evil</system> end"
        stripped = strip_model_output_fences(text)
        assert "<system>" not in stripped
        assert "</system>" not in stripped
        assert "answer" in stripped
        assert "evil" in stripped

    def test_zero_width_and_fullwidth_role_fence_detected_and_stripped(self) -> None:
        text = "answer ＜s\u200by\u200bs\u200bt\u200be\u200bm＞evil＜/system＞"
        warnings = scan_model_output(text)
        stripped = strip_model_output_fences(text)
        assert "model_output_contains_role_fence_tags" in warnings
        assert "<system>" not in stripped.casefold()
        assert "</system>" not in stripped.casefold()
        assert "evil" in stripped

    def test_strip_preserves_clean_text(self) -> None:
        text = "normal code output with no fences"
        assert strip_model_output_fences(text) == text


# ---------------------------------------------------------------------------
# Entropy detection — edge cases
# ---------------------------------------------------------------------------


class TestEntropyEdgeCases:
    def test_base64_api_key_detected(self) -> None:
        from ahadiff.safety.redact import redaction_pipeline

        key = "c2stYW50LWFwaTA0LUFiQ2RFZkdoSWpLbE1uT3BRcg=="
        result = redaction_pipeline(f"secret: {key}")
        assert result.blocked_remote or any(
            f.secret_type in {"anthropic_api_key", "high_entropy_string"}
            for f in result.primary_target.findings
        )

    def test_jwt_token_detected(self) -> None:
        from ahadiff.safety.redact import redaction_pipeline

        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        )
        result = redaction_pipeline(f"token: {jwt}")
        assert any(
            f.secret_type == "jwt_token"
            for f in result.primary_target.findings
        )

    def test_short_string_not_flagged(self) -> None:
        from ahadiff.safety.redact import redaction_pipeline

        result = redaction_pipeline("short_tok_abc")
        high_entropy_findings = [
            f for f in result.primary_target.findings if f.secret_type == "high_entropy_string"
        ]
        assert high_entropy_findings == []

    def test_uuid_exempt_from_entropy(self) -> None:
        from ahadiff.safety.redact import redaction_pipeline

        result = redaction_pipeline("id: 550e8400-e29b-41d4-a716-446655440000")
        high_entropy_findings = [
            f for f in result.primary_target.findings if f.secret_type == "high_entropy_string"
        ]
        assert high_entropy_findings == []

    def test_hex_hash_exempt_from_entropy(self) -> None:
        from ahadiff.safety.redact import redaction_pipeline

        result = redaction_pipeline(
            "commit: abcdef1234567890abcdef1234567890abcdef12"
        )
        high_entropy_findings = [
            f for f in result.primary_target.findings if f.secret_type == "high_entropy_string"
        ]
        assert high_entropy_findings == []


# ---------------------------------------------------------------------------
# DNS pinning integration — _send_once() passes pinned URL/Host/SNI to httpx
# ---------------------------------------------------------------------------


def _remote_provider_config(
    *,
    base_url: str = "https://api.example.com/v1",
    model_name: str = "gpt-5.4-mini",
) -> ProviderConfig:
    return ProviderConfig(
        provider_class="openai",  # pyright: ignore[reportArgumentType]
        model_name=model_name,
        base_url=base_url,
        api_key_env="AHADIFF_PROVIDER_API_KEY",
        probed_max_context=4096,
        supports_temperature=True,
    )


def _remote_request(**overrides: Any) -> ProviderRequest:
    payload: dict[str, Any] = {
        "prompt_name": "lesson.generate",
        "prompt_fingerprint": "prompt-v1",
        "prompt_version": "prompt-v1",
        "eval_bundle_version": "bundle-v1",
        "model": "gpt-5.4-mini",
        "payload_text": "Explain the diff.",
        "diff_content": "Explain the diff.",
        "source_ref": "HEAD",
        "privacy_mode": "explicit_remote",
    }
    payload.update(overrides)
    return ProviderRequest(**payload)


def _openai_chat_success_json() -> dict[str, Any]:
    return {
        "model": "gpt-5.4-mini",
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


class TestSendOnceDnsPinning:
    """Integration tests: verify _send_once() plumbs pinned URL, Host header,
    and sni_hostname extension through to httpx.Client.stream()."""

    @pytest.fixture(autouse=True)
    def _reset_runtime(
        self,
        tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> Any:
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
        reset_provider_runtime_state()
        yield
        reset_provider_runtime_state()

    def test_https_hostname_gets_pinned_url_host_and_sni(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """For an HTTPS hostname URL, _send_once must pass the pinned IP URL,
        the original hostname in the Host header, and sni_hostname in
        extensions to httpx.Client.stream()."""
        captured: dict[str, Any] = {}

        def resolve_public(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("93.184.216.34")]

        monkeypatch.setattr(provider_module, "_resolve_hostname_ips", resolve_public)

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["extensions"] = dict(request.extensions)
            return httpx.Response(
                200,
                json=_openai_chat_success_json(),
                headers={"x-request-id": "req-pin-1"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        provider = make_provider(
            _remote_provider_config(base_url="https://api.example.com/v1"),
            api_key="test-key",
            client=client,
        )
        try:
            provider.generate(_remote_request())
        finally:
            provider.close()

        # URL must contain the pinned IP, not the original hostname.
        assert "93.184.216.34" in captured["url"]
        assert "api.example.com" not in captured["url"]
        # Host header must contain the original hostname.
        assert captured["headers"]["host"] == "api.example.com"
        # SNI hostname must be set for HTTPS.
        assert captured["extensions"]["sni_hostname"] == b"api.example.com"

    def test_http_hostname_gets_pinned_url_and_host_no_sni(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """For a plain HTTP hostname URL, sni_hostname must NOT be set."""
        captured: dict[str, Any] = {}

        def resolve_public(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("1.2.3.4")]

        monkeypatch.setattr(provider_module, "_resolve_hostname_ips", resolve_public)

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["extensions"] = dict(request.extensions)
            return httpx.Response(
                200,
                json=_openai_chat_success_json(),
                headers={"x-request-id": "req-pin-2"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        provider = make_provider(
            _remote_provider_config(base_url="http://api.example.com:8080/v1"),
            api_key="test-key",
            client=client,
        )
        try:
            provider.generate(_remote_request())
        finally:
            provider.close()

        assert "1.2.3.4" in captured["url"]
        assert ":8080" in captured["url"]
        assert "api.example.com" not in captured["url"]
        assert captured["headers"]["host"] == "api.example.com:8080"
        # No SNI for plain HTTP — extension key must be absent.
        assert "sni_hostname" not in captured["extensions"]

    def test_literal_ip_url_no_pinning(self) -> None:
        """When the base_url already contains a literal public IP,
        validate_remote_url returns None and no pinning is applied."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["extensions"] = dict(request.extensions)
            return httpx.Response(
                200,
                json=_openai_chat_success_json(),
                headers={"x-request-id": "req-pin-3"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        provider = make_provider(
            _remote_provider_config(base_url="http://8.8.8.8:8000/v1"),
            api_key="test-key",
            client=client,
        )
        try:
            provider.generate(_remote_request())
        finally:
            provider.close()

        # URL must still contain the literal IP as-is (not rewritten).
        assert "8.8.8.8:8000" in captured["url"]
        # httpx sets the Host header from the URL automatically; the
        # pinning path would replace it with the *original hostname*,
        # but since there is no hostname here the Host header should
        # match the literal IP authority that httpx generates.
        assert captured["headers"].get("host", "").startswith("8.8.8.8")
        # No SNI extension for literal IP.
        assert "sni_hostname" not in captured["extensions"]

    def test_https_hostname_with_non_default_port_in_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Host header must include port when non-default (RFC 7230 5.4)."""
        captured: dict[str, Any] = {}

        def resolve_public(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("5.6.7.8")]

        monkeypatch.setattr(provider_module, "_resolve_hostname_ips", resolve_public)

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["extensions"] = dict(request.extensions)
            return httpx.Response(
                200,
                json=_openai_chat_success_json(),
                headers={"x-request-id": "req-pin-4"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        provider = make_provider(
            _remote_provider_config(base_url="https://api.example.com:9443/v1"),
            api_key="test-key",
            client=client,
        )
        try:
            provider.generate(_remote_request())
        finally:
            provider.close()

        assert "5.6.7.8" in captured["url"]
        assert ":9443" in captured["url"]
        assert captured["headers"]["host"] == "api.example.com:9443"
        assert captured["extensions"]["sni_hostname"] == b"api.example.com"

    def test_userinfo_preserved_in_pinned_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Userinfo (user@ prefix) must survive the pinning rewrite."""
        captured: dict[str, Any] = {}

        def resolve_public(_hostname: str) -> list[IPv4Address | IPv6Address]:
            return [IPv4Address("93.184.216.34")]

        monkeypatch.setattr(provider_module, "_resolve_hostname_ips", resolve_public)

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json=_openai_chat_success_json(),
                headers={"x-request-id": "req-pin-5"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler), trust_env=False)
        provider = make_provider(
            _remote_provider_config(base_url="https://apiuser@api.example.com/v1"),
            api_key="test-key",
            client=client,
        )
        try:
            provider.generate(_remote_request())
        finally:
            provider.close()

        assert "apiuser@" in captured["url"]
        assert "93.184.216.34" in captured["url"]
        assert "api.example.com" not in captured["url"]
