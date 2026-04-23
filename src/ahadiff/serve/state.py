from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
        return ServeState(
            state_dir=self.state_dir,
            token=self.token,
            locale=self.locale,
            bind_host=self.bind_host,
            port=self.port,
            write_lock=asyncio.Lock(),
        )


__all__ = ["ServeState"]
