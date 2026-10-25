"""Orthogonal edge routing — the output contract is a polyline point list.

Engineering constraint 4: the point sequence produced here is THE path.
SVG consumes it as a ``<polyline>``; PPTX (M2) must rebuild it from native
line segments and may not assume a single ELBOW connector reproduces it.
Constraint 6d: the same inputs always produce the same point sequence —
routing is a pure function with no hidden state.

Obstacle avoidance is deterministic and best-effort: a fixed candidate order
with a fixed channel clearance, no search and no randomness. A path that
cannot be cleared of every obstacle is returned unchanged so lint FC006 can
report it — avoidance never invents non-orthogonal detours.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from papercanvas.core.models import Node

#: distance (mm) a connector travels straight out of a port before turning
STUB_MM = 4.0

#: clearance (mm) between a detour channel and the blocking obstacles' bbox
CHANNEL_GAP_MM = 6.0

_EPS = 1e-9
#: rect shrink for hit tests: touching a boundary is not passing through
_HIT_EPS = 1e-6


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def port_point(node: Node, port: str) -> Point:
    """Midpoint of the given side, exactly on the node boundary."""
    if port == "left":
        return Point(node.x, node.y + node.h / 2)
    if port == "right":
        return Point(node.x + node.w, node.y + node.h / 2)
    if port == "top":
        return Point(node.x + node.w / 2, node.y)
    if port == "bottom":
        return Point(node.x + node.w / 2, node.y + node.h)
    raise ValueError(f"unknown port {port!r}")  # pragma: no cover - Literal-guarded


def _outward(port: str) -> Point:
    """Unit vector pointing away from the node through the given port."""
    return {
        "left": Point(-1.0, 0.0),
        "right": Point(1.0, 0.0),
        "top": Point(0.0, -1.0),
        "bottom": Point(0.0, 1.0),
    }[port]


def _add(p: Point, dx: float, dy: float) -> Point:
    return Point(p.x + dx, p.y + dy)


def _same_axis(a: str, b: str) -> bool:
    horizontal = ("left", "right")
    return (a in horizontal) == (b in horizontal)


def _dedupe(points: list[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if result and math.isclose(result[-1].x, point.x, abs_tol=_EPS) and math.isclose(
            result[-1].y, point.y, abs_tol=_EPS
        ):
            continue
        result.append(point)
    return result


def _segment_hits(start: Point, end: Point, node: Node) -> bool:
    """Liang-Barsky segment/AABB test against the node rect, shrunk by
    ``_HIT_EPS`` so merely touching a boundary is not "passing through".
    Same semantics as lint ``rules._path_hits`` — router and lint must agree
    on what a crossing is. Only called with placed nodes."""
    x0, y0 = node.x + _HIT_EPS, node.y + _HIT_EPS
    x1, y1 = node.x + node.w - _HIT_EPS, node.y + node.h - _HIT_EPS
    dx, dy = end.x - start.x, end.y - start.y
    t0, t1 = 0.0, 1.0
    for p, q in (
        (-dx, start.x - x0),
        (dx, x1 - start.x),
        (-dy, start.y - y0),
        (dy, y1 - start.y),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _path_hits(points: list[Point], node: Node) -> bool:
    return any(
        _segment_hits(start, end, node)
        for start, end in zip(points, points[1:], strict=False)
    )


def _clear_of(points: list[Point], obstacles: list[Node]) -> bool:
    """True when no segment crosses any obstacle (boundary contact allowed)."""
    return not any(_path_hits(points, ob) for ob in obstacles)


def _spine_detour(p0: Point, p1: Point, horizontal_spine: bool, at: float) -> list[Point]:
    """p0 -> p1 orthogonal path whose long run sits on one coordinate
    (``y == at`` for a horizontal spine, ``x == at`` otherwise)."""
    if horizontal_spine:
        return [p0, Point(p0.x, at), Point(p1.x, at), p1]
    return [p0, Point(at, p0.y), Point(at, p1.y), p1]


def _candidate_paths(
    base: list[Point],
    p0: Point,
    p1: Point,
    bbox: tuple[float, float, float, float],
    primary_y: bool,
) -> list[list[Point]]:
    """Detour candidates in a fixed, deterministic order: the original path,
    then channels on the min/max side of the blocking bbox at
    CHANNEL_GAP_MM — primary axis first, secondary axis second. The primary
    axis is perpendicular to the pair's travel direction, so the spec order
    (original channel, above, below) applies to horizontal pairs and its
    rotated equivalent to vertical ones."""
    xmin, ymin, xmax, ymax = bbox
    gap = CHANNEL_GAP_MM
    axes: list[tuple[bool, float, float]] = [
        (True, ymin - gap, ymax + gap),
        (False, xmin - gap, xmax + gap),
    ]
    if not primary_y:
        axes.reverse()
    candidates = [base]
    for horizontal_spine, lo, hi in axes:
        candidates.append(_dedupe(_spine_detour(p0, p1, horizontal_spine, lo)))
        candidates.append(_dedupe(_spine_detour(p0, p1, horizontal_spine, hi)))
    return candidates


def _base_route(
    source_port: str,
    target_port: str,
    p0: Point,
    p1: Point,
    d0: Point,
    d1: Point,
) -> list[Point]:
    """The v0.1 channel choice, unchanged: straight, Z, dogleg or L."""
    s = STUB_MM

    points: list[Point]

    if _same_axis(source_port, target_port):
        a0 = _add(p0, d0.x * s, d0.y * s)
        b1 = _add(p1, d1.x * s, d1.y * s)
        if d0.x * d1.x + d0.y * d1.y < 0:
            # Ports face each other (e.g. right -> left): straight or Z-shape.
            if math.isclose(p0.y, p1.y, abs_tol=_EPS) or math.isclose(
                p0.x, p1.x, abs_tol=_EPS
            ):
                points = [p0, p1]
            elif d0.x != 0:  # horizontal pair
                mid = (p0.x + p1.x) / 2
                points = [p0, Point(mid, p0.y), Point(mid, p1.y), p1]
            else:  # vertical pair
                mid = (p0.y + p1.y) / 2
                points = [p0, Point(p0.x, mid), Point(p1.x, mid), p1]
        else:
            # Ports face the same way (e.g. right -> right): out-and-around dogleg.
            points = [p0, a0, Point(a0.x, b1.y), b1, p1]
    else:
        # Mixed axes: exit the source stub, one L-turn through the entry stub.
        a0 = _add(p0, d0.x * s, d0.y * s)
        b1 = _add(p1, d1.x * s, d1.y * s)
        if d0.x != 0:
            # source exits horizontally -> go vertical after the stub, then horizontal
            points = [p0, a0, Point(a0.x, b1.y), b1, p1]
        else:
            # source exits vertically -> go horizontal after the stub, then vertical
            points = [p0, a0, Point(b1.x, a0.y), b1, p1]

    return _dedupe(points)


def route_orthogonal(
    source: Node,
    source_port: str,
    target: Node,
    target_port: str,
    obstacles: list[Node] | None = None,
) -> list[Point]:
    """Orthogonal polyline from the source port to the target port.

    Start and end lie exactly on the node boundaries; every segment between
    consecutive points is axis-aligned.

    With ``obstacles``, the base path is checked against every placed node in
    the list (callers exclude source/target themselves; unplaced nodes are
    ignored). On a hit, the fixed-order candidates from ``_candidate_paths``
    are each checked against ALL obstacles and the first clear one wins; if
    none is clear, the original crossing path is returned unchanged for lint
    FC006 to report. Without obstacles the output equals the legacy router's
    exactly.
    """
    p0 = port_point(source, source_port)
    p1 = port_point(target, target_port)
    d0 = _outward(source_port)
    d1 = _outward(target_port)
    base = _base_route(source_port, target_port, p0, p1, d0, d1)

    placed = [ob for ob in (obstacles or []) if ob.is_placed]
    if not placed or _clear_of(base, placed):
        return base

    hitting = [ob for ob in placed if _path_hits(base, ob)]
    bbox = (
        min(ob.x for ob in hitting),
        min(ob.y for ob in hitting),
        max(ob.x + ob.w for ob in hitting),
        max(ob.y + ob.h for ob in hitting),
    )
    for candidate in _candidate_paths(base, p0, p1, bbox, primary_y=d0.x != 0):
        if _clear_of(candidate, placed):
            return candidate
    # No candidate clears every obstacle: keep the crossing path (FC006 reports).
    return base
