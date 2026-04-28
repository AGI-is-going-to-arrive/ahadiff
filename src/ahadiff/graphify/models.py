from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GraphifyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    file_path: str | None = None
    kind: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphifyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    relation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphifyHyperedge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    nodes: list[str]
    relation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphifyGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directed: bool = True
    multigraph: bool = False
    graph: dict[str, Any] = Field(default_factory=dict)
    nodes: list[GraphifyNode] = Field(default_factory=lambda: list[GraphifyNode]())
    links: list[GraphifyEdge] = Field(default_factory=lambda: list[GraphifyEdge]())
    hyperedges: list[GraphifyHyperedge] = Field(default_factory=lambda: list[GraphifyHyperedge]())
