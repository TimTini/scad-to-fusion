"""OpenSCAD source frontend producing the symbolic Fusion IR."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any

from .frontend_parser import (
    AssertAst,
    AssignAst,
    CallAst,
    ExprAst,
    FunctionAst,
    ForAst,
    IfAst,
    ModuleAst,
    ParseError,
    Parser,
)
from .model import Expr, Node, Program


class ScadError(ValueError):
    """A source error with a stable ``filename:line`` prefix."""

    def __init__(self, message: str, filename: str = "<string>", line: int = 1):
        self.filename = filename
        self.line = line
        super().__init__(f"{filename}:{line}: {message}")


@dataclass
class _RangeValue:
    start: Expr
    step: Expr
    end: Expr
    values: list[Expr]


def compile_source(
    source: str,
    overrides: dict[str, object] | None = None,
    filename: str = "<string>",
) -> Program:
    """Parse and semantically expand SCAD source into a :class:`Program`."""

    try:
        statements = Parser(source).parse()
        return _Compiler(filename, statements, overrides or {}).compile()
    except ParseError as error:
        raise ScadError(error.message, filename, error.line) from error
    except RecursionError as error:
        raise ScadError("source nesting exceeds supported depth", filename, 1) from error


class _Compiler:
    _MAX_RANGE = 10_000
    _MAX_EXPANDED = 100_000
    _MAX_COMPREHENSION_EXPANDED = 1_000_000
    _MAX_POWER_EXPONENT = 10_000
    _PRIMITIVES = {
        "square",
        "circle",
        "cylinder",
        "cube",
        "sphere",
        "translate",
        "rotate",
        "scale",
        "linear_extrude",
        "offset",
        "union",
        "difference",
        "intersection",
        "polygon",
        "rotate_extrude",
        "polyhedron",
    }

    def __init__(self, filename: str, statements: list[object], overrides: dict[str, object]):
        self.filename = filename
        self.statements = statements
        self.overrides = overrides
        self.assignments: dict[str, ExprAst] = {
            statement.name: statement.expr
            for statement in statements
            if isinstance(statement, AssignAst)
        }
        self.modules: dict[str, ModuleAst] = {
            statement.name: statement
            for statement in statements
            if isinstance(statement, ModuleAst)
        }
        self.functions: dict[str, FunctionAst] = {
            statement.name: statement
            for statement in statements
            if isinstance(statement, FunctionAst)
        }
        self.global_cache: dict[str, Expr | list[Any] | _RangeValue] = {}
        self.global_stack: list[str] = []
        self._module_stack: list[str] = []
        self._function_stack: list[str] = []
        self._expanded = 0
        self._comprehension_expanded = 0
        self._rebuild_parameters: set[str] = set()

    def compile(self) -> Program:
        self._validate_overrides()
        for name in self.assignments:
            self._global_value(name)
        parameters: dict[str, Expr] = {}
        for name in self.assignments:
            if name.startswith("$"):
                continue
            value = self.global_cache[name]
            if isinstance(value, Expr) and isinstance(value.value, (int, float, bool)):
                parameters[name] = value
        geometry_statements = [
            statement
            for statement in self.statements
            if not isinstance(statement, (AssignAst, ModuleAst, FunctionAst))
        ]
        children = self._compile_statements(geometry_statements, {}, {})
        line = children[0].line if children else 1
        return Program(
            parameters,
            Node("union", {}, children, line),
            self.filename,
            frozenset(self._rebuild_parameters),
        )

    def _validate_overrides(self) -> None:
        for name, value in self.overrides.items():
            if name not in self.assignments or name.startswith("$"):
                raise ScadError(f"unknown override {name!r}", self.filename, 1)
            if self._contains_function_call(self.assignments[name]):
                raise ScadError(
                    f"override {name!r} targets a derived binding from function call",
                    self.filename,
                    self.assignments[name].line,
                )
            if self._names_in(self.assignments[name]) & set(self.assignments):
                raise ScadError(
                    f"override {name!r} targets a derived binding; override its base input",
                    self.filename,
                    self.assignments[name].line,
                )
            if not isinstance(value, (int, float, bool, str, list)) or isinstance(value, complex):
                raise ScadError(f"override {name!r} must be scalar or array", self.filename, self.assignments[name].line)
            if isinstance(value, float) and not math.isfinite(value):
                raise ScadError(f"override {name!r} must be finite", self.filename, self.assignments[name].line)
            original = self._eval(self.assignments[name], {}, {}, {})
            if not isinstance(original, (Expr, list)):
                continue
            if isinstance(original, list):
                original_kind = "array"
            elif isinstance(original.value, bool):
                original_kind = "bool"
            elif isinstance(original.value, (int, float)):
                original_kind = "number"
            elif isinstance(original.value, str):
                original_kind = "string"
            else:
                original_kind = "other"
            if isinstance(value, list):
                value_kind = "array"
            elif isinstance(value, bool):
                value_kind = "bool"
            elif isinstance(value, (int, float)):
                value_kind = "number"
            elif isinstance(value, str):
                value_kind = "string"
            else:
                value_kind = "other"
            if original_kind != value_kind:
                raise ScadError(
                    f"override {name!r} type does not match its base binding",
                    self.filename,
                    self.assignments[name].line,
                )

    def _contains_function_call(self, expr: ExprAst) -> bool:
        if expr.kind == "function":
            return True
        if expr.kind in {"literal", "name"}:
            return False
        if expr.kind == "unary":
            return self._contains_function_call(expr.value[1])
        if expr.kind == "binary":
            return self._contains_function_call(expr.value[1]) or self._contains_function_call(expr.value[2])
        if expr.kind == "ternary":
            return any(self._contains_function_call(part) for part in expr.value)
        if expr.kind == "index":
            return self._contains_function_call(expr.value[0]) or self._contains_function_call(expr.value[1])
        if expr.kind == "let":
            bindings, body = expr.value
            return any(self._contains_function_call(value) for _, value in bindings) or self._contains_function_call(body)
        if expr.kind in {"list", "range"}:
            return any(value is not None and self._contains_function_call(value) for value in expr.value)
        if expr.kind == "comprehension":
            clauses, body = expr.value
            return any(
                self._contains_function_call(value)
                for _, values in clauses
                for _, value in values
            ) or self._contains_function_call(body)
        return False

    def _names_in(self, expr: ExprAst) -> set[str]:
        if expr.kind == "name":
            return {str(expr.value)}
        if expr.kind in {"literal"}:
            return set()
        if expr.kind in {"list", "range"}:
            values = expr.value if expr.kind == "list" else expr.value
            result: set[str] = set()
            for value in values:
                if value is not None:
                    result |= self._names_in(value)
            return result
        if expr.kind in {"unary"}:
            return self._names_in(expr.value[1])
        if expr.kind in {"binary"}:
            return self._names_in(expr.value[1]) | self._names_in(expr.value[2])
        if expr.kind == "ternary":
            return self._names_in(expr.value[0]) | self._names_in(expr.value[1]) | self._names_in(expr.value[2])
        if expr.kind == "function":
            return {name for _, arg in expr.value.args for name in self._names_in(arg)}
        if expr.kind == "index":
            return self._names_in(expr.value[0]) | self._names_in(expr.value[1])
        if expr.kind == "let":
            bindings, body = expr.value
            return set().union(*(self._names_in(value) for _, value in bindings), self._names_in(body))
        if expr.kind == "comprehension":
            clauses, body = expr.value
            names = self._names_in(body)
            for kind, values in clauses:
                for _, value in values:
                    names |= self._names_in(value)
            return names
        return set()

    def _global_value(self, name: str) -> Expr | list[Any] | _RangeValue:
        if name in self.global_cache:
            return self.global_cache[name]
        if name in self.global_stack:
            cycle = " -> ".join(self.global_stack + [name])
            line = self.assignments[name].line if name in self.assignments else 1
            raise ScadError(f"cyclic global binding: {cycle}", self.filename, line)
        if name not in self.assignments:
            raise ScadError(f"unknown variable {name!r}", self.filename, 1)
        if name in self.overrides:
            value = self._override_value(self.overrides[name], self.assignments[name].line)
            self.global_cache[name] = value
            return value
        self.global_stack.append(name)
        value = self._eval(self.assignments[name], {}, {}, {})
        self.global_stack.pop()
        self.global_cache[name] = value
        return value

    def _global_ref(self, name: str) -> Expr | list[Any] | _RangeValue:
        value = self._global_value(name)
        if isinstance(value, Expr):
            return Expr(value.value, name, frozenset({name}))
        if isinstance(value, list):
            return value
        raise ScadError(f"global binding {name!r} is not scalar in this position", self.filename, 1)

    def _override_value(self, value: object, line: int) -> Expr | list[Any]:
        if isinstance(value, list):
            return [self._override_value(item, line) for item in value]
        if isinstance(value, (int, float, bool, str)):
            if isinstance(value, float) and not math.isfinite(value):
                raise ScadError("override value must be finite", self.filename, line)
            return _literal(value)
        raise ScadError("override value must be scalar or array", self.filename, line)

    def _eval(
        self,
        expr: ExprAst,
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Expr],
        resolving: tuple[str, ...] = (),
    ) -> Expr | list[Any] | _RangeValue:
        if expr.kind == "literal":
            value = _literal(expr.value)
            self._ensure_finite(value.value, expr.line)
            return value
        if expr.kind == "name":
            name = str(expr.value)
            if name in locals_:
                return locals_[name]
            if name in assignments:
                if name in cache:
                    return cache[name]
                if name in resolving:
                    chain = " -> ".join(resolving + (name,))
                    raise ScadError(f"cyclic local binding: {chain}", self.filename, expr.line)
                value = self._eval(assignments[name], locals_, assignments, cache, resolving + (name,))
                cache[name] = value
                return value
            if name in self.assignments:
                return self._global_ref(name)
            if name in {"PI", "pi"}:
                return _literal(math.pi, name)
            raise ScadError(f"unknown variable {name!r}", self.filename, expr.line)
        if expr.kind == "list":
            values = [self._eval(item, locals_, assignments, cache, resolving) for item in expr.value]
            if not all(_is_vector_value(item) for item in values):
                raise ScadError("nested range/list is not valid in this position", self.filename, expr.line)
            return values
        if expr.kind == "range":
            start_ast, step_ast, end_ast = expr.value
            start = self._scalar(self._eval(start_ast, locals_, assignments, cache, resolving), expr.line)
            end = self._scalar(self._eval(end_ast, locals_, assignments, cache, resolving), expr.line)
            if step_ast is None:
                step = _literal(1 if end.value >= start.value else -1)
            else:
                step = self._scalar(self._eval(step_ast, locals_, assignments, cache, resolving), expr.line)
            if step.value == 0:
                raise ScadError("range step cannot be zero", self.filename, expr.line)
            values = self._range_values(start, step, end, expr.line)
            return _RangeValue(start, step, end, values)
        if expr.kind == "unary":
            operator, child_ast = expr.value
            child = self._scalar(self._eval(child_ast, locals_, assignments, cache, resolving), expr.line)
            if operator == "!":
                return Expr(not bool(child.value), f"!{child.text}", child.deps)
            number = _number(child, expr.line, self.filename)
            return _number_result(-number if operator == "-" else number, f"{operator}{child.text}", child.deps)
        if expr.kind == "binary":
            operator, left_ast, right_ast = expr.value
            left = self._eval(left_ast, locals_, assignments, cache, resolving)
            right = self._eval(right_ast, locals_, assignments, cache, resolving)
            if isinstance(left, list) or isinstance(right, list):
                return self._vector_binary(operator, left, right, expr.line)
            left = self._scalar(left, expr.line)
            right = self._scalar(right, expr.line)
            return self._binary(operator, left, right, expr.line)
        if expr.kind == "index":
            source = self._eval(expr.value[0], locals_, assignments, cache, resolving)
            index = self._scalar(self._eval(expr.value[1], locals_, assignments, cache, resolving), expr.line)
            if not isinstance(source, list):
                raise ScadError("indexing requires an array", self.filename, expr.line)
            number = _number(index, expr.line, self.filename)
            if int(number) != number or not 0 <= int(number) < len(source):
                raise ScadError("array index out of range", self.filename, expr.line)
            return source[int(number)]
        if expr.kind == "let":
            bindings, body = expr.value
            let_locals = dict(locals_)
            let_cache = dict(cache)
            for name, value_ast in bindings:
                let_locals[name] = self._eval(value_ast, let_locals, assignments, let_cache, resolving)
            return self._eval(body, let_locals, assignments, let_cache, resolving)
        if expr.kind == "comprehension":
            clauses, body = expr.value
            return self._comprehension(clauses, body, locals_, assignments, cache, resolving, expr.line)
        if expr.kind == "ternary":
            condition_ast, yes_ast, no_ast = expr.value
            condition = self._scalar(self._eval(condition_ast, locals_, assignments, cache, resolving), expr.line)
            self._rebuild_parameters.update(condition.deps)
            chosen_ast = yes_ast if bool(condition.value) else no_ast
            return self._eval(chosen_ast, locals_, assignments, cache, resolving)
        if expr.kind == "function":
            return self._function(expr.value, locals_, assignments, cache, resolving)
        raise ScadError(f"unsupported expression {expr.kind!r}", self.filename, expr.line)

    def _function(
        self,
        call: CallAst,
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Expr],
        resolving: tuple[str, ...],
    ) -> Expr | list[Any]:
        if any(name is not None for name, _ in call.args):
            raise ScadError(f"named arguments are unsupported for function {call.name}", self.filename, call.line)
        values = [self._eval(arg, locals_, assignments, cache, resolving) for _, arg in call.args]
        if call.name in self.functions:
            if call.name in self._function_stack:
                raise ScadError(f"recursive function call {call.name!r}", self.filename, call.line)
            function = self.functions[call.name]
            if len(values) > len(function.params):
                raise ScadError(f"too many arguments for function {call.name}", self.filename, call.line)
            function_locals: dict[str, Any] = {}
            for index, (name, default) in enumerate(function.params):
                if index < len(values):
                    function_locals[name] = values[index]
                elif default is not None:
                    function_locals[name] = self._eval(default, function_locals, {}, {}, resolving)
                else:
                    raise ScadError(f"missing argument {name!r} for function {call.name}", self.filename, call.line)
            self._function_stack.append(call.name)
            try:
                return self._eval(function.expr, function_locals, {}, {}, resolving)
            finally:
                self._function_stack.pop()
        if call.name == "len":
            if len(values) != 1 or not isinstance(values[0], (list, Expr)):
                raise ScadError("len() expects one array or string", self.filename, call.line)
            if isinstance(values[0], Expr) and not isinstance(values[0].value, str):
                raise ScadError("len() expects one array or string", self.filename, call.line)
            deps = _deps_of(values[0])
            self._rebuild_parameters.update(deps)
            length = len(values[0].value) if isinstance(values[0], Expr) else len(values[0])
            return Expr(length, str(length), deps)
        if call.name == "concat":
            if not all(isinstance(value, list) for value in values):
                raise ScadError("concat() expects arrays", self.filename, call.line)
            result: list[Any] = []
            for value in values:
                result.extend(value)
            return result
        if call.name == "norm":
            if len(values) != 1 or not isinstance(values[0], list) or not all(isinstance(item, Expr) for item in values[0]):
                raise ScadError("norm() expects a numeric vector", self.filename, call.line)
            numbers = [_number(item, call.line, self.filename) for item in values[0]]
            deps = _deps_of(values[0])
            value = 0.0
            for number in numbers:
                value = math.hypot(value, number)
            self._ensure_finite(value, call.line)
            return Expr(value, f"norm({self._text_of(values[0])})", deps)
        if call.name == "str":
            return Expr("".join(_string_value(value) for value in values), f"str({', '.join(self._text_of(value) for value in values)})", _deps_of(values))
        if not all(isinstance(value, Expr) for value in values):
            raise ScadError(f"{call.name}() expects scalar arguments", self.filename, call.line)
        numbers = [_number(value, call.line, self.filename) for value in values]
        deps = frozenset().union(*(value.deps for value in values))
        text = f"{call.name}({', '.join(value.text for value in values)})"
        try:
            if call.name == "floor" and len(numbers) == 1:
                result = math.floor(numbers[0])
            elif call.name == "ceil" and len(numbers) == 1:
                result = math.ceil(numbers[0])
            elif call.name == "abs" and len(numbers) == 1:
                result = abs(numbers[0])
            elif call.name == "round" and len(numbers) == 1:
                result = round(numbers[0])
            elif call.name == "sqrt" and len(numbers) == 1:
                result = math.sqrt(numbers[0])
            elif call.name == "sin" and len(numbers) == 1:
                result = math.sin(math.radians(numbers[0]))
            elif call.name == "cos" and len(numbers) == 1:
                result = math.cos(math.radians(numbers[0]))
            elif call.name == "tan" and len(numbers) == 1:
                result = math.tan(math.radians(numbers[0]))
            elif call.name == "min" and numbers:
                result = min(numbers)
            elif call.name == "max" and numbers:
                result = max(numbers)
            else:
                raise ScadError(f"unsupported function or arity {call.name}()", self.filename, call.line)
        except ValueError as error:
            raise ScadError(f"invalid {call.name}() argument", self.filename, call.line) from error
        self._ensure_finite(result, call.line)
        return Expr(result, text, deps)

    def _binary(self, operator: str, left: Expr, right: Expr, line: int) -> Expr:
        deps = left.deps | right.deps
        text = f"({left.text} {operator} {right.text})"
        if operator in {"&&", "||"}:
            value = bool(left.value) and bool(right.value) if operator == "&&" else bool(left.value) or bool(right.value)
            return Expr(value, text, deps)
        if operator in {"==", "===", "!=", "!==", "<", "<=", ">", ">="}:
            if operator in {"==", "==="}:
                value = left.value == right.value
            elif operator in {"!=", "!=="}:
                value = left.value != right.value
            else:
                try:
                    if operator == "<":
                        value = left.value < right.value
                    elif operator == "<=":
                        value = left.value <= right.value
                    elif operator == ">":
                        value = left.value > right.value
                    else:
                        value = left.value >= right.value
                except TypeError as error:
                    raise ScadError("comparison requires compatible types", self.filename, line) from error
            return Expr(value, text, deps)
        a = _number(left, line, self.filename)
        b = _number(right, line, self.filename)
        if operator == "+":
            value = a + b
        elif operator == "-":
            value = a - b
        elif operator == "*":
            value = a * b
        elif operator == "/":
            if b == 0:
                raise ScadError("division by zero", self.filename, line)
            value = a / b
        elif operator == "%":
            if b == 0:
                raise ScadError("modulo by zero", self.filename, line)
            value = a % b
        elif operator == "^":
            if abs(b) > self._MAX_POWER_EXPONENT:
                raise ScadError("power exponent too large", self.filename, line)
            try:
                value = a**b
            except (ArithmeticError, OverflowError, ValueError) as error:
                raise ScadError("invalid power operation", self.filename, line) from error
        else:
            raise ScadError(f"unsupported operator {operator!r}", self.filename, line)
        self._ensure_finite(value, line)
        return _number_result(value, text, deps)

    def _vector_binary(self, operator: str, left: Any, right: Any, line: int) -> list[Any]:
        if operator not in {"+", "-"} or not isinstance(left, list) or not isinstance(right, list):
            raise ScadError("vector arithmetic requires two equally sized vectors", self.filename, line)
        if len(left) != len(right):
            raise ScadError("vector arithmetic requires equal vector lengths", self.filename, line)
        result: list[Any] = []
        for a, b in zip(left, right):
            if isinstance(a, list) or isinstance(b, list):
                result.append(self._vector_binary(operator, a, b, line))
            elif isinstance(a, Expr) and isinstance(b, Expr):
                result.append(self._binary(operator, a, b, line))
            else:
                raise ScadError("vector arithmetic requires numeric vectors", self.filename, line)
        return result

    def _comprehension(
        self,
        clauses: list[tuple[str, object]],
        body: ExprAst,
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Any],
        resolving: tuple[str, ...],
        line: int,
    ) -> list[Any]:
        result: list[Any] = []

        def visit(index: int, scope: dict[str, Any]) -> None:
            if self._comprehension_expanded >= self._MAX_COMPREHENSION_EXPANDED:
                raise ScadError("list comprehension expansion limit exceeded", self.filename, line)
            if index == len(clauses):
                self._comprehension_expanded += 1
                result.append(self._eval(body, scope, assignments, dict(cache), resolving))
                return
            kind, values = clauses[index]
            if kind == "let":
                let_scope = dict(scope)
                for name, value_ast in values:
                    let_scope[name] = self._eval(value_ast, let_scope, assignments, dict(cache), resolving)
                visit(index + 1, let_scope)
                return
            def bind(rest: list[tuple[str, ExprAst]], current: dict[str, Any]) -> None:
                if not rest:
                    visit(index + 1, current)
                    return
                bind_name, bind_ast = rest[0]
                bind_value = self._eval(bind_ast, current, assignments, dict(cache), resolving)
                self._rebuild_parameters.update(_deps_of(bind_value))
                if isinstance(bind_value, _RangeValue):
                    bind_items = bind_value.values
                elif isinstance(bind_value, list):
                    bind_items = bind_value
                else:
                    raise ScadError("comprehension binding must be an array or range", self.filename, line)
                for bind_item in bind_items:
                    child_scope = dict(current)
                    child_scope[bind_name] = bind_item
                    bind(rest[1:], child_scope)
            bind([(name, value_ast) for name, value_ast in values], scope)
            return

        visit(0, dict(locals_))
        return result

    def _ensure_finite(self, value: object, line: int) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ScadError("numeric value must be finite", self.filename, line)

    def _compile_statements(
        self,
        statements: list[object],
        locals_: dict[str, Any],
        inherited_assignments: dict[str, ExprAst],
        template_mode: bool = False,
    ) -> list[Node]:
        assignments = dict(inherited_assignments)
        assignments.update({s.name: s.expr for s in statements if isinstance(s, AssignAst)})
        cache: dict[str, Expr] = {}
        nodes: list[Node] = []
        for statement in statements:
            if isinstance(statement, (AssignAst, ModuleAst)):
                continue
            if isinstance(statement, AssertAst):
                if template_mode:
                    continue
                condition = self._scalar(self._eval(statement.condition, locals_, assignments, cache), statement.line)
                if not bool(condition.value):
                    message = "assertion failed"
                    if statement.message is not None:
                        message_value = self._scalar(self._eval(statement.message, locals_, assignments, cache), statement.line)
                        message = str(message_value.value)
                    raise ScadError(f"assert: {message}", self.filename, statement.line)
                continue
            if isinstance(statement, IfAst):
                condition = self._scalar(self._eval(statement.condition, locals_, assignments, cache), statement.line)
                self._rebuild_parameters.update(condition.deps)
                branch = statement.then_body if bool(condition.value) else (statement.else_body or [])
                nodes.extend(self._compile_statements(branch, dict(locals_), dict(assignments), template_mode))
                continue
            if isinstance(statement, ForAst):
                nodes.extend(self._compile_for(statement, locals_, assignments, cache, template_mode))
                continue
            if isinstance(statement, CallAst):
                if statement.name == "__empty__":
                    continue
                nodes.extend(self._compile_call(statement, locals_, assignments, cache, template_mode))
                continue
            raise ScadError(f"unsupported statement {type(statement).__name__}", self.filename, 1)
        return nodes

    def _compile_for(
        self,
        statement: ForAst,
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Expr],
        template_mode: bool = False,
    ) -> list[Node]:
        binding_data: list[dict[str, Any] | None] = [None] * len(statement.bindings)
        choices: list[list[Any]] = [[] for _ in statement.bindings]

        def binding_values(index: int, loop_locals: dict[str, Any]) -> list[Any]:
            name, expression = statement.bindings[index]
            value = self._eval(expression, loop_locals, assignments, dict(cache))
            if isinstance(value, _RangeValue):
                values = list(value.values)
                data = {"name": name, "values": values, "start": value.start, "step": value.step, "end": value.end}
            elif isinstance(value, list):
                values = list(value)
                data = {"name": name, "values": values, "start": None, "step": None, "end": None}
            else:
                raise ScadError("for binding must be a list or range", self.filename, statement.line)
            if binding_data[index] is None:
                binding_data[index] = data
                choices[index] = values
            return values
        children: list[Node] = []

        def expand(index: int, loop_locals: dict[str, Any]) -> None:
            if index == len(statement.bindings):
                before_count = len(children)
                children.extend(self._compile_statements(statement.body, loop_locals, dict(assignments), template_mode))
                if not template_mode:
                    self._expanded += len(children) - before_count
                if not template_mode and self._expanded > self._MAX_EXPANDED:
                    raise ScadError("loop expansion limit exceeded", self.filename, statement.line)
                return
            name, _ = statement.bindings[index]
            for choice in binding_values(index, loop_locals):
                next_locals = dict(loop_locals)
                next_locals[name] = choice
                expand(index + 1, next_locals)

        expand(0, dict(locals_))
        for index, data in enumerate(binding_data):
            if data is None:
                name, _ = statement.bindings[index]
                binding_data[index] = {"name": name, "values": [], "start": None, "step": None, "end": None}
        template: Node | None = None
        pattern_safe = False
        if choices and all(
            values
            and all(
                isinstance(value, Expr)
                and isinstance(value.value, (int, float))
                and not isinstance(value.value, bool)
                for value in values
            )
            for values in choices
        ) and not self._loop_has_dependent_bindings(statement.bindings):
            template_locals = dict(locals_)
            for (name, _), choices_for_binding in zip(statement.bindings, choices):
                first = choices_for_binding[0]
                template_locals[name] = Expr(first.value, f"__loop_{name}", frozenset())
            template_nodes = self._compile_statements(
                statement.body, template_locals, dict(assignments), template_mode=True
            )
            template = self._body_node(template_nodes, statement.line)
            pattern_safe = not self._loop_branch_depends_on_binding(statement.body, {name for name, _ in statement.bindings})
        if not children:
            return []
        baseline = dict(locals_)
        for (name, _), choices_for_binding in zip(statement.bindings, choices):
            baseline[name] = choices_for_binding[0]
        probes: list[Node] = []
        if pattern_safe:
            for (name, _), data, choices_for_binding in zip(statement.bindings, binding_data, choices):
                probe_locals = dict(baseline)
                if data["start"] is not None:
                    next_value = _number(data["start"], statement.line, self.filename) + _number(
                        data["step"], statement.line, self.filename
                    )
                    probe_locals[name] = _literal(next_value)
                elif len(choices_for_binding) > 1:
                    probe_locals[name] = choices_for_binding[1]
                probe_nodes = self._compile_statements(statement.body, probe_locals, dict(assignments))
                if len(probe_nodes) == 1:
                    probes.append(probe_nodes[0])
                elif probe_nodes:
                    probes.append(Node("union", {}, probe_nodes, statement.line))
                else:
                    probes.append(Node("union", {}, [], statement.line))
        return [
            Node(
                "for",
                {"bindings": binding_data, "probes": probes, "template": template, "pattern_safe": pattern_safe},
                children,
                statement.line,
            )
        ]

    def _loop_has_dependent_bindings(self, bindings: list[tuple[str, ExprAst]]) -> bool:
        earlier: set[str] = set()
        for name, expression in bindings:
            if self._names_in(expression) & earlier:
                return True
            earlier.add(name)
        return False

    def _body_node(self, nodes: list[Node], line: int) -> Node:
        if len(nodes) == 1:
            return nodes[0]
        return Node("union", {}, nodes, line)

    def _loop_branch_depends_on_binding(self, statements: list[object], bindings: set[str]) -> bool:
        affected = set(bindings)
        local_assignments: dict[str, ExprAst] = {}

        def collect(items: list[object]) -> None:
            for item in items:
                if isinstance(item, AssignAst):
                    local_assignments[item.name] = item.expr
                elif isinstance(item, IfAst):
                    collect(item.then_body)
                    collect(item.else_body or [])
                elif isinstance(item, ForAst):
                    collect(item.body)
                elif isinstance(item, CallAst) and item.body is not None:
                    collect(item.body)

        collect(statements)
        changed = True
        while changed:
            changed = False
            for name, expression in local_assignments.items():
                if name not in affected and self._names_in(expression) & affected:
                    affected.add(name)
                    changed = True

        def expression_has_branch(expression: ExprAst) -> bool:
            if expression.kind == "ternary":
                condition, yes, no = expression.value
                if self._names_in(condition) & affected:
                    return True
                return expression_has_branch(condition) or expression_has_branch(yes) or expression_has_branch(no)
            if expression.kind == "unary":
                return expression_has_branch(expression.value[1])
            if expression.kind == "binary":
                return expression_has_branch(expression.value[1]) or expression_has_branch(expression.value[2])
            if expression.kind == "index":
                return expression_has_branch(expression.value[0]) or expression_has_branch(expression.value[1])
            if expression.kind == "let":
                bindings, body = expression.value
                return any(expression_has_branch(value) for _, value in bindings) or expression_has_branch(body)
            if expression.kind in {"list", "range"}:
                return any(item is not None and expression_has_branch(item) for item in expression.value)
            if expression.kind == "comprehension":
                clauses, body = expression.value
                return any(
                    expression_has_branch(value)
                    for _, values in clauses
                    for _, value in values
                ) or expression_has_branch(body)
            if expression.kind == "function":
                return any(expression_has_branch(arg) for _, arg in expression.value.args)
            return False

        def statements_have_branch(items: list[object]) -> bool:
            for item in items:
                if isinstance(item, AssertAst):
                    return True
                if isinstance(item, AssignAst) and expression_has_branch(item.expr):
                    return True
                if isinstance(item, IfAst):
                    if self._names_in(item.condition) & affected or expression_has_branch(item.condition):
                        return True
                    if statements_have_branch(item.then_body) or statements_have_branch(item.else_body or []):
                        return True
                elif isinstance(item, ForAst):
                    return True
                elif isinstance(item, CallAst):
                    if item.name in self.modules:
                        return True
                    if any(expression_has_branch(argument) for _, argument in item.args):
                        return True
                    if item.body is not None and statements_have_branch(item.body):
                        return True
            return False

        return statements_have_branch(statements)

    def _compile_call(
        self,
        call: CallAst,
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Expr],
        template_mode: bool = False,
    ) -> list[Node]:
        if call.name in self.modules:
            if call.body is not None:
                raise ScadError("module child blocks/children() are unsupported", self.filename, call.line)
            if call.name in self._module_stack:
                raise ScadError(f"recursive module call {call.name!r}", self.filename, call.line)
            if len(self._module_stack) >= 64:
                raise ScadError("module expansion depth limit exceeded", self.filename, call.line)
            module = self.modules[call.name]
            module_locals: dict[str, Any] = {}
            positional = [arg for name, arg in call.args if name is None]
            named: dict[str, ExprAst] = {}
            for name, arg in call.args:
                if name is not None:
                    if name in named:
                        raise ScadError(f"duplicate module argument {name!r}", self.filename, call.line)
                    named[name] = arg
            if len(positional) > len(module.params):
                raise ScadError(f"too many arguments for module {call.name}", self.filename, call.line)
            for index, (name, default) in enumerate(module.params):
                if index < len(positional):
                    value = self._eval(positional[index], locals_, assignments, cache)
                elif name in named:
                    value = self._eval(named.pop(name), locals_, assignments, cache)
                elif default is not None:
                    value = self._eval(default, module_locals, {}, {})
                else:
                    raise ScadError(f"missing argument {name!r} for module {call.name}", self.filename, call.line)
                module_locals[name] = value
            if named:
                raise ScadError(f"unknown module argument {next(iter(named))!r}", self.filename, call.line)
            self._module_stack.append(call.name)
            try:
                return self._compile_statements(module.body, module_locals, {}, template_mode)
            finally:
                self._module_stack.pop()
        if call.name not in self._PRIMITIVES:
            raise ScadError(f"unsupported construct {call.name!r}", self.filename, call.line)
        if call.name in {"union", "difference", "intersection"}:
            args = self._arguments(call, set(), [], locals_, assignments, cache)
            if call.body is None:
                raise ScadError(f"{call.name} requires a block", self.filename, call.line)
            children = self._compile_statements(call.body, dict(locals_), dict(assignments), template_mode)
            return [Node(call.name, args, children, call.line)]
        if call.body is not None and call.name not in {"translate", "rotate", "scale", "linear_extrude", "offset", "rotate_extrude"}:
            raise ScadError(f"{call.name} cannot have a child block", self.filename, call.line)
        args = self._primitive_args(call, locals_, assignments, cache)
        children = []
        if call.body is not None:
            children = self._compile_statements(call.body, dict(locals_), dict(assignments), template_mode)
        return [Node(call.name, args, children, call.line)]

    def _arguments(
        self,
        call: CallAst,
        allowed: set[str],
        positional: list[str],
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Expr],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        index = 0
        for name, expression in call.args:
            if name is None:
                if index >= len(positional):
                    raise ScadError(f"unexpected positional argument for {call.name}", self.filename, call.line)
                name = positional[index]
                index += 1
            if name not in allowed:
                raise ScadError(f"unknown argument {name!r} for {call.name}", self.filename, call.line)
            if name in result:
                raise ScadError(f"duplicate argument {name!r} for {call.name}", self.filename, call.line)
            value = self._eval(expression, locals_, assignments, cache)
            result[name] = value
        return result

    def _primitive_args(
        self,
        call: CallAst,
        locals_: dict[str, Any],
        assignments: dict[str, ExprAst],
        cache: dict[str, Expr],
    ) -> dict[str, Any]:
        name = call.name
        if name == "square":
            args = self._arguments(call, {"size", "center", "$fn"}, ["size", "center"], locals_, assignments, cache)
            args.setdefault("center", _literal(False))
        elif name == "circle":
            args = self._arguments(call, {"r", "d", "$fn"}, ["r"], locals_, assignments, cache)
            if "r" in args and "d" in args:
                raise ScadError("circle cannot use both r and d", self.filename, call.line)
            if "d" in args:
                diameter = args.pop("d")
                args["r"] = _number_result(_number(diameter, call.line, self.filename) / 2, f"({diameter.text} / 2)", diameter.deps)
            if "r" not in args:
                raise ScadError("circle requires r or d", self.filename, call.line)
        elif name == "cylinder":
            args = self._arguments(call, {"h", "r", "d", "r1", "r2", "d1", "d2", "center", "$fn"}, ["h", "r", "center"], locals_, assignments, cache)
            if "h" not in args:
                raise ScadError("cylinder requires h", self.filename, call.line)
            if "d" in args and ("r" in args or "d1" in args or "d2" in args or "r1" in args or "r2" in args):
                raise ScadError("cylinder has conflicting diameter/radius arguments", self.filename, call.line)
            if "d" in args:
                d = args.pop("d")
                args["r1"] = args["r2"] = _number_result(_number(d, call.line, self.filename) / 2, f"({d.text} / 2)", d.deps)
            else:
                if "d1" in args:
                    d1 = args.pop("d1")
                    args["r1"] = _number_result(_number(d1, call.line, self.filename) / 2, f"({d1.text} / 2)", d1.deps)
                if "d2" in args:
                    d2 = args.pop("d2")
                    args["r2"] = _number_result(_number(d2, call.line, self.filename) / 2, f"({d2.text} / 2)", d2.deps)
                if "r" in args:
                    radius = args.pop("r")
                    args["r1"] = args["r2"] = radius
                args.setdefault("r1", _literal(0))
                args.setdefault("r2", args["r1"])
            args.setdefault("center", _literal(False))
        elif name == "cube":
            args = self._arguments(call, {"size", "center", "$fn"}, ["size", "center"], locals_, assignments, cache)
            args.setdefault("center", _literal(False))
        elif name == "sphere":
            args = self._arguments(call, {"r", "d", "$fn"}, ["r"], locals_, assignments, cache)
            if "d" in args:
                d = args.pop("d")
                args["r"] = _number_result(_number(d, call.line, self.filename) / 2, f"({d.text} / 2)", d.deps)
            if "r" not in args:
                raise ScadError("sphere requires r or d", self.filename, call.line)
        elif name == "translate":
            args = self._arguments(call, {"v"}, ["v"], locals_, assignments, cache)
        elif name == "rotate":
            args = self._arguments(call, {"a", "v"}, ["a", "v"], locals_, assignments, cache)
            if "a" not in args:
                raise ScadError("rotate requires a", self.filename, call.line)
        elif name == "scale":
            args = self._arguments(call, {"v"}, ["v"], locals_, assignments, cache)
        elif name == "linear_extrude":
            args = self._arguments(call, {"height", "center", "twist", "scale"}, ["height"], locals_, assignments, cache)
            if "height" not in args:
                raise ScadError("linear_extrude requires height", self.filename, call.line)
            args.setdefault("center", _literal(False))
            args.setdefault("twist", _literal(0))
            args.setdefault("scale", _literal(1))
        elif name == "offset":
            args = self._arguments(call, {"r"}, ["r"], locals_, assignments, cache)
            if "r" not in args:
                raise ScadError("offset requires r", self.filename, call.line)
        elif name == "polygon":
            args = self._arguments(
                call, {"points", "paths", "convexity", "$fn"}, ["points", "paths"], locals_, assignments, cache
            )
            if "points" not in args:
                raise ScadError("polygon requires points", self.filename, call.line)
            if "paths" in args:
                raise ScadError("polygon paths are unsupported", self.filename, call.line)
        elif name == "rotate_extrude":
            args = self._arguments(call, {"angle", "convexity", "$fn"}, ["angle"], locals_, assignments, cache)
            args.setdefault("convexity", _literal(1))
        elif name == "polyhedron":
            args = self._arguments(
                call, {"points", "faces", "triangles", "convexity"}, ["points", "faces"], locals_, assignments, cache
            )
            if "points" not in args or ("faces" not in args and "triangles" not in args):
                raise ScadError("polyhedron requires points and faces", self.filename, call.line)
            if "triangles" in args:
                raise ScadError("polyhedron triangles are unsupported", self.filename, call.line)
            data = args.get("faces", args.get("triangles"))
            deps = _deps_of(args["points"]) | _deps_of(data)
            self._rebuild_parameters.update(deps)
            args["rebuild_dependencies"] = sorted(deps)
            args["coordinate_expressions"] = _coordinate_samples(args["points"])
            args["points"] = _compact_value(args["points"])
            if "faces" in args:
                args["faces"] = _compact_value(args["faces"])
            if "triangles" in args:
                args["triangles"] = _compact_value(args["triangles"])
        else:
            args = {}
        if "$fn" in args:
            args["fn"] = args.pop("$fn")
        elif name in {"square", "circle", "cylinder", "cube", "sphere", "rotate_extrude"} and "$fn" in self.assignments:
            args["fn"] = self._global_ref("$fn")
        return args

    def _scalar(self, value: Expr | list[Any] | _RangeValue, line: int) -> Expr:
        if not isinstance(value, Expr):
            raise ScadError("expected scalar expression", self.filename, line)
        return value

    def _range_values(self, start: Expr, step: Expr, end: Expr, line: int) -> list[Expr]:
        a = _number(start, line, self.filename)
        b = _number(step, line, self.filename)
        z = _number(end, line, self.filename)
        values: list[Expr] = []
        current = a
        for _ in range(self._MAX_RANGE + 1):
            if (b > 0 and current > z) or (b < 0 and current < z):
                return values
            values.append(_literal(current))
            current += b
        raise ScadError("range expansion limit exceeded", self.filename, line)

    def _text_of(self, value: Expr | list[Expr] | _RangeValue) -> str:
        if isinstance(value, Expr):
            return value.text
        if isinstance(value, list):
            return "[" + ", ".join(self._text_of(item) for item in value) + "]"
        return f"[{value.start.text}:{value.step.text}:{value.end.text}]"


def _literal(value: object, text: str | None = None) -> Expr:
    if isinstance(value, bool):
        default = "true" if value else "false"
    elif isinstance(value, int):
        default = str(value)
    elif isinstance(value, float):
        default = format(value, ".15g")
    elif isinstance(value, str):
        default = repr(value)
    else:
        raise TypeError(f"unsupported literal {value!r}")
    return Expr(value, default if text is None else text, frozenset())


def _number(value: Expr, line: int, filename: str) -> int | float:
    if isinstance(value.value, bool) or not isinstance(value.value, (int, float)):
        raise ScadError("expected numeric expression", filename, line)
    if isinstance(value.value, float) and not math.isfinite(value.value):
        raise ScadError("numeric value must be finite", filename, line)
    return value.value


def _number_result(value: int | float, text: str, deps: frozenset[str]) -> Expr:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return Expr(value, text, deps)


def _is_vector_value(value: object) -> bool:
    return isinstance(value, Expr) or (
        isinstance(value, list) and all(_is_vector_value(item) for item in value)
    )


def _deps_of(value: object) -> frozenset[str]:
    if isinstance(value, Expr):
        return value.deps
    if isinstance(value, _RangeValue):
        return value.start.deps | value.step.deps | value.end.deps
    if isinstance(value, list):
        return frozenset().union(*(_deps_of(item) for item in value))
    return frozenset()


def _compact_value(value: object) -> object:
    if isinstance(value, Expr):
        return value.value
    if isinstance(value, list):
        return [_compact_value(item) for item in value]
    return value


def _coordinate_samples(value: object) -> list[list[Expr]]:
    """Retain a small symbolic sample before compacting a large mesh."""
    if not isinstance(value, list) or not value:
        return []
    candidates = [point for point in value if isinstance(point, list) and all(isinstance(item, Expr) for item in point)]
    if not candidates:
        return []
    samples: list[list[Expr]] = [list(candidates[0])]
    if candidates[-1] != candidates[0]:
        samples.append(list(candidates[-1]))
    covered = _deps_of(samples)
    shapes = {_coordinate_shape(point) for point in samples}
    for point in candidates[1:-1]:
        deps = _deps_of(point)
        shape = _coordinate_shape(point)
        if deps - covered or shape not in shapes:
            samples.append(list(point))
            covered |= deps
            shapes.add(shape)
    return samples


def _coordinate_shape(point: list[Expr]) -> tuple[str, ...]:
    return tuple(_expression_shape(item.text) for item in point)


def _expression_shape(text: str) -> str:
    if "^" in text:
        return text
    return re.sub(r"(?<![A-Za-z_$])(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", "#", text)


def _string_value(value: object) -> str:
    if isinstance(value, Expr):
        if isinstance(value.value, bool):
            return "true" if value.value else "false"
        if isinstance(value.value, float) and value.value.is_integer():
            return str(int(value.value))
        return str(value.value)
    if isinstance(value, list):
        return "[" + ", ".join(_string_value(item) for item in value) + "]"
    return str(value)
