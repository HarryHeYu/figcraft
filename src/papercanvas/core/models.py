"""Figure IR v0.1 — the single source of truth.

Every SVG/PDF/PPTX file is a build product of this model; nothing else is
ever edited directly. Geometric coordinates are millimetres, font sizes are
points. Node extents use the field names ``w``/``h`` (the v0.1 canonical
spelling).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "0.1"
SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ("0.1",)

Port = Literal["left", "right", "top", "bottom"]
NodeType = Literal["rect", "rounded_rect"]
DashPattern = Literal["solid", "dashed", "dotted"]
ArrowMode = Literal["none", "end", "start", "both"]

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class IrModel(BaseModel):
    """Base for all IR models: strict about unknown fields and non-finite numbers.

    ``validate_assignment`` closes the setattr hole: patch handlers must never
    be able to place schema-invalid values into a live model (a figure that
    can no longer be loaded is data corruption, not an inconvenience).
    """

    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, validate_assignment=True
    )


def _no_bool(value: object) -> object:
    """Field validator hook (mode="before").

    Pydantic's lax mode would coerce ``True`` to ``1.0`` / ``1``; numeric IR
    fields must refuse booleans outright so every write path behaves alike.
    """
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid number")
    return value


def check_id(value: str) -> str:
    if not value or not ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"invalid id {value!r}: ids must be non-empty and match {ID_PATTERN.pattern}"
        )
    return value


class Style(IrModel):
    """Visual style for nodes and groups."""

    fill: str | None = None
    stroke: str | None = None
    stroke_width: float | None = None
    stroke_dash: DashPattern | None = None

    @field_validator("stroke_width", mode="before")
    @classmethod
    def _no_bool_width(cls, value: object) -> object:
        return _no_bool(value)


class EdgeStyle(IrModel):
    """Visual style for edges."""

    stroke: str | None = None
    stroke_width: float | None = None
    arrow: ArrowMode = "end"

    @field_validator("stroke_width", mode="before")
    @classmethod
    def _no_bool_width(cls, value: object) -> object:
        return _no_bool(value)


class Canvas(IrModel):
    width: float
    height: float
    unit: Literal["mm"] = "mm"
    margin: float = 4.0

    @field_validator("width", "height", "margin", mode="before")
    @classmethod
    def _no_bool_dims(cls, value: object) -> object:
        return _no_bool(value)


class Node(IrModel):
    """A box on the canvas.

    ``x``/``y``/``w``/``h`` are the authoritative rendering coordinates in mm.
    They may be ``None`` in an IR that awaits automatic layout; renderers
    refuse to run until a layout pass has filled them in.
    """

    id: str
    type: NodeType = "rect"
    label: str = ""
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    style: Style = Field(default_factory=Style)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return check_id(value)

    @field_validator("x", "y", "w", "h", mode="before")
    @classmethod
    def _no_bool_coords(cls, value: object) -> object:
        return _no_bool(value)

    @property
    def is_placed(self) -> bool:
        return None not in (self.x, self.y, self.w, self.h)


class Edge(IrModel):
    """A directed, port-annotated connection between two nodes. Self-loops are hard errors."""

    id: str
    source: str
    target: str
    source_port: Port = "right"
    target_port: Port = "left"
    style: EdgeStyle = Field(default_factory=EdgeStyle)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return check_id(value)


class Group(IrModel):
    """A logical grouping of existing nodes, drawn as a dashed background box."""

    id: str
    children: list[str]
    label: str = ""
    style: Style = Field(
        default_factory=lambda: Style(stroke="#999999", stroke_dash="dashed")
    )

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return check_id(value)


class Theme(IrModel):
    """Global visual specification."""

    font_family: str = "Arial"
    font_size_pt: float = 8.0
    palette: dict[str, str] = Field(default_factory=dict)
    background: str = "#FFFFFF"

    @field_validator("font_size_pt", mode="before")
    @classmethod
    def _no_bool_size(cls, value: object) -> object:
        return _no_bool(value)


class Figure(IrModel):
    schema_version: str = SCHEMA_VERSION
    id: str
    revision: int = Field(default=1, ge=1)
    canvas: Canvas
    theme: Theme = Field(default_factory=Theme)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        return check_id(value)

    @field_validator("revision", mode="before")
    @classmethod
    def _no_bool_revision(cls, value: object) -> object:
        return _no_bool(value)

    # -- lookup helpers (linear scans are fine at figure scale) ------------

    def node(self, node_id: str) -> Node | None:
        return self._find(self.nodes, node_id)

    def edge(self, edge_id: str) -> Edge | None:
        return self._find(self.edges, edge_id)

    def group(self, group_id: str) -> Group | None:
        return self._find(self.groups, group_id)

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def style_target(self, target_id: str) -> Node | Edge | Group | None:
        """Find any style-bearing object by id (nodes, then edges, then groups)."""
        for collection in (self.nodes, self.edges, self.groups):
            found = self._find(collection, target_id)  # type: ignore[arg-type]
            if found is not None:
                return found
        return None

    @staticmethod
    def _find(collection: list, object_id: str):  # noqa: ANN202 - homogeneous lists
        for item in collection:
            if item.id == object_id:
                return item
        return None


def resolve_color(value: str, theme: Theme) -> str:
    """Resolve a style color to a concrete hex string.

    Accepts ``#rgb``/``#rrggbb`` literals or keys of ``theme.palette``.
    Raises ValueError for anything else; validate.py turns that into a hard
    error before any write or render.
    """
    if HEX_COLOR_PATTERN.fullmatch(value):
        return value
    if value in theme.palette:
        return theme.palette[value]
    raise ValueError(f"color {value!r} is neither a hex literal nor a palette key")
