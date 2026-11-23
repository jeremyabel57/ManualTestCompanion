from __future__ import annotations

import ast
import math
import operator
import re
from functools import reduce
from typing import Callable, Mapping


class ExpressionError(ValueError):
    """Raised when an AutoIt-style expression cannot be evaluated safely."""


class UnknownVariableError(ExpressionError):
    pass


_VARIABLE = re.compile(r"\$([A-Za-z_]\w*)")
_WORD = re.compile(r"[A-Za-z_]\w*")


def evaluate_expression(expression: str, variables: Mapping[str, object]) -> object:
    translated = _translate_expression(expression.strip())
    try:
        tree = ast.parse(translated, mode="eval")
    except SyntaxError as error:
        raise ExpressionError(f"invalid expression: {expression!r}") from error
    available = {str(name).lstrip("$").casefold(): value for name, value in variables.items()}
    return _evaluate_node(tree.body, available)


def interpolate_text(text: str, variables: Mapping[str, object]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = evaluate_expression(match.group(1), variables)
        return str(value)

    return re.sub(r"\{([^{}]+)\}", replace, text)


def _translate_expression(expression: str) -> str:
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(expression):
        char = expression[index]
        if quote is not None:
            output.append(char)
            if char == "\\" and index + 1 < len(expression):
                index += 1
                output.append(expression[index])
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(char)
            index += 1
            continue
        if expression.startswith("<>", index):
            output.append("!=")
            index += 2
            continue
        if char == "=" and (index == 0 or expression[index - 1] not in "<>=!") and (
            index + 1 == len(expression) or expression[index + 1] != "="
        ):
            output.append("==")
            index += 1
            continue
        if char == "&":
            output.append("+")
            index += 1
            continue
        if char == "$":
            match = _VARIABLE.match(expression, index)
            if match is None:
                raise ExpressionError(f"invalid variable reference near {expression[index:]!r}")
            output.append(f"__var_{match.group(1).casefold()}")
            index = match.end()
            continue
        word = _WORD.match(expression, index)
        if word is not None:
            value = word.group(0)
            normalized = value.casefold()
            replacements = {
                "and": "and",
                "or": "or",
                "not": "not",
                "true": "True",
                "false": "False",
            }
            output.append(replacements.get(normalized, f"__fn_{normalized}" if normalized in _FUNCTIONS else value))
            index = word.end()
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _evaluate_node(node: ast.AST, variables: Mapping[str, object]) -> object:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool, type(None))):
            return node.value
        raise ExpressionError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id.startswith("__var_"):
            name = node.id[6:].casefold()
            if name not in variables:
                raise UnknownVariableError(f"unknown variable: ${name}")
            return variables[name]
        if node.id.startswith("__fn_"):
            name = node.id[5:]
            if name in _FUNCTIONS:
                return _FUNCTIONS[name]
        name = node.id.casefold()
        if name in variables:
            return variables[name]
        raise UnknownVariableError(f"unknown name: {node.id}")
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, variables)
        right = _evaluate_node(node.right, variables)
        operation = _BINARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise ExpressionError(f"unsupported binary operator: {type(node.op).__name__}")
        return operation(left, right)
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand, variables)
        operation = _UNARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise ExpressionError(f"unsupported unary operator: {type(node.op).__name__}")
        return operation(operand)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: object = True
            for value in node.values:
                result = _evaluate_node(value, variables)
                if not result:
                    return result
            return result
        if isinstance(node.op, ast.Or):
            result = False
            for value in node.values:
                result = _evaluate_node(value, variables)
                if result:
                    return result
            return result
        raise ExpressionError(f"unsupported boolean operator: {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _evaluate_node(node.left, variables)
        for operation_node, comparator in zip(node.ops, node.comparators):
            right = _evaluate_node(comparator, variables)
            operation = _COMPARISON_OPERATORS.get(type(operation_node))
            if operation is None:
                raise ExpressionError(
                    f"unsupported comparison operator: {type(operation_node).__name__}"
                )
            if not operation(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        branch = node.body if _evaluate_node(node.test, variables) else node.orelse
        return _evaluate_node(branch, variables)
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [_evaluate_node(element, variables) for element in node.elts]
        return values if isinstance(node, ast.List) else tuple(values)
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):
            raise ExpressionError("dictionary unpacking is not supported")
        return {
            _evaluate_node(key, variables): _evaluate_node(value, variables)
            for key, value in zip(node.keys, node.values)
        }
    if isinstance(node, ast.Subscript):
        value = _evaluate_node(node.value, variables)
        index = _evaluate_node(node.slice, variables)
        if isinstance(value, dict):
            return value[index]
        if isinstance(value, (str, list, tuple)):
            if not isinstance(index, (int, slice)):
                raise ExpressionError("sequence indexes must be integers or slices")
            return value[index]
        raise ExpressionError("subscript is only supported for strings, lists, tuples, and dictionaries")
    if isinstance(node, ast.Slice):
        return slice(
            _evaluate_node(node.lower, variables) if node.lower is not None else None,
            _evaluate_node(node.upper, variables) if node.upper is not None else None,
            _evaluate_node(node.step, variables) if node.step is not None else None,
        )
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or not node.func.id.startswith("__fn_"):
            raise ExpressionError("only supported built-in functions may be called")
        function = _FUNCTIONS.get(node.func.id[5:])
        if function is None:
            raise ExpressionError(f"unsupported function: {node.func.id[5:]}")
        if node.keywords:
            raise ExpressionError("keyword arguments are not supported")
        arguments = [_evaluate_node(argument, variables) for argument in node.args]
        return function(*arguments)
    raise ExpressionError(f"unsupported expression element: {type(node).__name__}")


def _number(value: object) -> int | float:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 0)
        except ValueError:
            try:
                return float(text)
            except ValueError as error:
                raise ExpressionError(f"not a number: {value!r}") from error
    raise ExpressionError(f"not a number: {value!r}")


