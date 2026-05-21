from __future__ import annotations

import argparse
import json
import sys
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
}
PROVIDER_ALIASES = {
    "vertex_ai": "gemini",
    "vertex_ai-language-models": "gemini",
    "google": "gemini",
    "deepseek": "openai_compat",
    "fireworks_ai": "openai_compat",
    "groq": "openai_compat",
    "mistral": "openai_compat",
    "openrouter": "openai_compat",
    "together_ai": "openai_compat",
    "xai": "openai_compat",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate AhaDiff's vendored model limit registry from LiteLLM metadata."
    )
    parser.add_argument("--url", default=DEFAULT_LITELLM_REGISTRY_URL)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("src/ahadiff/llm/model_registry.json"),
    )
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()

    raw_registry = _download_registry(args.url)
    entries = _curate_entries(raw_registry, limit=max(1, args.limit))
    payload = {"schema_version": 1, "entries": entries}
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(entries)} entries to {args.out}")
    return 0


def _download_registry(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=30) as response:  # noqa: S310 - dev-time script only
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("LiteLLM registry payload must be a JSON object")
    return cast("dict[str, Any]", payload)


def _curate_entries(registry: dict[str, Any], *, limit: int) -> list[dict[str, object]]:
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
        max_input = _optional_positive_int(
            entry.get("max_input_tokens")
            or entry.get("max_context_tokens")
            or entry.get("max_tokens")
            or entry.get("context_window")
        )
        max_output = _optional_positive_int(
            entry.get("max_output_tokens")
            or entry.get("max_completion_tokens")
            or entry.get("output_token_limit")
        )
        if max_input is None and max_output is None:
            continue
        aliases = _aliases_for_model(str(model), entry)
        curated.append(
            {
                "provider": provider,
                "model": str(model),
                "mode": "chat",
                "max_input_tokens": max_input,
                "max_output_tokens": max_output,
                "aliases": aliases,
                "confidence": "registry",
            }
        )
        if len(curated) >= limit:
            break
    return curated


def _provider_for_entry(entry: dict[str, Any]) -> str | None:
    raw_provider = str(entry.get("litellm_provider") or entry.get("provider") or "").lower()
    provider = PROVIDER_ALIASES.get(raw_provider, raw_provider)
    if provider in KNOWN_PROVIDERS:
        return provider
    return None


def _aliases_for_model(model: str, entry: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("model_name", "aliases"):
        raw_value = entry.get(key)
        if isinstance(raw_value, str) and raw_value and raw_value != model:
            aliases.append(raw_value)
        elif isinstance(raw_value, list):
            aliases.extend(str(item) for item in raw_value if isinstance(item, str) and item)
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
