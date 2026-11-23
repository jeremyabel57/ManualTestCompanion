from __future__ import annotations

import csv
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class _InstrumentSession(Protocol):
    def query(self, command: str) -> str: ...

    def write(self, command: str) -> None: ...

    def query_binary(self, command: str) -> bytes: ...

    def write_binary_block(self, command: str, payload: bytes) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ScopeDirectoryEntry:
    name: str
    is_directory: bool


@dataclass(frozen=True)
class ScopeDirectory:
    path: str
    entries: tuple[ScopeDirectoryEntry, ...]


class ScopeFileManager:
    """SCPI file-system operations for the oscilloscope."""

    def __init__(self, session: _InstrumentSession) -> None:
        self._session = session

    def connect(self, last_folder: str = "") -> tuple[str, ScopeDirectory]:
        identification = self._session.query("*IDN?").strip()
        if not identification:
            raise ConnectionError("the oscilloscope returned an empty identification string")
        if last_folder:
            directory = self.change_directory(last_folder)
        else:
            directory = self.read_directory()
        return identification, directory

    def read_directory(self) -> ScopeDirectory:
        path = _parse_scpi_string(self._session.query("FILESystem:CWD?"))
        raw_entries = self._session.query("FILESystem:DIR?")
        return ScopeDirectory(path, parse_scope_directory(raw_entries))

    def change_directory(self, path: str) -> ScopeDirectory:
        self._session.write(f"FILESystem:CWD {_quote_scpi(path)}")
        return self.read_directory()

    def parent_directory(self, current_path: str) -> ScopeDirectory:
        return self.change_directory(scope_parent_path(current_path))

    def download_file(self, remote_name: str, destination: Path) -> Path:
        _validate_remote_name(remote_name)
        payload = self._session.query_binary(
            f"FILESystem:READFile {_quote_scpi(remote_name)}"
        )
        _write_binary_atomically(destination, payload)
        return destination

    def capture_screenshot(self, destination: Path, *, timeout: float = 10.0) -> Path:
        if timeout <= 0:
            raise ValueError("screenshot timeout must be positive")
        source = "C:/Temp_Scope.png"
        renamed = "C:/Temp2_Scope.png"
        try:
            self._session.write(f"FILESystem:DELEte {_quote_scpi(renamed)}")
            self._session.write(f"FILESystem:DELEte {_quote_scpi(source)}")
            self._session.write(f"SAVE:IMAGe {_quote_scpi(source)}")
            deadline = time.monotonic() + timeout
            while True:
                self._session.write("*CLS")
                time.sleep(0.5)
                self._session.write(
                    f"FILESystem:REName {_quote_scpi(source)},{_quote_scpi(renamed)}"
                )
                try:
                    event_status = int(self._session.query("*ESR?").strip())
                except ValueError as error:
                    raise ValueError(
                        "oscilloscope returned an invalid event status register"
                    ) from error
                if not event_status & 0x10:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "oscilloscope did not finish saving its screenshot in time"
                    )

            payload = self._session.query_binary(
                f"FILESystem:READFile {_quote_scpi(renamed)}"
            )
            if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("oscilloscope returned data that is not a PNG image")
            _write_binary_atomically(destination, payload)
        except Exception as error:
            self._cleanup_screenshot_files(error)
            raise
        self._cleanup_screenshot_files()
        return destination

    def _cleanup_screenshot_files(self, primary_error: Exception | None = None) -> None:
        cleanup_error: Exception | None = None
        for remote_path in ("C:/Temp2_Scope.png", "C:/Temp_Scope.png"):
            try:
                self._session.write(
                    f"FILESystem:DELEte {_quote_scpi(remote_path)}"
                )
            except Exception as error:
                if primary_error is not None:
                    primary_error.add_note(
                        f"Could not remove temporary oscilloscope file "
                        f"{remote_path}: {error}"
                    )
                elif cleanup_error is None:
                    cleanup_error = error
                else:
                    cleanup_error.add_note(
                        f"Could not remove temporary oscilloscope file "
                        f"{remote_path}: {error}"
                    )
        if cleanup_error is not None:
            raise RuntimeError(
                "screenshot was saved, but temporary oscilloscope files could not be removed"
            ) from cleanup_error

    def upload_file(self, source: Path, remote_name: str) -> ScopeDirectory:
        _validate_remote_name(remote_name)
        payload = source.read_bytes()
        self._session.write_binary_block(
            f"FILESystem:WRITEFile {_quote_scpi(remote_name)},",
            payload,
        )
        return self.read_directory()

    def close(self) -> None:
        self._session.close()


def _write_binary_atomically(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as output:
            temporary_path = output.name
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def parse_scope_directory(value: str) -> tuple[ScopeDirectoryEntry, ...]:
    try:
        rows = csv.reader([value], skipinitialspace=True, strict=True)
        names = next(rows, [])
    except csv.Error as error:
        raise ValueError(f"invalid oscilloscope directory listing: {value!r}") from error
    entries: list[ScopeDirectoryEntry] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        is_directory = name.endswith(("/", "\\")) or ":" in name
        entries.append(ScopeDirectoryEntry(name, is_directory))
    return tuple(entries)


def scope_parent_path(path: str) -> str:
    cleaned = path.rstrip("/\\")
    if not cleaned:
        return path
    if cleaned.endswith(":"):
        return f"{cleaned}{path[-1]}" if path.endswith(("/", "\\")) else cleaned
    separator = max(cleaned.rfind("/"), cleaned.rfind("\\"))
    if separator < 0:
        return "."
    if separator == 2 and len(cleaned) >= 2 and cleaned[1] == ":":
        return cleaned[:3]
    return cleaned[:separator] or cleaned[0]


def scope_join_path(current_path: str, child_name: str) -> str:
    if child_name.startswith(("/", "\\")) or (
        len(child_name) >= 2 and child_name[1] == ":"
    ):
        return child_name
    separator = "\\" if "\\" in current_path and "/" not in current_path else "/"
    base = current_path.rstrip("/\\")
    return f"{base}{separator}{child_name}"


def _parse_scpi_string(value: str) -> str:
    try:
        fields = next(csv.reader([value.strip()], skipinitialspace=True, strict=True), [])
    except csv.Error as error:
        raise ValueError(f"invalid quoted oscilloscope response: {value!r}") from error
    if not fields:
        return ""
    return fields[0].strip()


def _quote_scpi(value: str) -> str:
    if any(character in value for character in "\r\n"):
        raise ValueError("oscilloscope paths must not contain line breaks")
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _validate_remote_name(name: str) -> None:
    if not name or name in {".", ".."} or any(
        character in name for character in ('"', "\r", "\n", "/", "\\")
    ):
        raise ValueError(f"invalid oscilloscope file name: {name!r}")
