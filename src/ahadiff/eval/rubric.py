from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ahadiff.contracts import RUBRIC_WEIGHTS
from ahadiff.core.errors import InputError
from ahadiff.core.json_util import safe_json_loads


@dataclass(frozen=True)
class RubricDimension:
    name: str
    max_score: float
    hard_gate: float | None = None


@dataclass(frozen=True)
class RubricDefinition:
    rubric_version: str
    pass_threshold: float
    caution_threshold: float
    dimensions: tuple[RubricDimension, ...]

    def dimension(self, name: str) -> RubricDimension:
        for item in self.dimensions:
            if item.name == name:
                return item
        raise KeyError(name)


def load_rubric(path: Path | None = None) -> RubricDefinition:
    target = path or Path(__file__).with_name("rubric.yaml")
    try:
        payload = safe_json_loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"rubric file does not exist: {target}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise InputError(f"rubric file is not valid JSON-compatible YAML: {target}") from exc
    if not isinstance(payload, dict):
        raise InputError("rubric file must decode to an object")
    payload_map = cast("dict[str, object]", payload)

    raw_dimensions = payload_map.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raise InputError("rubric file must contain an object-valued dimensions field")
    raw_dimensions_map = cast("dict[str, object]", raw_dimensions)

    expected_names = tuple(RUBRIC_WEIGHTS.keys())
    if tuple(raw_dimensions_map.keys()) != expected_names:
        raise InputError(
            "rubric dimensions must exactly match the frozen contract order: "
            + ", ".join(expected_names)
        )

    dimensions: list[RubricDimension] = []
    for name, contract in RUBRIC_WEIGHTS.items():
        raw_dimension = raw_dimensions_map.get(name)
        if not isinstance(raw_dimension, dict):
            raise InputError(f"rubric dimension {name!r} must be an object")
        raw_dimension_map = cast("dict[str, object]", raw_dimension)
        max_score = _coerce_float(raw_dimension_map.get("max_score", -1), field="max_score")
        expected_max = float(contract["weight"])
        if max_score != expected_max:
            raise InputError(f"rubric dimension {name!r} max_score must be {expected_max}")
        hard_gate_raw = raw_dimension_map.get("hard_gate")
        expected_gate = contract.get("hard_gate")
        if expected_gate is None:
            if hard_gate_raw is not None:
                raise InputError(f"rubric dimension {name!r} must not define hard_gate")
            hard_gate = None
        else:
            if not isinstance(hard_gate_raw, int | float):
                raise InputError(f"rubric dimension {name!r} hard_gate must be numeric")
            hard_gate = float(hard_gate_raw)
            if hard_gate != float(expected_gate):
                raise InputError(f"rubric dimension {name!r} hard_gate must be {expected_gate}")
        dimensions.append(
            RubricDimension(
                name=name,
                max_score=max_score,
                hard_gate=hard_gate,
            )
        )

    return RubricDefinition(
        rubric_version=str(payload_map.get("rubric_version", "v0.1")),
        pass_threshold=_coerce_float(payload_map.get("pass_threshold", 80), field="pass_threshold"),
        caution_threshold=_coerce_float(
            payload_map.get("caution_threshold", 60),
            field="caution_threshold",
        ),
        dimensions=tuple(dimensions),
    )


def _coerce_float(value: object, *, field: str) -> float:
    if not isinstance(value, int | float):
        raise InputError(f"rubric field {field!r} must be numeric")
    return float(value)


__all__ = ["RubricDefinition", "RubricDimension", "load_rubric"]
