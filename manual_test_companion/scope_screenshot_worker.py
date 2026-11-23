from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .scope_file_manager import ScopeFileManager
from .visa import InstrumentSession


@dataclass(frozen=True)
class ScopeScreenshotResult:
    path: Path
    error: Exception | None = None


class ScopeScreenshotWorker:
    """Capture oscilloscope screenshots without blocking the Win32 thread."""

    def __init__(
        self,
        publish: Callable[[ScopeScreenshotResult], None],
        *,
        manager_factory: Callable[[str], ScopeFileManager] | None = None,
    ) -> None:
        self._publish = publish
        self._manager_factory = manager_factory or (
            lambda address: ScopeFileManager(InstrumentSession(address, timeout=15))
        )
        self._requests: queue.Queue[tuple[str, Path] | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name="Oscilloscope screenshot worker",
            daemon=True,
        )
        self._thread.start()

    def capture(self, address: str, destination: Path) -> None:
        self._requests.put((address, destination))

    def close(self) -> None:
        self._requests.put(None)

    def _run(self) -> None:
        while True:
            request = self._requests.get()
            if request is None:
                return
            address, destination = request
            manager: ScopeFileManager | None = None
            try:
                manager = self._manager_factory(address)
                path = manager.capture_screenshot(destination)
            except Exception as error:
                if manager is not None:
                    try:
                        manager.close()
                    except Exception as close_error:
                        error.add_note(
                            f"Closing the oscilloscope connection also failed: {close_error}"
                        )
                self._publish(ScopeScreenshotResult(destination, error))
            else:
                try:
                    manager.close()
                except Exception as error:
                    self._publish(ScopeScreenshotResult(path, error))
                else:
                    self._publish(ScopeScreenshotResult(path))
