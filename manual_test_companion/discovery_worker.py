from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from .discovery import DiscoveredDevice, scan_subnet


@dataclass(frozen=True)
class DiscoveryResult:
    devices: tuple[DiscoveredDevice, ...]
    error: Exception | None = None


class DiscoveryWorker:
    def __init__(self, publish: Callable[[DiscoveryResult], None]) -> None:
        self._publish = publish
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self, subnet: str) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("subnet scan is already running")
            self._thread = threading.Thread(
                target=self._scan,
                args=(subnet,),
                name="ManualTestCompanion subnet scan",
                daemon=True,
            )
            self._thread.start()

    def _scan(self, subnet: str) -> None:
        try:
            devices = scan_subnet(subnet)
            self._publish(DiscoveryResult(devices))
        except Exception as error:
            self._publish(DiscoveryResult((), error))
