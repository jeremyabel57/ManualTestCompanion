from __future__ import annotations

import configparser
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping


class LegacyConfig:
    """Read legacy AutoIt INI files and update selected keys without rewriting them."""

    def __init__(self, path: Path, section: str = "mts") -> None:
        self.path = path
        self.section = section
        self._parser = configparser.ConfigParser(interpolation=None)
        self._parser.optionxform = lambda optionstr: optionstr
        if path.exists():
            with path.open("r", encoding="utf-8-sig") as source:
                self._parser.read_file(source)

    def get_int(self, key: str, default: int) -> int:
        value = self._parser.get(self.section, key, fallback=str(default))
        try:
            return int(value)
        except ValueError:
            return default

    def get_str(self, key: str, default: str = "") -> str:
        return self._parser.get(self.section, key, fallback=default)

    def update(self, values: Mapping[str, str | int | float]) -> None:
        original = self.path.read_bytes() if self.path.exists() else b""
        has_bom = original.startswith(b"\xef\xbb\xbf")
        text = original.decode("utf-8-sig")
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines(keepends=True)
        section_header = re.compile(
            rf"^\s*\[{re.escape(self.section)}\]\s*(?:[;#].*)?$",
            re.IGNORECASE,
        )
        key_line = re.compile(r"^(\s*)([^=:#]+?)(\s*=\s*)(.*?)(\r?\n)?$")

        section_start = next(
            (index for index, line in enumerate(lines) if section_header.match(line.rstrip("\r\n"))),
            None,
        )
        if section_start is None:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            if lines and lines[-1].strip():
                lines.append(newline)
            lines.append(f"[{self.section}]{newline}")
            section_start = len(lines) - 1

        section_end = next(
            (
                index
                for index in range(section_start + 1, len(lines))
                if re.match(r"^\s*\[.*\]\s*(?:[;#].*)?$", lines[index].rstrip("\r\n"))
            ),
            len(lines),
        )
        remaining = dict(values)
        for index in range(section_start + 1, section_end):
            match = key_line.match(lines[index])
            if match is None:
                continue
            key = match.group(2).strip()
            if key not in remaining:
                continue
            ending = match.group(5) or ""
            lines[index] = (
                f"{match.group(1)}{match.group(2)}{match.group(3)}"
                f"{remaining.pop(key)}{ending}"
            )

        if remaining:
            insert_at = section_end
            if insert_at and not lines[insert_at - 1].endswith(("\n", "\r")):
                lines[insert_at - 1] += newline
            additions = [f"{key}={value}{newline}" for key, value in remaining.items()]
            lines[insert_at:insert_at] = additions

        encoded = "".join(lines).encode("utf-8")
        if has_bom:
            encoded = b"\xef\xbb\xbf" + encoded
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.path.parent, prefix=f".{self.path.name}.", delete=False
            ) as temporary:
                temp_path = temporary.name
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None and os.path.exists(temp_path):
                os.unlink(temp_path)
