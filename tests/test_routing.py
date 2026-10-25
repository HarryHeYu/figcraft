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


# -- deterministic obstacle avoidance ----------------------------------------


def segment_hits_rect(start: Point, end: Point, node: Node) -> bool:
    """Liang-Barsky segment/AABB check against the node rect shrunk by 1e-6
    (boundary contact is not crossing — the lint FC006 semantics). This is a
    deliberate independent copy of the router's rule so a bug in routing.py's
    own hit test cannot hide behind the assertions below."""
    x0, y0 = node.x + 1e-6, node.y + 1e-6
    x1, y1 = node.x + node.w - 1e-6, node.y + node.h - 1e-6
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


def path_hits(points: list[Point], node: Node) -> bool:
    return any(
        segment_hits_rect(a, b, node) for a, b in zip(points, points[1:], strict=False)
    )


def test_no_obstacles_keeps_legacy_paths() -> None:
    """obstacles=None/[] must reproduce the pre-avoidance point lists exactly."""
    straight_a = make_node("a", 10, 20)
    straight_c = make_node("c", 80, 20)
    straight = route_orthogonal(straight_a, "right", straight_c, "left")
    assert straight == [Point(40, 27.5), Point(80, 27.5)]
    assert route_orthogonal(straight_a, "right", straight_c, "left", []) == straight

    zig_src = make_node("src", 10, 10)
    zig_dst = make_node("dst", 80, 40)
    assert route_orthogonal(zig_src, "right", zig_dst, "left") == [
        Point(40, 17.5),
        Point(60, 17.5),
        Point(60, 47.5),
        Point(80, 47.5),
    ]

    dog_src = make_node("d1", 10, 10)
    dog_dst = make_node("d2", 80, 30)
    assert route_orthogonal(dog_src, "right", dog_dst, "right") == [
        Point(40, 17.5),
        Point(44, 17.5),
        Point(44, 37.5),
        Point(114, 37.5),
        Point(110, 37.5),
    ]

    l_src = make_node("l1", 10, 20)
    l_dst = make_node("l2", 60, 60)
    # bottom -> top is a vertical facing pair: straight-or-Z branch, mid y = 47.5
    assert route_orthogonal(l_src, "bottom", l_dst, "top") == [
        Point(25, 35),
        Point(25, 47.5),
        Point(75, 47.5),
        Point(75, 60),
    ]
    # true mixed axes: source exits vertically, one L-turn through the entry stub
    assert route_orthogonal(l_src, "bottom", l_dst, "left") == [
        Point(25, 35),
        Point(25, 39),
        Point(56, 39),
        Point(56, 67.5),
        Point(60, 67.5),
    ]


def test_straight_row_detours_around_middle_obstacle() -> None:
    a = make_node("a", 10, 20)
    b = make_node("b", 45, 20)
    c = make_node("c", 80, 20)
    base = route_orthogonal(a, "right", c, "left")
    assert path_hits(base, b)  # sanity: the straight row really crosses b
    points = route_orthogonal(a, "right", c, "left", [b])
    assert points != base
    assert points[0] == port_point(a, "right")
    assert points[-1] == port_point(c, "left")
    assert_axis_aligned(points)
    assert not path_hits(points, b)


def test_zigzag_channel_obstacle_is_dodged() -> None:
    src = make_node("src", 10, 10)
    dst = make_node("dst", 80, 40)
    ob = make_node("ob", 50, 20, w=20, h=20)
    base = route_orthogonal(src, "right", dst, "left")
    assert path_hits(base, ob)  # the vertical channel crosses ob
    points = route_orthogonal(src, "right", dst, "left", [ob])
    assert points[0] == port_point(src, "right")
    assert points[-1] == port_point(dst, "left")
    assert_axis_aligned(points)
    assert not path_hits(points, ob)


def test_vertical_facing_detours_around_obstacle() -> None:
    src = make_node("src", 35, 20)
    dst = make_node("dst", 35, 80)
    ob = make_node("ob", 35, 45)
    base = route_orthogonal(src, "bottom", dst, "top")
    assert path_hits(base, ob)
    points = route_orthogonal(src, "bottom", dst, "top", [ob])
    assert points[0] == port_point(src, "bottom")
    assert points[-1] == port_point(dst, "top")
    assert_axis_aligned(points)
    assert not path_hits(points, ob)


def test_multiple_obstacles_all_avoided() -> None:
    a = make_node("a", 10, 20)
    c = make_node("c", 80, 20)
    b1 = make_node("b1", 45, 20, w=10)
    b2 = make_node("b2", 60, 20, w=10)
    points = route_orthogonal(a, "right", c, "left", [b1, b2])
    assert_axis_aligned(points)
    assert not path_hits(points, b1)
    assert not path_hits(points, b2)


def test_unavoidable_obstacles_keep_original_path() -> None:
    """Upper and lower detour channels are both blocked: return the crossing
    path unchanged (no crash, no loop) — lint FC006 reports it afterwards."""
    a = make_node("a", 10, 20)
    c = make_node("c", 80, 20)
    blocker = make_node("b1", 45, 25, w=30, h=5)  # sits on the straight row
    above = make_node("b2", 45, 10, w=30, h=12)  # blocks the upper channel
    below = make_node("b3", 45, 34, w=30, h=12)  # blocks the lower channel
    base = route_orthogonal(a, "right", c, "left")
    assert path_hits(base, blocker)
    points = route_orthogonal(a, "right", c, "left", [blocker, above, below])
    assert points == base
    assert path_hits(points, blocker)


def test_unplaced_obstacles_are_ignored() -> None:
    a = make_node("a", 10, 20)
    c = make_node("c", 80, 20)
    ghost = Node(id="ghost", type="rect", label="ghost")  # x/y/w/h all None
    half = Node(id="half", type="rect", label="half", x=45.0, y=20.0, h=15.0)  # w=None
    legacy = route_orthogonal(a, "right", c, "left")
    assert route_orthogonal(a, "right", c, "left", [ghost]) == legacy
    assert route_orthogonal(a, "right", c, "left", [ghost, half]) == legacy


def test_obstacle_routing_is_deterministic() -> None:
    a = make_node("a", 10, 20)
    c = make_node("c", 80, 20)
    b = make_node("b", 45, 20)
    first = route_orthogonal(a, "right", c, "left", [b])
    second = route_orthogonal(
        a.model_copy(deep=True),
        "right",
        c.model_copy(deep=True),
        "left",
        [b.model_copy(deep=True)],
    )
    assert first == second


@pytest.mark.parametrize("source_port", PORTS)
@pytest.mark.parametrize("target_port", PORTS)
def test_port_combinations_with_obstacles_stay_aligned(
    source_port: str, target_port: str
) -> None:
    src = make_node("src", 10, 20)
    dst = make_node("dst", 80, 20)
    # an unrelated node above and below the direct corridor, clear of all
    # legacy base paths so both scenarios must hold simultaneously
    unrelated = [make_node("n1", 45, 45), make_node("n2", 45, 0, h=10)]
    for obstacles in (None, [], unrelated):
        points = route_orthogonal(src, source_port, dst, target_port, obstacles)
        assert points[0] == port_point(src, source_port)
        assert points[-1] == port_point(dst, target_port)
        assert len(points) >= 2
        assert_axis_aligned(points)
        for ob in unrelated:
            assert not path_hits(points, ob)
