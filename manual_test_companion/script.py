from __future__ import annotations

import re
import threading
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .expressions import evaluate_expression, interpolate_text
from .modbus import ModbusTcpClient
from .visa import InstrumentSession


class ScriptError(RuntimeError):
    """Raised when a script is invalid or cannot be executed."""


class ScriptCancelled(ScriptError):
    """Raised when script execution is cancelled."""


class _VisaTransport(Protocol):
    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


class _ModbusTransport(Protocol):
    def read_value(self, address: int, format_string: str) -> int | float | str: ...

    def write_value(
        self, address: int, value: int | float | str, format_string: str
    ) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class _Command:
    line: int
    text: str


@dataclass(frozen=True)
class _If:
    line: int
    condition: str
    body: tuple[Statement, ...]
    otherwise: tuple[Statement, ...]


@dataclass(frozen=True)
class _While:
    line: int
    condition: str
    body: tuple[Statement, ...]


@dataclass(frozen=True)
class _DoUntil:
    line: int
    body: tuple[Statement, ...]
    condition: str


@dataclass(frozen=True)
class _Python:
    line: int
    mode: str
    source: str


Statement = _Command | _If | _While | _DoUntil | _Python
_ASSIGNMENT = re.compile(r"^\$([A-Za-z_]\w*)\s*=\s*(.+)$")
_VARIABLE_NAME = re.compile(r"^\$?([A-Za-z_]\w*)$")


