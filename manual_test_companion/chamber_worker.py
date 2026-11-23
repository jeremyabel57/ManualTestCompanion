from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Protocol

from .chamber import F4TChamber
from .modbus import ModbusTcpClient


class _Chamber(Protocol):
    def read_temperature_c(self) -> float: ...

    def read_setpoint_c(self) -> float: ...

    def read_enabled(self) -> bool: ...

    def read_heating_percent(self) -> float: ...

    def read_cooling_percent(self) -> float: ...

    def set_setpoint_c(self, temperature: float) -> None: ...

    def set_enabled(self, enabled: bool) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ChamberReading:
    temperature_c: float
    setpoint_c: float
    enabled: bool
    heating_percent: float
    cooling_percent: float


@dataclass(frozen=True)
class ChamberResult:
    action: str
    reading: ChamberReading | None = None
    error: Exception | None = None


class ChamberWorker:
    """Keep synchronous Modbus operations off the Win32 message thread."""

    def __init__(
        self,
        publish: Callable[[ChamberResult], None],
        *,
        client_factory: Callable[[str], _Chamber] | None = None,
    ) -> None:
        self._publish = publish
        self._client_factory = client_factory or (
            lambda host: F4TChamber(ModbusTcpClient(host, timeout=1.5))
        )
        self._requests: queue.Queue[tuple[str, object] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="F4T chamber worker", daemon=True)
        self._thread.start()

    def connect(self, host: str) -> None:
        self._requests.put(("connect", host))

    def refresh(self) -> None:
        self._requests.put(("refresh", None))

    def set_setpoint(self, temperature_c: float) -> None:
        self._requests.put(("setpoint", temperature_c))

    def set_enabled(self, enabled: bool) -> None:
        self._requests.put(("enable", enabled))

    def close(self) -> None:
        self._requests.put(None)

    def _run(self) -> None:
        chamber: _Chamber | None = None
        while True:
            request = self._requests.get()
            if request is None:
                if chamber is not None:
                    chamber.close()
                return

            action, value = request
            try:
                if action == "connect":
                    if chamber is not None:
                        chamber.close()
                    chamber = self._client_factory(str(value))
                elif chamber is None:
                    raise RuntimeError("connect to the chamber before sending commands")
                elif action == "setpoint":
                    chamber.set_setpoint_c(float(value))
                elif action == "enable":
                    chamber.set_enabled(bool(value))
                elif action != "refresh":
                    raise ValueError(f"unknown chamber operation: {action}")
                self._publish(ChamberResult(action, self._read(chamber)))
            except Exception as error:
                if action == "connect" and chamber is not None:
                    chamber.close()
                    chamber = None
                self._publish(ChamberResult(action, error=error))

    @staticmethod
    def _read(chamber: _Chamber) -> ChamberReading:
        return ChamberReading(
            temperature_c=chamber.read_temperature_c(),
            setpoint_c=chamber.read_setpoint_c(),
            enabled=chamber.read_enabled(),
            heating_percent=chamber.read_heating_percent(),
            cooling_percent=chamber.read_cooling_percent(),
        )
