"""Hard validation for the Figure IR.

A figure that fails any check here must never be committed to disk or
rendered. Cosmetic/quality checks (overflow, overlap, font size, ...) are a
separate concern and live in the lint package from M2 onwards — deliberately
separated from these structural hard errors.
"""

from __future__ import annotations

from .errors import FigureValidationError
from .models import HEX_COLOR_PATTERN, Edge, Figure, Theme, resolve_color

_STYLE_FIELDS = ("fill", "stroke")

#: sanity ceiling (10 km) — far above any real figure, far below float ranges
#: where layout arithmetic could overflow to inf
MAX_DIMENSION_MM = 10_000_000.0
#: ceiling for font sizes and stroke widths in their native units
MAX_METRIC_PT = 1000.0


def _check_color(where: str, value: str | None, theme: Theme, errors: list[str]) -> None:
    if value is None:
        return
    try:
        resolve_color(value, theme)
    except ValueError as exc:
        errors.append(f"{where}: {exc}")


def _check_style(where: str, style, theme: Theme, errors: list[str]) -> None:
    """Check a node/group Style. ``style`` is a Style instance."""
    for field_name in _STYLE_FIELDS:
        _check_color(where, getattr(style, field_name), theme, errors)
    if style.stroke_width is not None:
        if style.stroke_width <= 0:
            errors.append(
                f"{where}: stroke_width must be > 0, got {style.stroke_width}"
            )
        elif style.stroke_width > MAX_METRIC_PT:
            errors.append(
                f"{where}: stroke_width must be <= {MAX_METRIC_PT:g}, got {style.stroke_width}"
            )


def _check_edge_style(where: str, edge: Edge, theme: Theme, errors: list[str]) -> None:
    _check_color(where, edge.style.stroke, theme, errors)
    if edge.style.stroke_width is not None:
        if edge.style.stroke_width <= 0:
            errors.append(f"{where}: stroke_width must be > 0, got {edge.style.stroke_width}")
        elif edge.style.stroke_width > MAX_METRIC_PT:
            errors.append(
                f"{where}: stroke_width must be <= {MAX_METRIC_PT:g}, got {edge.style.stroke_width}"
            )


def _check_theme(theme: Theme, errors: list[str]) -> None:
    if theme.font_size_pt <= 0:
        errors.append(f"theme: font_size_pt must be > 0, got {theme.font_size_pt}")
    elif theme.font_size_pt > MAX_METRIC_PT:
        errors.append(
            f"theme: font_size_pt must be <= {MAX_METRIC_PT:g}, got {theme.font_size_pt}"
        )
    if not theme.font_family.strip():
        errors.append("theme: font_family must not be empty")
    if not HEX_COLOR_PATTERN.fullmatch(theme.background):
        errors.append(f"theme: background {theme.background!r} is not a hex color")
    for key, value in theme.palette.items():
        if not HEX_COLOR_PATTERN.fullmatch(value):
            errors.append(f"theme.palette[{key!r}]: {value!r} is not a hex color")


def validate_figure(fig: Figure) -> list[str]:
    """Return every hard-rule violation as a human-readable message (empty list = valid)."""
    errors: list[str] = []

    if fig.schema_version not in ("0.1",):
        supported = ", ".join(f"{v!r}" for v in ("0.1",))
        errors.append(
            f"unsupported schema_version {fig.schema_version!r}; supported: {supported}"
        )

    # -- canvas -------------------------------------------------------------
    if fig.canvas.width <= 0:
        errors.append(f"canvas: width must be > 0, got {fig.canvas.width}")
    elif fig.canvas.width > MAX_DIMENSION_MM:
        errors.append(f"canvas: width must be <= {MAX_DIMENSION_MM:g} mm, got {fig.canvas.width}")
    if fig.canvas.height <= 0:
        errors.append(f"canvas: height must be > 0, got {fig.canvas.height}")
    elif fig.canvas.height > MAX_DIMENSION_MM:
        errors.append(f"canvas: height must be <= {MAX_DIMENSION_MM:g} mm, got {fig.canvas.height}")
    if fig.canvas.margin < 0:
        errors.append(f"canvas: margin must be >= 0, got {fig.canvas.margin}")
    elif fig.canvas.margin > MAX_DIMENSION_MM:
        errors.append(f"canvas: margin must be <= {MAX_DIMENSION_MM:g} mm, got {fig.canvas.margin}")

    _check_theme(fig.theme, errors)

    # -- global id uniqueness across nodes/edges/groups ----------------------
    seen: dict[str, str] = {}

    def register(object_id: str, kind: str) -> None:
        if object_id in seen:
            errors.append(
                f"duplicate id {object_id!r}: defined both as {seen[object_id]} and {kind}"
            )
        else:
            seen[object_id] = kind

    for node in fig.nodes:
        register(node.id, "node")
    for edge in fig.edges:
        register(edge.id, "edge")
    for group in fig.groups:
        register(group.id, "group")

    node_ids = fig.node_ids()

    # -- nodes: geometry sanity (coordinates may be None until layout runs) --
    for node in fig.nodes:
        where = f"node {node.id!r}"
        for name in ("w", "h"):
            value = getattr(node, name)
            if value is not None and value <= 0:
                errors.append(f"{where}: {name} must be > 0, got {value}")
            elif value is not None and value > MAX_DIMENSION_MM:
                errors.append(
                    f"{where}: {name} must be <= {MAX_DIMENSION_MM:g} mm, got {value}"
                )
        for name in ("x", "y"):
            value = getattr(node, name)
            if value is not None and abs(value) > MAX_DIMENSION_MM:
                errors.append(
                    f"{where}: {name} must be within ±{MAX_DIMENSION_MM:g} mm, got {value}"
                )
        _check_style(where, node.style, fig.theme, errors)

    # -- edges: dangling references and self-loops ---------------------------
    for edge in fig.edges:
        where = f"edge {edge.id!r}"
        if edge.source not in node_ids:
            errors.append(f"{where}: source {edge.source!r} is not a node")
        if edge.target not in node_ids:
            errors.append(f"{where}: target {edge.target!r} is not a node")
        if edge.source == edge.target:
            errors.append(f"{where}: self-loops are hard errors in v0.1")
        _check_edge_style(where, edge, fig.theme, errors)

    # -- groups: children must exist, be unique, and be claimed once ---------
    owner: dict[str, str] = {}
    for group in fig.groups:
        where = f"group {group.id!r}"
        if not group.children:
            errors.append(f"{where}: children must not be empty")
        _check_style(where, group.style, fig.theme, errors)
        for child in group.children:
            if child not in node_ids:
                errors.append(f"{where}: child {child!r} is not a node")
            if child in owner:
                errors.append(
                    f"{where}: node {child!r} is already claimed by group {owner[child]!r}"
                )
            else:
                owner[child] = group.id
        if len(set(group.children)) != len(group.children):
            errors.append(f"{where}: children contain duplicates")

    return errors


def ensure_valid(fig: Figure) -> None:
    """Raise FigureValidationError unless ``fig`` passes every hard rule."""
    errors = validate_figure(fig)
    if errors:
        raise FigureValidationError(errors)
