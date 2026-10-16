"""Infer length dimensions from use, and render explicit Fusion expressions."""
import ast
import math


def expression_ast(text):
    class Constants(ast.NodeTransformer):
        def visit_Name(self, node):
            values = {'PI': math.pi, 'pi': math.pi, 'true': 1, 'false': 0}
            return ast.Constant(values[node.id]) if node.id in values else node
    return Constants().visit(ast.parse(text.replace('^', '**'), mode='eval').body)


def _combine(a, b, scale=1):
    result = dict(a)
    for name, coefficient in b.items():
        result[name] = result.get(name, 0) + coefficient * scale
    return {name: value for name, value in result.items() if value}


def infer_dimensions(definitions, usages):
    """Solve dimension equations; numbers in additions adopt the other unit."""
    equations = []
    used = {node.id for text, _ in usages for node in ast.walk(expression_ast(text))
            if isinstance(node, ast.Name) and node.id in definitions}
    pending = list(used)
    while pending:
        name = pending.pop()
        for node in ast.walk(expression_ast(definitions[name])):
            if isinstance(node, ast.Name) and node.id in definitions and node.id not in used:
                used.add(node.id)
                pending.append(node.id)

    def dimension(node):
        if isinstance(node, ast.Name):
            if node.id not in definitions:
                raise ValueError('Unknown parameter in dimension expression: ' + node.id)
            return {node.id: 1}
        if isinstance(node, ast.Constant):
            return None  # literal is contextual in sums, dimensionless in products
        if isinstance(node, ast.UnaryOp):
            return dimension(node.operand)
        if isinstance(node, ast.BinOp):
            a, b = dimension(node.left), dimension(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mod)):
                if a is not None and b is not None:
                    equations.append((_combine(a, b, -1), 0))
                return a if a is not None else b
            if isinstance(node.op, ast.Mult):
                return _combine(a or {}, b or {}) if a is not None or b is not None else None
            if isinstance(node.op, ast.Div):
                return _combine(a or {}, b or {}, -1) if a is not None or b is not None else None
            if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
                return {key: value * node.right.value for key, value in a.items()} if a is not None else None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            parts = [dimension(arg) for arg in node.args]
            if node.func.id == 'sqrt' and len(parts)==1:
                return {k:v/2 for k,v in parts[0].items()} if parts[0] is not None else None
            if node.func.id == 'atan2' and len(parts)==2:
                if all(part is not None for part in parts): equations.append((_combine(parts[0],parts[1],-1),0))
                return {}
            if node.func.id in ('floor', 'ceil', 'round', 'sin', 'cos', 'tan'):
                for part in parts:
                    if part is not None:
                        equations.append((part, 0))
                return {} if any(part is not None for part in parts) else None
            if node.func.id in ('min', 'max', 'abs'):
                known = [part for part in parts if part is not None]
                if known:
                    for other in known[1:]:
                        equations.append((_combine(known[0], other, -1), 0))
                    return known[0]
                return None
        raise ValueError('Unsupported dimension expression: ' + ast.dump(node))

    for name, expression in definitions.items():
        part = dimension(expression_ast(expression))
        if part is not None:
            equations.append((_combine({name: 1}, part, -1), 0))
    for text, expected in usages:
        part = dimension(expression_ast(text))
        if part is not None:
            equations.append((part, expected))
    names = list(definitions)
    rows = [[float(eq.get(name, 0)) for name in names] + [float(rhs)] for eq, rhs in equations]
    pivots = []
    row = 0
    for col in range(len(names)):
        pivot = next((i for i in range(row, len(rows)) if abs(rows[i][col]) > 1e-9), None)
        if pivot is None:
            continue
        rows[row], rows[pivot] = rows[pivot], rows[row]
        factor = rows[row][col]
        rows[row] = [value / factor for value in rows[row]]
        for i in range(len(rows)):
            if i != row and abs(rows[i][col]) > 1e-9:
                factor = rows[i][col]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[row])]
        pivots.append((row, col))
        row += 1
    if any(all(abs(v) < 1e-9 for v in r[:-1]) and abs(r[-1]) > 1e-9 for r in rows):
        raise ValueError('Inconsistent parameter dimensions; specify consistent geometric uses')
    free = set(range(len(names))) - {col for _, col in pivots}
    result = {name: 0 for name in names}
    for row, col in pivots:
        if any(abs(rows[row][i]) > 1e-9 for i in free):
            if names[col] in used:
                raise ValueError('Ambiguous dimension for parameter ' + names[col])
            continue  # Inactive branch metadata has no geometric unit in this package.
        exponent = round(rows[row][-1])
        if abs(rows[row][-1] - exponent) > 1e-9 or exponent not in (0, 1):
            raise ValueError('Unsupported dimension for parameter ' + names[col])
        result[names[col]] = exponent
    return result


