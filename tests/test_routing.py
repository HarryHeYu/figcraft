"""Orthogonal routing: determinism (constraint 6d) and axis-aligned contracts."""

from __future__ import annotations

import pytest

from papercanvas.core.models import Node
from papercanvas.layout.routing import Point, port_point, route_orthogonal

PORTS = ("left", "right", "top", "bottom")


def make_node(node_id: str, x: float, y: float, w: float = 30.0, h: float = 15.0) -> Node:
    return Node(id=node_id, type="rect", label=node_id, x=x, y=y, w=w, h=h)


def assert_axis_aligned(points: list[Point]) -> None:
    for a, b in zip(points, points[1:], strict=False):
        same_x = a.x == pytest.approx(b.x, abs=1e-9)
        same_y = a.y == pytest.approx(b.y, abs=1e-9)
        assert same_x or same_y, f"diagonal segment ({a.x}, {a.y}) -> ({b.x}, {b.y})"


@pytest.mark.parametrize("source_port", PORTS)
@pytest.mark.parametrize("target_port", PORTS)
def test_every_port_combination_is_axis_aligned(source_port: str, target_port: str) -> None:
    src = make_node("src", 10, 20)
    dst = make_node("dst", 80, 20)
    points = route_orthogonal(src, source_port, dst, target_port)
    assert points[0] == port_point(src, source_port)
    assert points[-1] == port_point(dst, target_port)
    assert len(points) >= 2
    assert_axis_aligned(points)


def test_same_input_same_points() -> None:
    """Constraint 6d: identical inputs yield an identical point sequence."""
    src = make_node("src", 10, 20)
    dst = make_node("dst", 80, 35)
    first = route_orthogonal(src, "right", dst, "left")
    second = route_orthogonal(src.model_copy(deep=True), "right", dst.model_copy(deep=True), "left")
    assert first == second


def test_facing_ports_same_row_give_straight_line() -> None:
    src = make_node("src", 10, 20)
    dst = make_node("dst", 80, 20)
    points = route_orthogonal(src, "right", dst, "left")
    assert points == [port_point(src, "right"), port_point(dst, "left")]


def test_facing_ports_different_rows_zigzag() -> None:
    src = make_node("src", 10, 10)
    dst = make_node("dst", 80, 40)
    points = route_orthogonal(src, "right", dst, "left")
    assert len(points) == 4
    assert_axis_aligned(points)
    # the two interior corners share the same x (the routing channel)
    assert points[1].x == points[2].x
    start, end = points[0], points[-1]
    assert start.y == src.y + src.h / 2  # leaves from the right-side midpoint
    assert end.x == dst.x  # arrives exactly on the target boundary


def test_same_sided_ports_go_around() -> None:
    src = make_node("src", 10, 10)
    dst = make_node("dst", 80, 30)
    points = route_orthogonal(src, "right", dst, "right")
    assert len(points) == 5
    assert_axis_aligned(points)
    assert points[-1] == port_point(dst, "right")


def test_mixed_axes_single_l_turn() -> None:
    src = make_node("src", 10, 20)
    dst = make_node("dst", 60, 60)
    points = route_orthogonal(src, "bottom", dst, "top")
    assert_axis_aligned(points)
    assert points[0] == port_point(src, "bottom")
    assert points[-1] == port_point(dst, "top")


def test_port_point_sits_on_the_boundary() -> None:
    node = make_node("n", 5, 7, w=30, h=10)
    assert port_point(node, "left") == Point(5, 12)
    assert port_point(node, "right") == Point(35, 12)
    assert port_point(node, "top") == Point(20, 7)
    assert port_point(node, "bottom") == Point(20, 17)
