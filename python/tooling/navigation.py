from __future__ import annotations

import heapq
import math
from typing import Dict, Iterable, List, Optional, Tuple

# Coarse "village infrastructure" model:
# A connected 2D road grid over the 5km x 5km world.
# Movement tools use this for shortest-route distance instead of straight-line teleport distance.

WORLD_MIN = 0.0
WORLD_MAX = 5000.0

ROAD_GRID_SPACING_M = 250.0
ROAD_GRID_N = int((WORLD_MAX - WORLD_MIN) / ROAD_GRID_SPACING_M) + 1  # 21 nodes along each axis


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _grid_xy(i: int, j: int) -> Tuple[float, float]:
    return (WORLD_MIN + i * ROAD_GRID_SPACING_M, WORLD_MIN + j * ROAD_GRID_SPACING_M)


def _nearest_grid_idx(x: float, y: float) -> Tuple[int, int]:
    i = int(round(_clamp(x, WORLD_MIN, WORLD_MAX) / ROAD_GRID_SPACING_M))
    j = int(round(_clamp(y, WORLD_MIN, WORLD_MAX) / ROAD_GRID_SPACING_M))
    i = max(0, min(ROAD_GRID_N - 1, i))
    j = max(0, min(ROAD_GRID_N - 1, j))
    return i, j


def _neighbors(idx: Tuple[int, int]) -> Iterable[Tuple[int, int]]:
    i, j = idx
    if i > 0:
        yield (i - 1, j)
    if i < ROAD_GRID_N - 1:
        yield (i + 1, j)
    if j > 0:
        yield (i, j - 1)
    if j < ROAD_GRID_N - 1:
        yield (i, j + 1)


def _heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    ax, ay = _grid_xy(a[0], a[1])
    bx, by = _grid_xy(b[0], b[1])
    return math.hypot(ax - bx, ay - by)


def _a_star_grid_distance_m(start: Tuple[int, int], goal: Tuple[int, int]) -> float:
    """
    A* over an unblocked 4-neighbor grid. Edge cost = ROAD_GRID_SPACING_M.
    Returns shortest path length in meters.
    """
    if start == goal:
        return 0.0

    open_heap: List[Tuple[float, Tuple[int, int]]] = []
    heapq.heappush(open_heap, (0.0, start))

    g: Dict[Tuple[int, int], float] = {start: 0.0}
    closed = set()

    while open_heap:
        _, cur = heapq.heappop(open_heap)
        if cur in closed:
            continue
        closed.add(cur)

        if cur == goal:
            return g[cur]

        for nb in _neighbors(cur):
            tentative = g[cur] + ROAD_GRID_SPACING_M
            if tentative < g.get(nb, float("inf")):
                g[nb] = tentative
                f = tentative + _heuristic(nb, goal)
                heapq.heappush(open_heap, (f, nb))

    # Should never happen (grid is connected); fallback to Manhattan on node coords.
    sx, sy = _grid_xy(start[0], start[1])
    gx, gy = _grid_xy(goal[0], goal[1])
    return abs(sx - gx) + abs(sy - gy)


def shortest_route_distance_m(start_xyz: Tuple[float, float, float], end_xyz: Tuple[float, float, float]) -> float:
    """
    Computes approximate shortest-route distance on the road grid plus "last-meter connectors"
    from the actual points to their nearest road nodes.
    Uses only x,y (z ignored) because roads are ground-plane.

    Returns meters (float).
    """
    sx, sy, _sz = start_xyz
    ex, ey, _ez = end_xyz

    s_idx = _nearest_grid_idx(sx, sy)
    e_idx = _nearest_grid_idx(ex, ey)

    s_node_x, s_node_y = _grid_xy(s_idx[0], s_idx[1])
    e_node_x, e_node_y = _grid_xy(e_idx[0], e_idx[1])

    tail = math.hypot(sx - s_node_x, sy - s_node_y)
    head = math.hypot(ex - e_node_x, ey - e_node_y)

    grid_dist = _a_star_grid_distance_m(s_idx, e_idx)
    return float(tail + grid_dist + head)