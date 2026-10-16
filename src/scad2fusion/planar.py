"""Small, dependency-free planar geometry normalizer for the Fusion backend."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Callable, Mapping


def _number_text(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return format(float(value), ".15g")


@dataclass(frozen=True)
class Scalar:
    """A numeric value paired with its symbolic expression."""

    value: float
    text: str | None = None

    def __post_init__(self) -> None:
        numeric = float(self.value)
        if not math.isfinite(numeric):
            raise ValueError("scalar value must be finite")
        object.__setattr__(self, "value", numeric)
        object.__setattr__(self, "text", _number_text(numeric) if self.text is None else str(self.text))

    @classmethod
    def from_ir(cls, value: Scalar | Mapping[str, object] | Real) -> Scalar:
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            if "value" not in value:
                raise ValueError("serialized scalar requires value")
            return cls(value["value"], value.get("text"))  # type: ignore[arg-type]
        if isinstance(value, Real):
            return cls(value)
        raise TypeError(f"expected scalar, got {type(value).__name__}")

    def _literal(self, numeric: float) -> bool:
        return self.text == _number_text(numeric)

    def _other(self, value: Scalar | Real) -> Scalar:
        return Scalar.from_ir(value)

    def __add__(self, other: Scalar | Real) -> Scalar:
        right = self._other(other)
        if self._literal(0):
            return right
        if right._literal(0):
            return self
        return Scalar(self.value + right.value, f"({self.text} + {right.text})")

    def __radd__(self, other: Scalar | Real) -> Scalar:
        return self._other(other) + self

    def __sub__(self, other: Scalar | Real) -> Scalar:
        right = self._other(other)
        if self.text == right.text:
            return Scalar(0)
        if right._literal(0):
            return self
        return Scalar(self.value - right.value, f"({self.text} - {right.text})")

    def __rsub__(self, other: Scalar | Real) -> Scalar:
        return self._other(other) - self

    def __mul__(self, other: Scalar | Real) -> Scalar:
        right = self._other(other)
        if self._literal(0) or right._literal(0):
            return Scalar(0)
        if self._literal(1):
            return right
        if right._literal(1):
            return self
        return Scalar(self.value * right.value, f"({self.text} * {right.text})")

    def __rmul__(self, other: Scalar | Real) -> Scalar:
        return self._other(other) * self

    def __truediv__(self, other: Scalar | Real) -> Scalar:
        right = self._other(other)
        if right.value == 0:
            raise ZeroDivisionError("division by zero")
        if self._literal(0):
            return Scalar(0)
        if right._literal(1):
            return self
        return Scalar(self.value / right.value, f"({self.text} / {right.text})")

    def __rtruediv__(self, other: Scalar | Real) -> Scalar:
        return self._other(other) / self

    def __neg__(self) -> Scalar:
        if self._literal(0):
            return self
        if self._literal(-1):
            return Scalar(1)
        return Scalar(-self.value, f"(-{self.text})")

    def __float__(self) -> float:
        return self.value


Point = tuple[Scalar, Scalar]


@dataclass
class _Shape:
    curves: list[dict[str, object]]
    bounds: tuple[float, float, float, float]
    contains_fn: Callable[[float, float], bool]

    def contains(self, x: float, y: float) -> bool:
        return self.contains_fn(float(x), float(y))


def _scalar(value: object) -> Scalar:
    return Scalar.from_ir(value)  # type: ignore[arg-type]


def _point(value: object) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("planar point must contain exactly two coordinates")
    return (_scalar(value[0]), _scalar(value[1]))


def _vector(value: object, *, name: str, ignore_z: bool = False) -> tuple[Scalar, Scalar]:
    if isinstance(value, (list, tuple)):
        if len(value) not in (2, 3):
            raise ValueError(f"{name} must contain two or three coordinates")
        result = (_scalar(value[0]), _scalar(value[1]))
        if len(value) == 3 and not ignore_z and not _scalar(value[2])._literal(0):
            raise ValueError(f"{name} z coordinate must be zero for planar geometry")
        return result
    scalar = _scalar(value)
    return scalar, scalar


def _curve(kind: str, **values: object) -> dict[str, object]:
    return {"kind": kind, **values}


def _polygon_contains(points: list[Point], x: float, y: float) -> bool:
    inside = False
    for index, first in enumerate(points):
        second = points[(index + 1) % len(points)]
        x1, y1 = first[0].value, first[1].value
        x2, y2 = second[0].value, second[1].value
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) <= 1e-9 and min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9:
            return True
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def _bounds(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [point[0].value for point in points]
    ys = [point[1].value for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _validate_polygon(points: list[Point]) -> None:
    if len(points) < 3:
        raise ValueError("polygon requires at least three points")
    area = sum(
        points[i][0].value * points[(i + 1) % len(points)][1].value
        - points[(i + 1) % len(points)][0].value * points[i][1].value
        for i in range(len(points))
    )
    if abs(area) <= 1e-9:
        raise ValueError("polygon must have nonzero area")
    for i, first in enumerate(points):
        first_end = points[(i + 1) % len(points)]
        for j in range(i + 1, len(points)):
            if j in (i, (i - 1) % len(points), (i + 1) % len(points)):
                continue
            second = points[j]
            second_end = points[(j + 1) % len(points)]
            if _segments_intersect(first, first_end, second, second_end):
                raise ValueError("polygon must be simple")


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0].value - p[0].value) * (r[1].value - p[1].value) - (q[1].value - p[1].value) * (r[0].value - p[0].value)

    values = (orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b))
    return values[0] * values[1] < -1e-12 and values[2] * values[3] < -1e-12


def _polygon_shape(points: list[Point]) -> _Shape:
    _validate_polygon(points)
    curves = [_curve("line", start=points[i], end=points[(i + 1) % len(points)]) for i in range(len(points))]
    return _Shape(curves, _bounds(points), lambda x, y: _polygon_contains(points, x, y))


def _circle_shape(center: Point, radius: Scalar, fn: Scalar | None) -> _Shape:
    if radius.value <= 0:
        raise ValueError("circle radius must be positive")
    if fn is not None and fn.value <= 12:
        count = int(fn.value)
        if count != fn.value or count < 3:
            raise ValueError("fn must be an integer of at least 3")
        points = [
            (
                center[0] + radius * math.cos(2 * math.pi * i / count),
                center[1] + radius * math.sin(2 * math.pi * i / count),
            )
            for i in range(count)
        ]
        return _polygon_shape(points)
    cx, cy, r = center[0].value, center[1].value, radius.value
    curves = [_curve("circle", center=center, radius=radius)]
    return _Shape(curves, (cx - r, cy - r, cx + r, cy + r), lambda x, y: (x - cx) ** 2 + (y - cy) ** 2 <= r * r + 1e-9)


def _square_shape(size: object, center: object) -> _Shape:
    if isinstance(size, (list, tuple)):
        if len(size) != 2:
            raise ValueError("square size must contain two coordinates")
        width, height = _scalar(size[0]), _scalar(size[1])
    else:
        width = height = _scalar(size)
    if width.value <= 0 or height.value <= 0:
        raise ValueError("square dimensions must be positive")
    cx = width * 0
    cy = height * 0
    if bool(_scalar(center).value):
        cx, cy = -width / 2, -height / 2
    points = [(cx, cy), (cx + width, cy), (cx + width, cy + height), (cx, cy + height)]
    return _polygon_shape(points)


def _rounded_square_shape(square: _Shape, radius: Scalar) -> _Shape:
    if radius.value < 0:
        raise ValueError("negative offset is unsupported")
    if radius.value == 0:
        return square
    if len(square.curves) != 4 or any(curve["kind"] != "line" for curve in square.curves):
        raise ValueError("offset currently supports square only")
    points = [curve["start"] for curve in square.curves]
    min_x, min_y, max_x, max_y = square.bounds
    width, height = max_x - min_x, max_y - min_y
    if radius.value * 2 > min(width, height):
        raise ValueError("offset radius must fit inside the square dimensions")
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2
    half_w, half_h = width / 2, height / 2
    # Keep the original Scalar coordinates. Rebuilding these from numeric
    # bounds would discard expressions such as ``L - 2 * R`` before Fusion
    # receives the contour.
    left, bottom = points[0]
    right = points[1][0]
    top = points[2][1]
    outer_left, outer_right = left - radius, right + radius
    outer_bottom, outer_top = bottom - radius, top + radius
    r = radius
    diagonal = r * math.sqrt(0.5)
    corners = [
        (right, bottom),
        (right, top),
        (left, top),
        (left, bottom),
    ]
    centers = corners
    p = [
        (outer_left, outer_bottom),
        (outer_right, outer_bottom),
        (outer_right, outer_top),
        (outer_left, outer_top),
    ]
    curves: list[dict[str, object]] = []
    curves.append(_curve("line", start=(p[0][0] + r, p[0][1]), end=(p[1][0] - r, p[1][1])))
    curves.append(_curve("arc", start=(p[1][0] - r, p[1][1]), mid=(centers[0][0] + diagonal, centers[0][1] - diagonal), end=(p[1][0], p[1][1] + r), radius=r))
    curves.append(_curve("line", start=(p[1][0], p[1][1] + r), end=(p[2][0], p[2][1] - r)))
    curves.append(_curve("arc", start=(p[2][0], p[2][1] - r), mid=(centers[1][0] + diagonal, centers[1][1] + diagonal), end=(p[2][0] - r, p[2][1]), radius=r))
    curves.append(_curve("line", start=(p[2][0] - r, p[2][1]), end=(p[3][0] + r, p[3][1])))
    curves.append(_curve("arc", start=(p[3][0] + r, p[3][1]), mid=(centers[2][0] - diagonal, centers[2][1] + diagonal), end=(p[3][0], p[3][1] - r), radius=r))
    curves.append(_curve("line", start=(p[3][0], p[3][1] - r), end=(p[0][0], p[0][1] + r)))
    curves.append(_curve("arc", start=(p[0][0], p[0][1] + r), mid=(centers[3][0] - diagonal, centers[3][1] - diagonal), end=(p[0][0] + r, p[0][1]), radius=r))
    min_x -= radius.value
    min_y -= radius.value
    max_x += radius.value
    max_y += radius.value
    inner_w, inner_h = width / 2, height / 2

    def contains(x: float, y: float) -> bool:
        ax, ay = abs(x - cx), abs(y - cy)
        if (ax <= inner_w or ay <= inner_h) and ax <= width / 2 and ay <= height / 2:
            return True
        dx = max(ax - inner_w, 0.0)
        dy = max(ay - inner_h, 0.0)
        return dx * dx + dy * dy <= radius.value * radius.value + 1e-9

    return _Shape(curves, (min_x, min_y, max_x, max_y), contains)


def _combine(shapes: list[_Shape], operation: str) -> _Shape:
    if not shapes:
        return _Shape([], (0.0, 0.0, 0.0, 0.0), lambda _x, _y: False)
    curves = [curve for shape in shapes for curve in shape.curves]
    if operation == "union":
        bounds = (min(s.bounds[0] for s in shapes), min(s.bounds[1] for s in shapes), max(s.bounds[2] for s in shapes), max(s.bounds[3] for s in shapes))
        return _Shape(curves, bounds, lambda x, y: any(s.contains(x, y) for s in shapes))
    if operation == "difference":
        first = shapes[0]
        return _Shape(curves, first.bounds, lambda x, y: first.contains(x, y) and all(not s.contains(x, y) for s in shapes[1:]))
    if operation == "intersection":
        bounds = (max(s.bounds[0] for s in shapes), max(s.bounds[1] for s in shapes), min(s.bounds[2] for s in shapes), min(s.bounds[3] for s in shapes))
        return _Shape(curves, bounds, lambda x, y: all(s.contains(x, y) for s in shapes))
    raise ValueError(f"unsupported planar op: {operation}")


def _transform_shape(shape: _Shape, transform: Callable[[Point], Point], inverse: Callable[[float, float], tuple[float, float]], *, curved_scale: bool = False) -> _Shape:
    def transform_value(point: Point) -> Point:
        return transform(point)

    curves: list[dict[str, object]] = []
    for curve in shape.curves:
        copied = dict(curve)
        for key in ("start", "mid", "end", "center"):
            if key in copied:
                copied[key] = transform_value(copied[key])  # type: ignore[arg-type]
        if "radius" in copied and curved_scale:
            copied["radius"] = copied["radius"] * 1  # preserve Scalar type
        curves.append(copied)
    corners = [
        (Scalar(shape.bounds[0]), Scalar(shape.bounds[1])),
        (Scalar(shape.bounds[0]), Scalar(shape.bounds[3])),
        (Scalar(shape.bounds[2]), Scalar(shape.bounds[1])),
        (Scalar(shape.bounds[2]), Scalar(shape.bounds[3])),
    ]
    transformed_corners = [transform_value(corner) for corner in corners]
    bounds = _bounds(transformed_corners)
    return _Shape(curves, bounds, lambda x, y: shape.contains(*inverse(x, y)))


def _rotation(angle: Scalar) -> tuple[Scalar, Scalar]:
    radians = math.radians(angle.value)
    if angle._literal(angle.value):
        return Scalar(math.cos(radians)), Scalar(math.sin(radians))
    return Scalar(math.cos(radians), f"cos({angle.text})"), Scalar(math.sin(radians), f"sin({angle.text})")


def _scale_abs(value: Scalar) -> Scalar:
    if value._literal(value.value):
        return Scalar(abs(value.value))
    return Scalar(abs(value.value), f"abs({value.text})")


def _build(node: Mapping[str, object]) -> _Shape:
    op = node.get("op")
    args = node.get("args") or {}
    children = node.get("children") or []
    if not isinstance(args, Mapping) or not isinstance(children, list):
        raise TypeError("serialized node must contain args mapping and children list")
    if op == "square":
        return _square_shape(args.get("size"), args.get("center", False))
    if op == "circle":
        return _circle_shape((Scalar(0), Scalar(0)), _scalar(args.get("r")), _scalar(args["fn"]) if "fn" in args else None)
    if op == "cylinder":
        r1, r2 = _scalar(args.get("r1", args.get("r"))), _scalar(args.get("r2", args.get("r1", args.get("r"))))
        if abs(r1.value - r2.value) > 1e-9:
            raise ValueError("planar cylinder requires equal r1 and r2")
        return _circle_shape((Scalar(0), Scalar(0)), r1, _scalar(args["fn"]) if "fn" in args else None)
    if op == "polygon":
        return _polygon_shape([_point(value) for value in args.get("points", [])])
    if op in {"union", "difference", "intersection", "for"}:
        return _combine([_build(child) for child in children], "union" if op == "for" else op)
    if op == "offset":
        if len(children) != 1:
            raise ValueError("offset requires one child")
        return _rounded_square_shape(_build(children[0]), _scalar(args.get("r")))
    if op == "translate":
        if len(children) != 1:
            raise ValueError("translate requires one child")
        dx, dy = _vector(args.get("v"), name="translate vector")
        child = _build(children[0])
        return _transform_shape(child, lambda p: (p[0] + dx, p[1] + dy), lambda x, y: (x - dx.value, y - dy.value))
    if op == "rotate":
        if len(children) != 1:
            raise ValueError("rotate requires one child")
        angle = args.get("a")
        if isinstance(angle, (list, tuple)):
            if len(angle) != 3 or not _scalar(angle[0])._literal(0) or not _scalar(angle[1])._literal(0):
                raise ValueError("only Z rotation is supported for planar geometry")
            angle = angle[2]
        angle = _scalar(angle)
        cosine, sine = _rotation(angle)
        child = _build(children[0])
        return _transform_shape(child, lambda p: (p[0] * cosine - p[1] * sine, p[0] * sine + p[1] * cosine), lambda x, y: (x * cosine.value + y * sine.value, -x * sine.value + y * cosine.value))
    if op == "scale":
        if len(children) != 1:
            raise ValueError("scale requires one child")
        sx, sy = _vector(args.get("v"), name="scale vector", ignore_z=True)
        child = _build(children[0])
        if any(curve["kind"] in {"circle", "arc"} for curve in child.curves) and abs(abs(sx.value) - abs(sy.value)) > 1e-9:
            raise ValueError("uniform scale is required for curved primitives")
        if sx.value == 0 or sy.value == 0:
            raise ValueError("scale coordinates must be nonzero")
        return _transform_shape(child, lambda p: (p[0] * sx, p[1] * sy), lambda x, y: (x / sx.value, y / sy.value))
    if op == "linear_extrude":
        if len(children) != 1:
            raise ValueError("linear_extrude requires one child")
        twist = _scalar(args.get("twist", 0))
        extrude_scale = _scalar(args.get("scale", 1))
        if abs(twist.value) > 1e-9 or abs(extrude_scale.value - 1) > 1e-9:
            raise ValueError("linear_extrude twist/scale are outside planar profile normalization")
        return _build(children[0])
    raise ValueError(f"unsupported planar op: {op}")


class Region:
    """Normalized planar contours plus a numeric recursive CSG membership test."""

    def __init__(self, node: Mapping[str, object]):
        if not isinstance(node, Mapping):
            raise TypeError("Region expects a serialized Node mapping")
        shape = _build(node)
        self.curves = shape.curves
        self.bounds = shape.bounds
        self._contains = shape.contains

    def contains(self, x: float, y: float) -> bool:
        return self._contains(x, y)
