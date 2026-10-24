"""Orthogonal edge routing — the output contract is a polyline point list.

Engineering constraint 4: the point sequence produced here is THE path.
SVG consumes it as a ``<polyline>``; PPTX (M2) must rebuild it from native
line segments and may not assume a single ELBOW connector reproduces it.
Constraint 6d: the same inputs always produce the same point sequence —
routing is a pure function with no hidden state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from papercanvas.core.models import Node

#: distance (mm) a connector travels straight out of a port before turning
STUB_MM = 4.0

_EPS = 1e-9


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


def route_orthogonal(
    source: Node, source_port: str, target: Node, target_port: str
) -> list[Point]:
    """Orthogonal polyline from the source port to the target port.

    Start and end lie exactly on the node boundaries; every segment between
    consecutive points is axis-aligned.
    """
    p0 = port_point(source, source_port)
    p1 = port_point(target, target_port)
    d0 = _outward(source_port)
    d1 = _outward(target_port)
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