class ScriptRunner:
    """Run the synchronous AutoIt DSL subset, including explicit Python code."""

    def __init__(
        self,
        visa: _VisaTransport | InstrumentSession | None = None,
        modbus: _ModbusTransport | ModbusTcpClient | None = None,
        *,
        variables: dict[str, object] | None = None,
        cancel_event: threading.Event | None = None,
        logger: Callable[[str], None] | None = None,
        max_loop_iterations: int = 100_000,
    ) -> None:
        if max_loop_iterations < 1:
            raise ValueError("max_loop_iterations must be positive")
        self.visa = visa
        self.modbus = modbus
        self.variables = {
            str(name).lstrip("$").casefold(): value
            for name, value in (variables or {}).items()
        }
        self.cancel_event = cancel_event or threading.Event()
        self.logger = logger
        self.max_loop_iterations = max_loop_iterations
        self.log_path = Path.cwd() / "log.txt"
        self.working_directory = Path.cwd()
        self.last_result: object = None

    def run(self, source: str) -> dict[str, object]:
        statements = _parse(source)
        self._execute(statements)
        return dict(self.variables)

    def _execute(self, statements: tuple[Statement, ...]) -> None:
        for statement in statements:
            self._check_cancelled()
            try:
                if isinstance(statement, _Command):
                    self._execute_command(statement.text)
                elif isinstance(statement, _Python):
                    self._execute_python(statement.mode, statement.source)
                elif isinstance(statement, _If):
                    branch = statement.body if self._condition(statement.condition) else statement.otherwise
                    self._execute(branch)
                elif isinstance(statement, _While):
                    iterations = 0
                    while self._condition(statement.condition):
                        self._check_loop_limit(iterations)
                        self._execute(statement.body)
                        iterations += 1
                else:
                    iterations = 0
                    while True:
                        self._check_loop_limit(iterations)
                        self._execute(statement.body)
                        iterations += 1
                        if self._condition(statement.condition):
                            break
            except ScriptCancelled:
                raise
            except ScriptError as error:
                raise ScriptError(f"line {statement.line}: {error}") from error
            except Exception as error:
                raise ScriptError(
                    f"line {statement.line}: {type(error).__name__}: {error}"
                ) from error

    def _execute_command(self, command: str) -> None:
        if command.casefold().startswith(("download::", "upload::")):
            raise ScriptError("binary upload and download directives are not supported")
        assignment = _ASSIGNMENT.match(command)
        if assignment is not None:
            name, request = assignment.groups()
            result = self._run_request(request.strip(), query=True)
            self._set_variable(name, result)
            return

        parts = command.split(maxsplit=1)
        directive = parts[0].casefold()
        argument = parts[1] if len(parts) == 2 else ""

        if directive == "set":
            parts = argument.split(maxsplit=1)
            match = _VARIABLE_NAME.fullmatch(parts[0]) if parts else None
            if len(parts) != 2 or match is None:
                raise ScriptError("set syntax is: set $variable expression")
            value = evaluate_expression(parts[1], self.variables)
            self._set_variable(match.group(1), value)
        elif directive == "sleep":
            duration = float(evaluate_expression(argument, self.variables))
            if duration < 0:
                raise ScriptError("sleep duration must not be negative")
            if self.cancel_event.wait(duration / 1000):
                raise ScriptCancelled("script execution was cancelled")
        elif directive in {"log", "print"}:
            text = interpolate_text(argument, self.variables)
            if self.logger is not None:
                self.logger(text)
            else:
                with self.log_path.open("a", encoding="utf-8", newline="\n") as log_file:
                    log_file.write(text + "\n")
        elif directive == "logfile":
            if not argument:
                raise ScriptError("logfile requires a path")
            self.log_path = self._resolve_path(interpolate_text(argument, self.variables))
        elif directive in {"cd", "chdir"}:
            if not argument:
                raise ScriptError(f"{directive} requires a path")
            directory = self._resolve_path(interpolate_text(argument, self.variables))
            if not directory.is_dir():
                raise ScriptError(f"working directory does not exist: {directory}")
            self.working_directory = directory
        elif directive in {"close"}:
            if self.visa is not None:
                self.visa.close()
            if self.modbus is not None:
                self.modbus.close()
        elif directive in {"write", "cmd"}:
            if not argument:
                raise ScriptError(f"{directive} requires a SCPI command")
            self._run_request(argument, query=argument.rstrip().endswith("?"))
        elif directive in {"read", "getret"}:
            if argument:
                match = _VARIABLE_NAME.fullmatch(argument.strip())
                if match is None:
                    raise ScriptError(f"{directive} expects a variable name")
                self._set_variable(match.group(1), self.last_result)
        elif directive in {"modbusread", "modbuswrite"}:
            self.last_result = self._run_modbus(directive, argument)
        elif directive in {"eval", "exec"}:
            if not argument:
                raise ScriptError(f"{directive} requires Python code")
            self._execute_python(directive, argument)
        elif directive in {"execute", "upload", "download", "select", "sel"}:
            raise ScriptError(f"the {directive!r} directive is not supported by the Python runner")
        else:
            self.last_result = self._run_request(
                command,
                query=command.rstrip().endswith("?"),
            )

    def _execute_python(self, mode: str, source: str) -> None:
        namespace: dict[str, object] = {
            "__name__": "__manual_test_companion_script__",
            "visa": self.visa,
            "modbus": self.modbus,
            **self.variables,
        }
        code = compile(source, f"<script {mode}>", mode)
        if mode == "eval":
            result = eval(code, namespace, namespace)
            self.last_result = result
        else:
            exec(code, namespace, namespace)
            self.last_result = None
        for name, value in namespace.items():
            if name not in {"__name__", "__builtins__", "visa", "modbus"}:
                self.variables[name.casefold()] = value

    def _run_request(self, request: str, *, query: bool) -> object:
        request = interpolate_text(request, self.variables).strip()
        if request.casefold().startswith("modbusread "):
            return self._run_modbus("modbusread", request.split(maxsplit=1)[1])
        if request.casefold().startswith("modbuswrite "):
            return self._run_modbus("modbuswrite", request.split(maxsplit=1)[1])
        if self.visa is None:
            raise ScriptError("this script requires a configured VISA/SCPI session")
        if query:
            result = self.visa.query(request)
            self.last_result = result
            return result
        self.visa.write(request)
        self.last_result = None
        return None

    def _run_modbus(self, directive: str, argument: str) -> object:
        if self.modbus is None:
            raise ScriptError("this script requires a configured Modbus TCP client")
        parts = argument.split(maxsplit=2)
        minimum = 2 if directive == "modbusread" else 3
        if len(parts) < minimum:
            usage = "modbusread format address" if minimum == 2 else "modbuswrite format address value"
            raise ScriptError(f"{directive} syntax is: {usage}")
        format_string = interpolate_text(parts[0], self.variables)
        address = int(evaluate_expression(parts[1], self.variables))
        if directive == "modbusread":
            result = self.modbus.read_value(address, format_string)
        else:
            value = evaluate_expression(parts[2], self.variables)
            if not isinstance(value, (int, float, str)):
                raise ScriptError("Modbus value must be numeric or a string")
            self.modbus.write_value(address, value, format_string)
            result = None
        self.last_result = result
        return result

    def _condition(self, expression: str) -> bool:
        return bool(evaluate_expression(expression, self.variables))

    def _set_variable(self, name: str, value: object) -> None:
        self.variables[name.lstrip("$").casefold()] = value
        self.last_result = value

    def _resolve_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.working_directory / path

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise ScriptCancelled("script execution was cancelled")

    def _check_loop_limit(self, iterations: int) -> None:
        self._check_cancelled()
        if iterations >= self.max_loop_iterations:
            raise ScriptError(f"loop exceeded {self.max_loop_iterations} iterations")


