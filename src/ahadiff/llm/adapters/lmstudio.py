from __future__ import annotations

from typing import TYPE_CHECKING

from .openai_compat import OpenAICompatAdapter

if TYPE_CHECKING:
    from ahadiff.contracts import ProviderCapabilities


class LMStudioAdapter(OpenAICompatAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return super().capabilities.model_copy(
            update={
                "supports_native_json_schema": True,
                "structured_output_notes": ("lm-studio-structured-output",),
            }
        )
