from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ServeState:
    state_dir: Path
    token: str
    locale: Literal["en", "zh-CN"] = "en"
    bind_host: str = "127.0.0.1"
    port: int = 8765
    write_lock: asyncio.Lock | None = None

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def review_db_path(self) -> Path:
        return self.state_dir / "review.sqlite"

    def with_runtime_lock(self) -> ServeState:
        if self.write_lock is not None:
            return self
        return replace(self, write_lock=asyncio.Lock())

    def with_locale(self, locale: Literal["en", "zh-CN"]) -> ServeState:
        return replace(self, locale=locale)


__all__ = ["ServeState"]
