"""Small, conservative recovery helpers for sampled planar circles."""

from __future__ import annotations

import math
from typing import Any


_DEFAULT_SAGITTA_MM = 0.02
_FIT_TOLERANCE_MM = 1e-5


def join_tangent_path_curves(curves, tolerance=0.02):
    """Recover a tangent junction obscured by a short sampled bridge chord.

    Only an existing line support exactly tangent to the recovered circle is
    eligible. The recovered junction must lie on the bridge interval within
    the declared sampling tolerance. This operates on an open path.
    """
    result=[dict(c) for c in curves]
    index=0
    while index+2<len(result):
        first,bridge,last=result[index:index+3]
        if bridge['kind']!='line' or {first['kind'],last['kind']}!={'line','arc'}:
            index+=1;continue
        arc=first if first['kind']=='arc' else last
        line=last if first['kind']=='arc' else first
        a,b=(_point_value(line[k]) for k in ('start','end'))
        center=_point_value(arc['center']);dx,dy=b[0]-a[0],b[1]-a[1]
        length2=dx*dx+dy*dy
        if length2<1e-18:index+=1;continue
        factor=((center[0]-a[0])*dx+(center[1]-a[1])*dy)/length2
        tangent=(a[0]+factor*dx,a[1]+factor*dy)
        if (first['kind']=='line' and factor<1) or (last['kind']=='line' and factor>0):
            index+=1;continue
        if abs(math.dist(tangent,center)-arc['radius'].value)>1e-5:
            index+=1;continue
        old=_point_value(arc['end'] if first['kind']=='arc' else arc['start'])
        length=math.sqrt(length2)
        if abs((old[0]-a[0])*dy-(old[1]-a[1])*dx)/length>tolerance:
            index+=1;continue
        start,mid=(_point_value(arc[k]) for k in ('start','mid'))
        turn=math.remainder(math.atan2(mid[1]-center[1],mid[0]-center[0])-math.atan2(start[1]-center[1],start[0]-center[0]),2*math.pi)
        direction=1 if turn>0 else -1
        rx,ry=tangent[0]-center[0],tangent[1]-center[1]
        if abs(turn)<1e-12 or direction*(-ry*dx+rx*dy)/(arc['radius'].value*length)<1-1e-8:
            index+=1;continue
        angle=math.remainder(math.atan2(tangent[1]-center[1],tangent[0]-center[0])-math.atan2(old[1]-center[1],old[0]-center[0]),2*math.pi)
        if abs(angle)>math.radians(15):index+=1;continue
        if (first['kind']=='arc' and angle*direction<0) or (last['kind']=='arc' and angle*direction>0):
            index+=1;continue
        p,q=(_point_value(bridge[k]) for k in ('start','end'))
        vx,vy=q[0]-p[0],q[1]-p[1];span=vx*vx+vy*vy
        if span<1e-18:index+=1;continue
        t=((tangent[0]-p[0])*vx+(tangent[1]-p[1])*vy)/span
        closest=(p[0]+t*vx,p[1]+t*vy)
        if not 0<=t<=1 or math.dist(tangent,closest)>tolerance:
            index+=1;continue
        template=bridge['start']
        joint=tuple(_scalar_like(template[i],tangent[i]) for i in range(2))
        first['end']=joint;last['start']=joint
        result[index:index+3]=[first,last]
        index=max(0,index-1)
    return result


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
            start = best[0]
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
