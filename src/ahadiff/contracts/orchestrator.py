from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .event_log import RunStatus, Verdict
from .run_source import DegradedFlag, PrivacyMode, RunSource


class LearnabilityWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complexity: float = 0.4
    novelty: float = 0.3
    pattern: float = 0.3


class LearnabilityGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: LearnabilityWeights = Field(default_factory=LearnabilityWeights)
    threshold: float = 0.3
    calibration_status: Literal["heuristic_default"] = "heuristic_default"


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: RunSource
    lang: Literal["auto", "en", "zh-CN"] = "auto"
    privacy_mode: PrivacyMode = "strict_local"
    force_learn: bool = False
    use_graphify: bool | None = None
    dry_run: bool = False


class ServeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port: int = 8765
    no_browser: bool = False
    bind_host: Literal["127.0.0.1"] = "127.0.0.1"


class OrchestratorCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["learn", "improve", "verify", "serve"]
    run_config: RunConfig | None = None
    serve_config: ServeConfig | None = None

    @model_validator(mode="after")
    def validate_config_shape(self) -> "OrchestratorCommand":
        if self.kind == "serve":
            if self.serve_config is None or self.run_config is not None:
                raise ValueError("serve requires serve_config and forbids run_config")
            return self

        if self.run_config is None or self.serve_config is not None:
            raise ValueError(f"{self.kind} requires run_config and forbids serve_config")
        return self


class OrchestratorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    overall: float | None = None
    verdict: Verdict | None = None
    weakest_dim: str | None = None
    artifacts_path: str | None = None
    note_json: str | None = None
    degraded_flags: dict[DegradedFlag, bool] = Field(default_factory=dict)


class Orchestrator:
    async def run_learn(self, config: RunConfig) -> OrchestratorResult:
        raise NotImplementedError("run_learn must be implemented by a runtime orchestrator")

    async def run_improve(self, config: RunConfig) -> OrchestratorResult:
        raise NotImplementedError("run_improve must be implemented by a runtime orchestrator")

    async def run_verify(self, config: RunConfig) -> OrchestratorResult:
        raise NotImplementedError("run_verify must be implemented by a runtime orchestrator")

    async def run_serve(self, config: ServeConfig) -> None:
        raise NotImplementedError("run_serve must be implemented by a runtime orchestrator")


__all__ = [
    "LearnabilityWeights",
    "LearnabilityGate",
    "Orchestrator",
    "OrchestratorCommand",
    "OrchestratorResult",
    "RunConfig",
    "ServeConfig",
]
