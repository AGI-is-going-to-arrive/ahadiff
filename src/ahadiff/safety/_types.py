from __future__ import annotations

from typing import Literal

SourceKind = Literal[
    "raw_patch",
    "resolved_file",
    "branch_name",
    "tag_name",
    "markdown",
    "string",
]

__all__ = ["SourceKind"]
