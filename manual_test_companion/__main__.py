from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


_REQUIRED_MODULES = ("win32api", "win32con", "win32gui", "pyvisa")


def ensure_dependencies() -> None:
    if sys.platform != "win32":
        raise SystemExit("Manual Test Station Companion requires Windows.")

    missing = [module for module in _REQUIRED_MODULES if importlib.util.find_spec(module) is None]
    if not missing:
        return

    requirements_file = Path(__file__).resolve().parent.parent / "requirements.txt"
    if not requirements_file.is_file():
        raise FileNotFoundError(f"Dependency file not found: {requirements_file}")

    print(f"Installing missing dependencies from {requirements_file}...")
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements_file),
            ],
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            f"Dependency installation failed with exit code {error.returncode}."
        ) from error


def main() -> int:
    ensure_dependencies()
    from .app import main as launch_app

    return launch_app()


if __name__ == "__main__":
    raise SystemExit(main())