def _parse(source: str) -> tuple[Statement, ...]:
    lines = [
        (number, line.rstrip())
        for number, line in enumerate(source.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("//")
    ]
    statements, index, terminator = _parse_block(lines, 0, frozenset())
    if terminator is not None:
        line, command = lines[index]
        raise ScriptError(f"line {line}: unexpected {command!r}")
    return statements


def _parse_block(
    lines: list[tuple[int, str]],
    index: int,
    endings: frozenset[str],
) -> tuple[tuple[Statement, ...], int, str | None]:
    statements: list[Statement] = []
    while index < len(lines):
        line_number, raw_text = lines[index]
        text = raw_text.strip()
        parts = text.split(maxsplit=1)
        directive = parts[0].casefold()
        argument = parts[1] if len(parts) == 2 else ""
        if directive in {"else", "end", "endif"} or directive == "until":
            if directive in endings:
                return tuple(statements), index, directive
            raise ScriptError(f"line {line_number}: unexpected {directive}")
        if directive == "if":
            condition = _remove_then(argument, line_number)
            if not condition:
                raise ScriptError(f"line {line_number}: if requires a condition")
            body, next_index, terminator = _parse_block(
                lines, index + 1, frozenset({"else", "end", "endif"})
            )
            otherwise: tuple[Statement, ...] = ()
            if terminator == "else":
                otherwise, next_index, terminator = _parse_block(
                    lines, next_index + 1, frozenset({"end", "endif"})
                )
            if terminator is None:
                raise ScriptError(f"line {line_number}: if block is missing end")
            statements.append(_If(line_number, condition, body, otherwise))
            index = next_index + 1
            continue
        if directive == "while":
            if not argument:
                raise ScriptError(f"line {line_number}: while requires a condition")
            body, next_index, terminator = _parse_block(
                lines, index + 1, frozenset({"end", "endif"})
            )
            if terminator is None:
                raise ScriptError(f"line {line_number}: while block is missing end")
            statements.append(_While(line_number, argument, body))
            index = next_index + 1
            continue
        if directive == "do":
            body, next_index, terminator = _parse_block(lines, index + 1, frozenset({"until"}))
            if terminator is None:
                raise ScriptError(f"line {line_number}: do block is missing until")
            until_parts = lines[next_index][1].split(maxsplit=1)
            condition = until_parts[1] if len(until_parts) == 2 else ""
            if not condition:
                raise ScriptError(f"line {lines[next_index][0]}: until requires a condition")
            statements.append(_DoUntil(line_number, body, condition))
            index = next_index + 1
            continue
        if directive == "eval":
            if not argument:
                raise ScriptError(f"line {line_number}: eval requires Python code")
            statements.append(_Python(line_number, "eval", argument))
            index += 1
            continue
        if directive == "exec":
            if argument:
                statements.append(_Python(line_number, "exec", argument))
                index += 1
                continue
            code_lines: list[str] = []
            end_index = index + 1
            while end_index < len(lines) and lines[end_index][1].strip().casefold() != "endexec":
                code_lines.append(lines[end_index][1])
                end_index += 1
            if end_index == len(lines):
                raise ScriptError(f"line {line_number}: exec block is missing endexec")
            code = textwrap.dedent("\n".join(code_lines)).strip("\n")
            if not code.strip():
                raise ScriptError(f"line {line_number}: exec block is empty")
            statements.append(_Python(line_number, "exec", code))
            index = end_index + 1
            continue
        if directive == "endexec":
            raise ScriptError(f"line {line_number}: unexpected endexec")
        if directive in {"else", "until", "end", "endif"}:
            raise ScriptError(f"line {line_number}: unexpected {directive}")
        statements.append(_Command(line_number, text))
        index += 1
    return tuple(statements), index, None


def _remove_then(condition: str, line: int) -> str:
    if condition.casefold().endswith(" then"):
        condition = condition[:-5].rstrip()
    elif condition.casefold() == "then":
        condition = ""
    if not condition:
        raise ScriptError(f"line {line}: if requires a condition")
    return condition
