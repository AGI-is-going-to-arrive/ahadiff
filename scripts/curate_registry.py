from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.request import urlopen

DEFAULT_LITELLM_REGISTRY_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
KNOWN_PROVIDERS = {
    "anthropic",
    "azure",
    "gemini",
    "lmstudio",
    "newapi",
    "ollama",
    "openai",
    "openai_compat",
    "openai_responses",
    "openrouter",
}
PROVIDER_ALIASES = {
    "vertex_ai": "gemini",
    "vertex_ai-language-models": "gemini",
    "google": "gemini",
    "deepseek": "openai_compat",
    "fireworks_ai": "openai_compat",
    "groq": "openai_compat",
    "mistral": "openai_compat",
    "openrouter": "openrouter",
    "together_ai": "openai_compat",
    "xai": "openai_compat",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate AhaDiff's vendored model limit registry from LiteLLM metadata."
    )
    parser.add_argument("--url", default=DEFAULT_LITELLM_REGISTRY_URL)
    parser.add_argument("--input", type=Path, help="Read a saved LiteLLM snapshot without network.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("src/ahadiff/llm/model_registry.json"),
    )
    parser.add_argument("--limit", type=int, help="Optional cap; all supported models by default.")
    parser.add_argument("--source-tag", default=None)
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    raw_registry = (
        _parse_registry(args.input.read_text(encoding="utf-8"))
        if args.input is not None
        else _download_registry(args.url)
    )
    entries = _curate_entries(
        raw_registry,
        limit=args.limit,
        source_tag=args.source_tag or _default_source_tag(args.url),
    )
    payload = {"schema_version": 2, "models": entries}
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} entries to {args.out}")
    return 0


def _download_registry(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=30) as response:  # noqa: S310 - dev-time script only
        return _parse_registry(response.read().decode("utf-8"))


def _parse_registry(raw_text: str) -> dict[str, Any]:
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("LiteLLM registry payload must be a JSON object")
    return cast("dict[str, Any]", payload)


def _default_source_tag(url: str = DEFAULT_LITELLM_REGISTRY_URL) -> str:
    return f"{url}; retrieved {datetime.now(UTC).date().isoformat()}"


def _curate_entries(
    registry: dict[str, Any],
    *,
    limit: int | None = None,
    source_tag: str | None = None,
) -> list[dict[str, object]]:
    curated: list[dict[str, object]] = []
    for model, raw_entry in sorted(registry.items()):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast("dict[str, Any]", raw_entry)
        if entry.get("mode") != "chat":
            continue
        provider = _provider_for_entry(entry)
        if provider is None:
            continue
        model_name = _model_name_for_entry(str(model), provider, entry)
        top_provider = entry.get("top_provider")
        top_provider_context = (
            _optional_positive_int(cast("dict[str, Any]", top_provider).get("context_length"))
            if isinstance(top_provider, dict)
            else None
        )
        raw_context = _optional_positive_int(
            entry.get("max_context_tokens")
            or entry.get("max_context_length")
            or entry.get("context_length")
            or entry.get("context_window")
            or entry.get("max_tokens")
        )
        max_input = _optional_positive_int(
            entry.get("max_input_tokens")
            or entry.get("input_token_limit")
            or entry.get("max_context_tokens")
            or entry.get("max_context_length")
            or entry.get("context_length")
            or entry.get("max_tokens")
            or entry.get("context_window")
        )
        max_output = _optional_positive_int(
            entry.get("max_output_tokens")
            or entry.get("max_completion_tokens")
            or entry.get("output_token_limit")
        )
        context_policy = _context_policy_for_provider(provider)
        max_context = top_provider_context if provider == "openrouter" else raw_context
        if provider == "openrouter" and top_provider_context is not None:
            max_input = top_provider_context
        if context_policy == "split_envelope" and max_input is not None and max_output is not None:
            max_context = max_input + max_output
        if max_context is None and context_policy != "local_runtime":
            continue
        if max_input is None:
            max_input = max_context
        warnings: list[str] = []
        if (
            max_context is not None
            and max_output is not None
            and max_output > max_context
            and context_policy != "split_envelope"
        ):
            max_output = None
            warnings.append("max_output_tokens omitted because it exceeded max_context_tokens")
        aliases = _aliases_for_model(model_name, entry)
        curated.append(
            {
                "provider": provider,
                "model": model_name,
                "aliases": aliases,
                "max_context_tokens": max_context,
                "max_input_tokens": max_input,
                "max_output_tokens": max_output,
                "context_policy": context_policy,
                "source": source_tag or _default_source_tag(),
                "confidence": "medium",
                "warnings": warnings,
            }
        )
        if limit is not None and len(curated) >= limit:
            break
    return curated


def _provider_for_entry(entry: dict[str, Any]) -> str | None:
    raw_provider = str(entry.get("litellm_provider") or entry.get("provider") or "").lower()
    provider = PROVIDER_ALIASES.get(raw_provider, raw_provider)
    if provider in KNOWN_PROVIDERS:
        return provider
    return None


def _model_name_for_entry(model: str, provider: str, entry: dict[str, Any]) -> str:
    raw_provider = str(entry.get("litellm_provider") or entry.get("provider") or "").lower()
    provider_prefixes = {provider, raw_provider, *PROVIDER_ALIASES.keys()}
    if "/" not in model:
        return model
    qualifier, remainder = model.split("/", 1)
    normalized_qualifier = qualifier.lower()
    if (
        normalized_qualifier in provider_prefixes
        and PROVIDER_ALIASES.get(normalized_qualifier, normalized_qualifier) == provider
    ):
        return remainder
    return model


def _context_policy_for_provider(provider: str) -> str:
    if provider in {"lmstudio", "ollama"}:
        return "local_runtime"
    if provider == "openrouter":
        return "route_specific"
    if provider == "gemini":
        return "split_envelope"
    return "shared_pool"


def _aliases_for_model(model: str, entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("model_name", "aliases"):
        raw_value = entry.get(key)
        if isinstance(raw_value, str) and raw_value and raw_value != model:
            aliases.append(raw_value)
        elif isinstance(raw_value, list):
            aliases.extend(
                item for item in cast("list[object]", raw_value) if isinstance(item, str) and item
            )
    return sorted(set(aliases))


def _optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


if __name__ == "__main__":
    sys.exit(main())
