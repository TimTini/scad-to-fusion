"""Small, conservative recovery helpers for sampled planar circles."""

from __future__ import annotations

import math
from typing import Any


_DEFAULT_SAGITTA_MM = 0.02
_FIT_TOLERANCE_MM = 1e-5


def _point_value(point: tuple[Any, Any]) -> tuple[float, float]:
    return point[0].value, point[1].value


def _scalar_like(template: Any, value: float) -> Any:
    return type(template)(value)


def _fit_planar_circle(points: list[tuple[Any, Any]], start: int, end: int):
    samples = points[start:end + 1]
    if len(samples) < 3:
        return None
    first = _point_value(samples[0])
    middle = _point_value(samples[len(samples) // 2])
    last = _point_value(samples[-1])
    x1, y1 = first
    x2, y2 = middle
    x3, y3 = last
    determinant = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(determinant) <= 1e-12:
        return None
    q1, q2, q3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    cx = (q1 * (y2 - y3) + q2 * (y3 - y1) + q3 * (y1 - y2)) / determinant
    cy = (q1 * (x3 - x2) + q2 * (x1 - x3) + q3 * (x2 - x1)) / determinant
    radius = math.hypot(x1 - cx, y1 - cy)
    if radius <= 1e-12:
        return None
    tolerance = max(_FIT_TOLERANCE_MM, radius * 1e-7)
    if any(abs(math.hypot(point[0].value - cx, point[1].value - cy) - radius) > tolerance
           for point in samples):
        return None
    angles = [math.atan2(point[1].value - cy, point[0].value - cx) for point in samples]
    steps = [math.remainder(b - a, 2 * math.pi) for a, b in zip(angles, angles[1:])]
    if not steps or any(abs(step) <= 1e-10 for step in steps):
        return None
    direction = 1 if steps[0] > 0 else -1
    if any(step * direction <= 0 for step in steps):
        return None
    sweep = sum(steps)
    if abs(sweep) >= 2 * math.pi - 1e-7:
        return None
    return cx, cy, radius, direction, sweep, max(abs(step) for step in steps)


def _full_circle(points: list[tuple[Any, Any]], sagitta_limit: float):
    if len(points) < 4:
        return None
    fitted = _fit_planar_circle(points, 0, len(points) - 1)
    if fitted is None:
        # The last sample may be near the first sample; fit with a non-adjacent
        # triple and validate the complete ring below.
        first, middle, last = points[0], points[len(points) // 3], points[(2 * len(points)) // 3]
        fitted = _fit_planar_circle([first, middle, last], 0, 2)
        if fitted is None:
            return None
        cx, cy, radius = fitted[:3]
    else:
        cx, cy, radius = fitted[:3]
    angles = [math.atan2(point[1].value - cy, point[0].value - cx) for point in points]
    steps = [math.remainder(b - a, 2 * math.pi) for a, b in zip(angles, angles[1:] + angles[:1])]
    if not steps or any(abs(step) <= 1e-10 for step in steps):
        return None
    direction = 1 if steps[0] > 0 else -1
    if any(step * direction <= 0 for step in steps):
        return None
    if abs(sum(steps)) < 2 * math.pi - 1e-6:
        return None
    tolerance = max(_FIT_TOLERANCE_MM, radius * 1e-7)
    if any(abs(math.hypot(point[0].value - cx, point[1].value - cy) - radius) > tolerance
           for point in points):
        return None
    sagitta = radius * (1 - math.cos(max(abs(step) for step in steps) / 2))
    if sagitta > sagitta_limit + 1e-12:
        return None
    template = points[0][0]
    return {
        "kind": "circle",
        "center": (_scalar_like(template, cx), _scalar_like(points[0][1], cy)),
        "radius": _scalar_like(template, radius),
        "sagitta_mm": sagitta,
    }


def _arc_curve(points: list[tuple[Any, Any]], start: int, end: int, fitted):
    cx, cy, radius, direction, sweep, max_step = fitted
    start_angle = math.atan2(points[start][1].value - cy, points[start][0].value - cx)
    mid_angle = start_angle + direction * abs(sweep) / 2
    template = points[start][0]
    mid = (
        _scalar_like(template, cx + radius * math.cos(mid_angle)),
        _scalar_like(points[start][1], cy + radius * math.sin(mid_angle)),
    )
    return {
        "kind": "arc",
        "start": points[start],
        "mid": mid,
        "end": points[end],
        "center": (_scalar_like(template, cx), _scalar_like(points[start][1], cy)),
        "radius": _scalar_like(template, radius),
        "sagitta_mm": radius * (1 - math.cos(max_step / 2)),
    }


def recover_polygon_curves(points: list[tuple[Any, Any]], sagitta_limit: float = _DEFAULT_SAGITTA_MM):
    """Recover sufficiently sampled circular runs while retaining line corners.

    The input is a closed polygon represented without a repeated terminal point.
    Runs need at least four vertices and every chord's circle sagitta must be at
    most ``sagitta_limit``.  A full ring is represented by one ``circle`` curve;
    all other recovered runs become ``arc`` curves.  Returning line curves for
    unsupported/coarse samples is deliberate and keeps polygon fidelity safe.
    """
    if sagitta_limit <= 0 or not math.isfinite(sagitta_limit):
        raise ValueError("sagitta limit must be positive and finite")
    cleaned = []
    for point in points:
        if not cleaned or math.dist(_point_value(point), _point_value(cleaned[-1])) > 1e-10:
            cleaned.append(point)
    if len(cleaned) > 1 and math.dist(_point_value(cleaned[-1]), _point_value(cleaned[0])) <= 1e-10:
        cleaned.pop()
    points = cleaned
    if len(points) < 3:
        return None
    circle = _full_circle(points, sagitta_limit)
    if circle is not None:
        return [circle]

    runs: dict[int, tuple[int, tuple[float, float, float, int, float, float]]] = {}
    start = 0
    while start < len(points) - 3:
        best = None
        for end in range(start + 3, len(points)):
            fitted = _fit_planar_circle(points, start, end)
            if fitted is None:
                break
            sagitta = fitted[2] * (1 - math.cos(fitted[-1] / 2))
            if sagitta > sagitta_limit + 1e-12:
                break
            best = (end, fitted)
        if best is not None:
            runs[start] = best
            start = best[0] + 1
        else:
            start += 1

    curves = []
    index = 0
    while index < len(points):
        run = runs.get(index)
        if run is not None:
            end, fitted = run
            curves.append(_arc_curve(points, index, end, fitted))
            index = end
            continue
        else:
            curves.append({"kind": "line", "start": points[index], "end": points[(index + 1) % len(points)]})
        index += 1
    return curves