def fusion_expression(text, dimensions, expected=1):
    """Render only a validated AST; never executes input as Python."""
    def dim(node):
        if isinstance(node, ast.Constant):
            return None
        if isinstance(node, ast.Name):
            return dimensions[node.id]
        if isinstance(node, ast.UnaryOp):
            return dim(node.operand)
        if isinstance(node, ast.BinOp):
            a, b = dim(node.left), dim(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mod)):
                return a if a is not None else b
            if isinstance(node.op, ast.Mult):
                return (a or 0) + (b or 0) if a is not None or b is not None else None
            if isinstance(node.op, ast.Div):
                return (a or 0) - (b or 0) if a is not None or b is not None else None
            if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
                return a * node.right.value if a is not None else None
        if isinstance(node, ast.Call):
            if node.func.id == 'sqrt':
                value=dim(node.args[0])
                return value/2 if value is not None else None
            if node.func.id in ('min', 'max', 'abs'):
                return next((dim(a) for a in node.args if dim(a) is not None), None)
            return 0
        raise ValueError('Unsupported Fusion expression ' + text)

    def render(node, target):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            number = repr(node.value)
            return '(' + number + ' mm)' if target == 1 else number
        if isinstance(node, ast.Name):
            if node.id not in dimensions:
                raise ValueError('Unknown Fusion parameter ' + node.id)
            return node.id
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return '(' + ('-' if isinstance(node.op, ast.USub) else '+') + render(node.operand, target) + ')'
        if isinstance(node, ast.BinOp):
            operators = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.Mod: '%', ast.Pow: '^'}
            symbol = operators.get(type(node.op))
            if symbol is None:
                raise ValueError('Unsupported Fusion expression operator')
            if isinstance(node.op, ast.Pow):
                text = '(' + render(node.left, 0) + ' ^ ' + render(node.right, 0) + ')'
                return '(' + text + ' * (1 mm))' if target == 1 else text
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mod)):
                left = right = target
            else:
                left, right = dim(node.left), dim(node.right)
                if left is None and right is None:
                    left, right = target, 0
                elif left is None:
                    left = target - right if symbol == '*' else target + right
                elif right is None:
                    right = target - left if symbol == '*' else left - target
            return '(' + render(node.left, left) + ' ' + symbol + ' ' + render(node.right, right) + ')'
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if name not in ('min', 'max', 'abs', 'floor', 'ceil', 'round', 'sin', 'cos', 'tan', 'sqrt'):
                raise ValueError('Unsupported Fusion function ' + name)
            argument_dim = 2*target if name=='sqrt' else (target if name in ('min', 'max', 'abs') else 0)
            arguments = [render(a, argument_dim) for a in node.args]
            if name in ('min','max'):
                result = arguments[0]
                for argument in arguments[1:]: result = name + '(' + result + '; ' + argument + ')'
            else:
                result = name + '(' + '; '.join(arguments) + ')'
            if target == 1 and name in ('floor','ceil','round','sin','cos','tan'):
                result = '(' + result + ' * (1 mm))'
            return result
        raise ValueError('Unsupported Fusion expression ' + text)
    return render(expression_ast(text), expected)