def _add(left: object, right: object) -> object:
    if isinstance(left, str) and isinstance(right, str):
        try:
            return _number(left) + _number(right)
        except ExpressionError:
            return left + right
    return _number(left) + _number(right)


def _round(value: object, digits: object = 0) -> int | float:
    places = int(digits)
    factor = 10**places
    scaled = float(_number(value)) * factor
    rounded = math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)
    result = rounded / factor
    return int(result) if places == 0 else result


def _bit_shift(value: object, shift: object) -> int:
    amount = int(shift)
    return int(value) >> amount if amount >= 0 else int(value) << -amount


def _bitwise(function: Callable[[int, int], int], *values: object) -> int:
    if not values:
        raise ExpressionError("bitwise functions require at least one argument")
    return reduce(function, (int(value) for value in values))


def _numeric_binary(function: Callable[[int | float, int | float], object]) -> Callable[[object, object], object]:
    return lambda left, right: function(_number(left), _number(right))


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[object, object], object]] = {
    ast.Add: _add,
    ast.Sub: _numeric_binary(operator.sub),
    ast.Mult: _numeric_binary(operator.mul),
    ast.Div: _numeric_binary(operator.truediv),
    ast.FloorDiv: _numeric_binary(operator.floordiv),
    ast.Mod: _numeric_binary(operator.mod),
    ast.Pow: _numeric_binary(operator.pow),
    ast.BitAnd: lambda left, right: int(left) & int(right),
    ast.BitOr: lambda left, right: int(left) | int(right),
    ast.BitXor: lambda left, right: int(left) ^ int(right),
    ast.LShift: lambda left, right: int(left) << int(right),
    ast.RShift: lambda left, right: int(left) >> int(right),
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[object], object]] = {
    ast.UAdd: lambda value: +_number(value),
    ast.USub: lambda value: -_number(value),
    ast.Not: operator.not_,
    ast.Invert: lambda value: ~int(value),
}
_COMPARISON_OPERATORS: dict[type[ast.cmpop], Callable[[object, object], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: lambda left, right: _number(left) < _number(right),
    ast.LtE: lambda left, right: _number(left) <= _number(right),
    ast.Gt: lambda left, right: _number(left) > _number(right),
    ast.GtE: lambda left, right: _number(left) >= _number(right),
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}
_FUNCTIONS: dict[str, Callable[..., object]] = {
    "abs": lambda value: abs(_number(value)),
    "ceil": lambda value: math.ceil(_number(value)),
    "exp": lambda value: math.exp(_number(value)),
    "floor": lambda value: math.floor(_number(value)),
    "hex": lambda value: format(int(value), "X"),
    "int": lambda value: int(_number(value)),
    "log": lambda value, base=math.e: math.log(_number(value), _number(base)),
    "log10": lambda value: math.log10(_number(value)),
    "max": lambda *values: max(_number(value) for value in values),
    "min": lambda *values: min(_number(value) for value in values),
    "mod": lambda left, right: operator.mod(_number(left), _number(right)),
    "number": _number,
    "round": _round,
    "sqrt": lambda value: math.sqrt(_number(value)),
    "str": str,
    "string": str,
    "bitand": lambda *values: _bitwise(operator.and_, *values),
    "bitor": lambda *values: _bitwise(operator.or_, *values),
    "bitxor": lambda *values: _bitwise(operator.xor, *values),
    "bitshift": _bit_shift,
}
