from __future__ import annotations

from pathlib import Path


def read_script_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_script_file(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
