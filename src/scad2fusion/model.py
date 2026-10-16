"""Small, dependency-free intermediate representation for SCAD frontends."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Expr:
    """A scalar value together with its source-level symbolic expression."""

    value: float | int | bool | str
    text: str
    deps: frozenset[str] = field(default_factory=frozenset)


@dataclass
class Node:
    """Normalized geometry/CSG operation."""

    op: str
    args: dict[str, Any] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    line: int = 1


@dataclass
class Program:
    """Frontend result consumed by the Fusion generator."""

    parameters: dict[str, Expr]
    geometry: Node
    source_name: str
    rebuild_parameters: frozenset[str] = field(default_factory=frozenset)
