"""A deliberately small OpenSCAD lexer/parser used by :mod:`frontend`.

The parser only builds syntax trees.  It never evaluates source text as Python.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


class ParseError(ValueError):
    def __init__(self, message: str, token: Token):
        super().__init__(f"line {token.line}: {message}")
        self.message = message
        self.line = token.line


class Lexer:
    _number = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
    _name = re.compile(r"[$A-Za-z_][$A-Za-z0-9_]*")

    def __init__(self, source: str):
        self.source = source
        self.i = 0
        self.line = 1
        self.column = 1

    def tokens(self) -> list[Token]:
        result: list[Token] = []
        while self.i < len(self.source):
            c = self.source[self.i]
            if c.isspace():
                self._advance(c)
                continue
            if self.source.startswith("//", self.i):
                while self.i < len(self.source) and self.source[self.i] not in "\r\n":
                    self._advance(self.source[self.i])
                continue
            if self.source.startswith("/*", self.i):
                start = self._token_start()
                self._advance("/")
                self._advance("*")
                while self.i < len(self.source) and not self.source.startswith("*/", self.i):
                    self._advance(self.source[self.i])
                if self.i >= len(self.source):
                    raise ParseError("unterminated comment", Token("comment", "", *start))
                self._advance("*")
                self._advance("/")
                continue
            line, col = self.line, self.column
            if c in "\"'":
                result.append(Token("string", self._string(c), line, col))
                continue
            match = self._number.match(self.source, self.i)
            if match:
                text = match.group(0)
                self._advance_text(text)
                result.append(Token("number", text, line, col))
                continue
            match = self._name.match(self.source, self.i)
            if match:
                text = match.group(0)
                self._advance_text(text)
                result.append(Token("name", text, line, col))
                continue
            found = None
            for operator in ("===", "!==", "<=", ">=", "==", "!=", "&&", "||"):
                if self.source.startswith(operator, self.i):
                    found = operator
                    break
            if found is None:
                found = c
            self._advance_text(found)
            result.append(Token("op", found, line, col))
        result.append(Token("eof", "", self.line, self.column))
        return result

    def _token_start(self) -> tuple[int, int]:
        return self.line, self.column

    def _string(self, quote: str) -> str:
        self._advance(quote)
        chars: list[str] = []
        while self.i < len(self.source):
            c = self.source[self.i]
            if c == quote:
                self._advance(c)
                return "".join(chars)
            if c == "\\":
                self._advance(c)
                if self.i >= len(self.source):
                    break
                escaped = self.source[self.i]
                chars.append({"n": "\n", "r": "\r", "t": "\t"}.get(escaped, escaped))
                self._advance(escaped)
            else:
                chars.append(c)
                self._advance(c)
        raise ParseError("unterminated string", Token("string", "", self.line, self.column))

    def _advance_text(self, text: str) -> None:
        for c in text:
            self._advance(c)

    def _advance(self, c: str) -> None:
        self.i += 1
        if c == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1


@dataclass
class ExprAst:
    kind: str
    value: object
    line: int


@dataclass
class AssignAst:
    name: str
    expr: ExprAst
    line: int


@dataclass
class ModuleAst:
    name: str
    params: list[tuple[str, ExprAst | None]]
    body: list[object]
    line: int


@dataclass
class FunctionAst:
    name: str
    params: list[tuple[str, ExprAst | None]]
    expr: ExprAst
    line: int


@dataclass
class CallAst:
    name: str
    args: list[tuple[str | None, ExprAst]]
    body: list[object] | None
    line: int


@dataclass
class IfAst:
    condition: ExprAst
    then_body: list[object]
    else_body: list[object] | None
    line: int


@dataclass
class AssertAst:
    condition: ExprAst
    message: ExprAst | None
    line: int


@dataclass
class ForAst:
    bindings: list[tuple[str, ExprAst]]
    body: list[object]
    line: int


class Parser:
    _precedence = {
        "||": 1,
        "&&": 2,
        "==": 3,
        "!=": 3,
        "===": 3,
        "!==": 3,
        "<": 4,
        "<=": 4,
        ">": 4,
        ">=": 4,
        "+": 5,
        "-": 5,
        "*": 6,
        "/": 6,
        "%": 6,
        "^": 7,
    }

    def __init__(self, source: str):
        self.tokens = Lexer(source).tokens()
        self.i = 0

    def parse(self) -> list[object]:
        return self._statements(None)

    def _statements(self, end: str | None) -> list[object]:
        result: list[object] = []
        while self.current.text != "" and (end is None or self.current.text != end):
            result.append(self.statement())
        if end is not None:
            self.expect(end)
        return result

    def statement(self) -> object:
        token = self.current
        if token.text == ";":
            self.take()
            return CallAst("__empty__", [], None, token.line)
        if token.kind == "name" and token.text == "module":
            return self.module()
        if token.kind == "name" and token.text == "function":
            return self.function()
        if token.kind == "name" and token.text == "if":
            return self.if_statement()
        if token.kind == "name" and token.text == "for":
            return self.for_statement()
        if token.kind == "name" and token.text == "assert":
            return self.assert_statement()
        if token.kind == "name" and self.peek().text == "=":
            name = self.take()
            self.expect("=")
            expr = self.expression()
            self.expect(";")
            return AssignAst(name.text, expr, name.line)
        call = self.call()
        if call.body is None:
            self.expect(";")
        return call

    def module(self) -> ModuleAst:
        start = self.expect("module")
        name = self.expect_kind("name")
        self.expect("(")
        params: list[tuple[str, ExprAst | None]] = []
        if self.current.text != ")":
            while True:
                param = self.expect_kind("name")
                default = None
                if self.current.text == "=":
                    self.take()
                    default = self.expression()
                params.append((param.text, default))
                if self.current.text != ",":
                    break
                self.take()
        self.expect(")")
        body = self.block()
        return ModuleAst(name.text, params, body, start.line)

    def function(self) -> FunctionAst:
        start = self.expect("function")
        name = self.expect_kind("name")
        params = self.parameters()
        self.expect("=")
        expr = self.expression()
        self.expect(";")
        return FunctionAst(name.text, params, expr, start.line)

    def parameters(self) -> list[tuple[str, ExprAst | None]]:
        self.expect("(")
        params: list[tuple[str, ExprAst | None]] = []
        if self.current.text != ")":
            while True:
                param = self.expect_kind("name")
                default = None
                if self.current.text == "=":
                    self.take()
                    default = self.expression()
                params.append((param.text, default))
                if self.current.text != ",":
                    break
                self.take()
        self.expect(")")
        return params

    def if_statement(self) -> IfAst:
        start = self.expect("if")
        self.expect("(")
        condition = self.expression()
        self.expect(")")
        then_body = self.body()
        else_body = None
        if self.current.text == "else":
            self.take()
            else_body = self.body()
        return IfAst(condition, then_body, else_body, start.line)

    def for_statement(self) -> ForAst:
        start = self.expect("for")
        self.expect("(")
        bindings: list[tuple[str, ExprAst]] = []
        while True:
            name = self.expect_kind("name")
            self.expect("=")
            bindings.append((name.text, self.expression()))
            if self.current.text != ",":
                break
            self.take()
        self.expect(")")
        return ForAst(bindings, self.body(), start.line)

    def assert_statement(self) -> AssertAst:
        start = self.expect("assert")
        self.expect("(")
        condition = self.expression()
        message = None
        if self.current.text == ",":
            self.take()
            message = self.expression()
        self.expect(")")
        self.expect(";")
        return AssertAst(condition, message, start.line)

    def body(self) -> list[object]:
        return self.block() if self.current.text == "{" else [self.statement()]

    def block(self) -> list[object]:
        self.expect("{")
        return self._statements("}")

    def call(self, allow_child: bool = True) -> CallAst:
        name = self.expect_kind("name")
        self.expect("(")
        args: list[tuple[str | None, ExprAst]] = []
        if self.current.text != ")":
            while True:
                arg_name = None
                if self.current.kind == "name" and self.peek().text == "=":
                    arg_name = self.take().text
                    self.expect("=")
                args.append((arg_name, self.expression()))
                if self.current.text != ",":
                    break
                self.take()
        self.expect(")")
        body = self.block() if self.current.text == "{" else None
        # OpenSCAD permits one child without braces: translate(v) cube(1);
        if allow_child and body is None and self.current.text not in {";", "", "}"}:
            body = [self.statement()]
        return CallAst(name.text, args, body, name.line)

    def expression(self, minimum: int = 0) -> ExprAst:
        left = self.prefix()
        while self.current.text == "[":
            token = self.take()
            index = self.expression()
            self.expect("]")
            left = ExprAst("index", (left, index), token.line)
        while True:
            operator = self.current.text
            if operator == "?":
                if 0 < minimum:
                    break
                token = self.take()
                yes = self.expression()
                self.expect(":")
                no = self.expression()
                left = ExprAst("ternary", (left, yes, no), token.line)
                continue
            precedence = self._precedence.get(operator)
            if precedence is None or precedence < minimum:
                break
            self.take()
            right = self.expression(precedence if operator == "^" else precedence + 1)
            left = ExprAst("binary", (operator, left, right), left.line)
        return left

    def prefix(self) -> ExprAst:
        token = self.current
        if token.text == "(":
            self.take()
            value = self.expression()
            self.expect(")")
            return value
        if token.text == "[":
            return self.list_or_range()
        if token.kind == "number":
            self.take()
            value = float(token.text)
            if value.is_integer() and all(c not in token.text for c in ".eE"):
                value = int(value)
            return ExprAst("literal", value, token.line)
        if token.kind == "string":
            self.take()
            return ExprAst("literal", token.text, token.line)
        if token.text in ("+", "-", "!"):
            self.take()
            return ExprAst("unary", (token.text, self.expression(8)), token.line)
        if token.kind == "name":
            self.take()
            if token.text in ("true", "false"):
                return ExprAst("literal", token.text == "true", token.line)
            if token.text == "let" and self.current.text == "(":
                self.i -= 1
                return self.let_expression()
            if self.current.text == "(":
                self.i -= 1
                call = self.call(allow_child=False)
                return ExprAst("function", call, token.line)
            return ExprAst("name", token.text, token.line)
        raise ParseError(f"expected expression, got {token.text!r}", token)

    def list_or_range(self) -> ExprAst:
        start = self.expect("[")
        if self.current.text == "]":
            self.take()
            return ExprAst("list", [], start.line)
        if self.current.text == "for":
            clauses: list[tuple[str, object]] = []
            while self.current.text in {"for", "let"}:
                if self.current.text == "for":
                    self.take()
                    bindings = self.parameters_bindings()
                    clauses.append(("for", bindings))
                else:
                    self.take()
                    clauses.append(("let", self.let_bindings()))
            body = self.expression()
            self.expect("]")
            return ExprAst("comprehension", (clauses, body), start.line)
        first = self.expression()
        if self.current.text == ":":
            self.take()
            second = self.expression()
            if self.current.text == ":":
                self.take()
                end = self.expression()
                self.expect("]")
                return ExprAst("range", (first, second, end), start.line)
            self.expect("]")
            return ExprAst("range", (first, None, second), start.line)
        values = [first]
        while self.current.text == ",":
            self.take()
            values.append(self.expression())
        self.expect("]")
        return ExprAst("list", values, start.line)

    def let_expression(self) -> ExprAst:
        start = self.expect("let")
        bindings = self.let_bindings()
        return ExprAst("let", (bindings, self.expression()), start.line)

    def let_bindings(self) -> list[tuple[str, ExprAst]]:
        self.expect("(")
        bindings: list[tuple[str, ExprAst]] = []
        if self.current.text != ")":
            while True:
                name = self.expect_kind("name")
                self.expect("=")
                bindings.append((name.text, self.expression()))
                if self.current.text != ",":
                    break
                self.take()
        self.expect(")")
        return bindings

    def parameters_bindings(self) -> list[tuple[str, ExprAst]]:
        self.expect("(")
        bindings: list[tuple[str, ExprAst]] = []
        while True:
            name = self.expect_kind("name")
            self.expect("=")
            bindings.append((name.text, self.expression()))
            if self.current.text != ",":
                break
            self.take()
        self.expect(")")
        return bindings

    @property
    def current(self) -> Token:
        return self.tokens[self.i]

    def peek(self) -> Token:
        return self.tokens[min(self.i + 1, len(self.tokens) - 1)]

    def take(self) -> Token:
        token = self.current
        self.i += 1
        return token

    def expect(self, text: str) -> Token:
        if self.current.text != text:
            raise ParseError(f"expected {text!r}, got {self.current.text!r}", self.current)
        return self.take()

    def expect_kind(self, kind: str) -> Token:
        if self.current.kind != kind:
            raise ParseError(f"expected {kind}, got {self.current.text!r}", self.current)
        return self.take()
