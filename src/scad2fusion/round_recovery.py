"""Recover explicitly encoded quarter-circle corners from polygon samples."""

from __future__ import annotations

import ast
import math


_SAGITTA_LIMIT_MM = 0.02
_FIT_TOLERANCE_MM = 1e-5


def _ast_key(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _numeric_constant(node: ast.AST):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    return None


def _constant(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return ast.Constant(value=value)


def _simplify(node: ast.AST) -> ast.AST:
    """Fold only safe scalar arithmetic and constant degree-based trig."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _simplify(node.operand)
        number = _numeric_constant(operand)
        if number is not None:
            return _constant(number if isinstance(node.op, ast.UAdd) else -number)
        return ast.UnaryOp(op=node.op, operand=operand)
    if isinstance(node, ast.Call):
        args = [_simplify(argument) for argument in node.args]
        if isinstance(node.func, ast.Name) and node.func.id in {"sin", "cos"} and len(args) == 1 and not node.keywords:
            degrees = _numeric_constant(args[0])
            if degrees is not None:
                quarter_turns = round(degrees / 90)
                if math.isclose(degrees, quarter_turns * 90, abs_tol=1e-12):
                    index = quarter_turns % 4
                    values = (1, 0, -1, 0) if node.func.id == "cos" else (0, 1, 0, -1)
                    return _constant(values[index])
                radians = math.radians(degrees)
                result = math.sin(radians) if node.func.id == "sin" else math.cos(radians)
                return _constant(result)
        if isinstance(node.func, ast.Name) and not node.keywords:
            numbers = [_numeric_constant(argument) for argument in args]
            if all(number is not None for number in numbers):
                functions = {"abs": abs, "ceil": math.ceil, "floor": math.floor,
                             "min": min, "max": max}
                function = functions.get(node.func.id)
                if function is not None:
                    try:
                        return _constant(function(*numbers))
                    except (OverflowError, ValueError):
                        pass
        keywords = [ast.keyword(arg=keyword.arg, value=_simplify(keyword.value)) for keyword in node.keywords]
        return ast.Call(func=node.func, args=args, keywords=keywords)
    if not isinstance(node, ast.BinOp):
        return node

    left, right = _simplify(node.left), _simplify(node.right)
    lhs, rhs = _numeric_constant(left), _numeric_constant(right)
    if lhs is not None and rhs is not None:
        if isinstance(node.op, ast.Add):
            return _constant(lhs + rhs)
        if isinstance(node.op, ast.Sub):
            return _constant(lhs - rhs)
        if isinstance(node.op, ast.Mult):
            return _constant(lhs * rhs)
        if isinstance(node.op, ast.Div) and rhs != 0:
            return _constant(lhs / rhs)
        if isinstance(node.op, ast.FloorDiv) and rhs != 0:
            return _constant(lhs // rhs)
        if isinstance(node.op, ast.Mod) and rhs != 0:
            return _constant(lhs % rhs)
        if isinstance(node.op, ast.Pow) and abs(rhs) <= 32:
            try:
                result = lhs ** rhs
                if isinstance(result, (int, float)) and math.isfinite(result):
                    return _constant(result)
            except (OverflowError, TypeError, ValueError):
                pass
    if isinstance(node.op, ast.Add):
        if lhs == 0:
            return right
        if rhs == 0:
            return left
        if isinstance(right, ast.UnaryOp) and isinstance(right.op, ast.USub):
            return _cancel_add_sub(left, right.operand)
        if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Sub) and _ast_key(left.right) == _ast_key(right):
            return left.left
        if isinstance(right, ast.BinOp) and isinstance(right.op, ast.Sub) and _ast_key(right.right) == _ast_key(left):
            return right.left
    elif isinstance(node.op, ast.Sub):
        if rhs == 0:
            return left
        if lhs == 0:
            return ast.UnaryOp(op=ast.USub(), operand=right)
        if _ast_key(left) == _ast_key(right):
            return _constant(0)
        if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Add):
            if _ast_key(left.right) == _ast_key(right):
                return left.left
            if _ast_key(left.left) == _ast_key(right):
                return left.right
    elif isinstance(node.op, ast.Mult):
        if lhs == 0 or rhs == 0:
            return _constant(0)
        if lhs == 1:
            return right
        if rhs == 1:
            return left
    elif isinstance(node.op, ast.Div):
        if lhs == 0:
            return _constant(0)
        if rhs == 1:
            return left
    return ast.BinOp(left=left, op=node.op, right=right)


def _cancel_add_sub(left: ast.AST, right: ast.AST) -> ast.AST:
    if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Add):
        if _ast_key(left.right) == _ast_key(right):
            return left.left
        if _ast_key(left.left) == _ast_key(right):
            return left.right
    return ast.BinOp(left=left, op=ast.Add(), right=ast.UnaryOp(op=ast.USub(), operand=right))


def _canonical_sharp_scalar(scalar, center: ast.AST, radius: ast.AST, direction: int):
    operation = ast.Add() if direction > 0 else ast.Sub()
    expression = ast.BinOp(left=center, op=operation, right=radius)
    simplified = ast.fix_missing_locations(_simplify(expression))
    return type(scalar)(scalar.value, ast.unparse(simplified))


def _evaluate_number(node: ast.AST, values: dict[str, float]):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        return None
    if isinstance(node, ast.Name):
        value = values.get(node.id)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_number(node.operand, values)
        if value is not None:
            return value if isinstance(node.op, ast.UAdd) else -value
        return None
    if isinstance(node, ast.BinOp):
        left, right = _evaluate_number(node.left, values), _evaluate_number(node.right, values)
        if left is None or right is None:
            return None
        try:
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            elif isinstance(node.op, ast.Div) and right != 0:
                result = left / right
            elif isinstance(node.op, ast.Pow) and abs(right) <= 32:
                result = left ** right
            else:
                return None
        except (OverflowError, TypeError, ValueError, ZeroDivisionError):
            return None
        return result if isinstance(result, (int, float)) and math.isfinite(result) else None
    return None


def _trig_term(node: ast.AST, name: str) -> tuple[ast.AST, ast.AST] | None:
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
        return None
    for radius, trig in ((node.left, node.right), (node.right, node.left)):
        if (isinstance(trig, ast.Call) and isinstance(trig.func, ast.Name)
                and trig.func.id == name and len(trig.args) == 1 and not trig.keywords):
            return radius, trig.args[0]
    return None


def _coordinate_form(text: str, trig_name: str) -> tuple[ast.AST, ast.AST, ast.AST] | None:
    try:
        expression = ast.parse(text, mode="eval").body
    except (SyntaxError, ValueError):
        return None
    if not isinstance(expression, ast.BinOp) or not isinstance(expression.op, ast.Add):
        return None
    for center, term in ((expression.left, expression.right), (expression.right, expression.left)):
        parsed = _trig_term(term, trig_name)
        if parsed is not None:
            radius, angle = parsed
            return center, radius, angle
    return None


def _descriptor(point):
    try:
        x_form = _coordinate_form(point[0].text, "cos")
        y_form = _coordinate_form(point[1].text, "sin")
    except (AttributeError, IndexError, TypeError):
        return None
    if x_form is None or y_form is None:
        return None
    cx, rx, ax = x_form
    cy, ry, ay = y_form
    if _ast_key(rx) != _ast_key(ry) or _ast_key(ax) != _ast_key(ay):
        return None
    return cx, cy, rx, ax


def _contains_trig(point) -> bool:
    try:
        texts = (point[0].text, point[1].text)
        trees = [ast.parse(text, mode="eval") for text in texts]
    except (AttributeError, IndexError, SyntaxError, TypeError, ValueError):
        return False
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id in {"sin", "cos"} for tree in trees for node in ast.walk(tree))


def _fit_circle(points, start: int, end: int):
    samples = points[start:end + 1]
    first = samples[0]
    middle = samples[len(samples) // 2]
    last = samples[-1]
    x1, y1 = first[0].value, first[1].value
    x2, y2 = middle[0].value, middle[1].value
    x3, y3 = last[0].value, last[1].value
    determinant = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(determinant) < 1e-12:
        return None
    q1, q2, q3 = x1 * x1 + y1 * y1, x2 * x2 + y2 * y2, x3 * x3 + y3 * y3
    cx = (q1 * (y2 - y3) + q2 * (y3 - y1) + q3 * (y1 - y2)) / determinant
    cy = (q1 * (x3 - x2) + q2 * (x1 - x3) + q3 * (x2 - x1)) / determinant
    radius = math.hypot(x1 - cx, y1 - cy)
    if radius <= 0 or any(abs(math.hypot(p[0].value - cx, p[1].value - cy) - radius) > _FIT_TOLERANCE_MM
                          for p in samples):
        return None
    angles = [math.atan2(p[1].value - cy, p[0].value - cx) for p in samples]
    increments = [math.remainder(b - a, 2 * math.pi) for a, b in zip(angles, angles[1:])]
    if not increments or any(abs(delta) < 1e-10 for delta in increments):
        return None
    direction = 1 if increments[0] > 0 else -1
    if any(delta * direction <= 0 for delta in increments):
        return None
    sweep = sum(increments)
    if abs(abs(sweep) - math.pi / 2) > 1e-5:
        return None
    max_step = max(abs(delta) for delta in increments)
    sagitta = radius * (1 - math.cos(max_step / 2))
    if sagitta > _SAGITTA_LIMIT_MM:
        return None
    return cx, cy, radius, sagitta


def _axis_tangent(a, b, radial_point, center, tolerance=1e-6):
    dx, dy = b[0].value - a[0].value, b[1].value - a[1].value
    if math.hypot(dx, dy) <= tolerance:
        return None
    if abs(dx) <= tolerance:
        orientation = "vertical"
    elif abs(dy) <= tolerance:
        orientation = "horizontal"
    else:
        return None
    rx, ry = radial_point[0].value - center[0], radial_point[1].value - center[1]
    if abs(dx * rx + dy * ry) > tolerance * max(1.0, math.hypot(dx, dy) * math.hypot(rx, ry)):
        return None
    return orientation


def _recover_run(points, start, end, descriptor, parameter_values):
    if end - start + 1 < 5:
        return None
    fitted = _fit_circle(points, start, end)
    if fitted is None:
        return None
    cx, cy, radius, sagitta = fitted
    prev_index, next_index = (start - 1) % len(points), (end + 1) % len(points)
    incoming = _axis_tangent(points[prev_index], points[start], points[start], (cx, cy))
    outgoing = _axis_tangent(points[end], points[next_index], points[end], (cx, cy))
    if incoming is None or outgoing is None or incoming == outgoing:
        return None
    # The tangent lines meet at one of the two source arc endpoints' coordinate pairs.
    sharp = (points[start][0], points[end][1]) if incoming == "vertical" else (points[end][0], points[start][1])
    center_x, center_y, radius_ast, _ = descriptor
    coefficient = _evaluate_number(radius_ast, parameter_values)
    if coefficient is None or coefficient == 0:
        return None
    offsets = (sharp[0].value - cx, sharp[1].value - cy)
    if any(not math.isclose(abs(offset), radius, rel_tol=1e-7, abs_tol=1e-6) for offset in offsets):
        return None
    try:
        sharp = (
            _canonical_sharp_scalar(sharp[0], center_x, radius_ast,
                                    (1 if offsets[0] > 0 else -1) * (1 if coefficient > 0 else -1)),
            _canonical_sharp_scalar(sharp[1], center_y, radius_ast,
                                    (1 if offsets[1] > 0 else -1) * (1 if coefficient > 0 else -1)),
        )
    except (AttributeError, SyntaxError, TypeError, ValueError):
        return None
    radius_ast = descriptor[2]
    return {
        "start": start,
        "end": end,
        "sharp": sharp,
        "fillet": {
            "position": sharp,
            "radius": {"value": radius, "text": f"abs({ast.unparse(radius_ast)})"},
            "source_segments": end - start,
            "sagitta_mm": sagitta,
        },
    }


def recover_quarter_rounds(points, parameter_values: dict[str, float] | None = None):
    """Return sharp corners and native fillets; ``parameter_values`` resolves radius signs.

    A symbolic radius whose sign cannot be evaluated from the supplied values makes
    the source arc unsupported, because its native fillet radius must be positive.
    """
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        return None
    parameter_values = parameter_values or {}
    descriptors = [_descriptor(point) for point in points]
    if not any(descriptor is not None for descriptor in descriptors):
        return None
    if any(_contains_trig(point) and descriptor is None for point, descriptor in zip(points, descriptors)):
        return None

    runs = []
    index = 0
    while index < len(points):
        descriptor = descriptors[index]
        if descriptor is None:
            index += 1
            continue
        key = tuple(_ast_key(item) for item in descriptor[:3])
        end = index
        while end + 1 < len(points):
            following = descriptors[end + 1]
            if following is None or tuple(_ast_key(item) for item in following[:3]) != key:
                break
            end += 1
        sample_count = end - index + 1
        if sample_count < 5:
            return None
        if sample_count >= 5:
            run = _recover_run(points, index, end, descriptor, parameter_values)
            if run is None:
                return None
            runs.append(run)
        index = end + 1
    if not runs:
        return None
    recovered = []
    run_by_start = {run["start"]: run for run in runs}
    index = 0
    while index < len(points):
        run = run_by_start.get(index)
        if run is None:
            recovered.append(points[index])
            index += 1
        else:
            recovered.append(run["sharp"])
            index = run["end"] + 1
    return {"points": recovered, "fillets": [run["fillet"] for run in runs]}
