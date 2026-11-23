from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Protocol, cast

from .dcps import DCPSController, DCPSReading
from .visa import InstrumentSession


class _Controller(Protocol):
    def identify(self) -> str: ...

    def read_all(self) -> DCPSReading: ...

    def set_voltage(self, channel: int, voltage: float) -> None: ...

    def set_current_limit(self, channel: int, current: float) -> None: ...

    def set_output(self, channel: int, enabled: bool) -> None: ...

    def emergency_off(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DCPSResult:
    action: str
    reading: DCPSReading | None = None
    identification: str = ""
    error: Exception | None = None


class DCPSWorker:
    """Keep synchronous SCPI operations off the Win32 message thread."""

    def __init__(
        self,
        publish: Callable[[DCPSResult], None],
        *,
        controller_factory: Callable[[str], _Controller] | None = None,
    ) -> None:
        self._publish = publish
        self._controller_factory = controller_factory or (
            lambda address: DCPSController(InstrumentSession(address, timeout=1.5))
        )
        self._requests: queue.Queue[tuple[str, object] | None] = queue.Queue()
        self._cancel_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="DC power supply worker", daemon=True)
        self._thread.start()

    def connect(self, address: str) -> None:
        self._requests.put(("connect", address))

    def refresh(self) -> None:
        self._requests.put(("refresh", None))

    def set_voltage(self, channel: int, voltage: float) -> None:
        self._requests.put(("voltage", (channel, voltage)))

    def set_current_limit(self, channel: int, current: float) -> None:
        self._requests.put(("current", (channel, current)))

    def set_output(self, channel: int, enabled: bool) -> None:
        self._requests.put(("output", (channel, enabled)))

    def emergency_off(self) -> None:
        self._requests.put(("emergency_off", None))

    def run_sequence(self, steps: tuple[tuple[int, bool, float], ...]) -> None:
        self._requests.put(("sequence", steps))

    def close(self) -> None:
        self._cancel_event.set()
        self._requests.put(None)

    def _run(self) -> None:
        controller: _Controller | None = None
        identification = ""
        while True:
            request = self._requests.get()
            if request is None:
                if controller is not None:
                    controller.close()
                return

            action, value = request
            try:
                if action == "connect":
                    if controller is not None:
                        controller.close()
                    controller = self._controller_factory(str(value))
                    identification = controller.identify()
                elif controller is None:
                    raise RuntimeError("connect to the power supply before sending commands")
                elif action == "voltage":
                    channel, voltage = cast(tuple[int, float], value)
                    controller.set_voltage(int(channel), float(voltage))
                elif action == "current":
                    channel, current = cast(tuple[int, float], value)
                    controller.set_current_limit(int(channel), float(current))
                elif action == "output":
                    channel, enabled = cast(tuple[int, bool], value)
                    controller.set_output(int(channel), bool(enabled))
                elif action == "emergency_off":
                    controller.emergency_off()
                elif action == "sequence":
                    self._run_sequence(
                        controller,
                        cast(tuple[tuple[int, bool, float], ...], value),
                    )
                elif action != "refresh":
                    raise ValueError(f"unknown power-supply operation: {action}")
                self._publish(
                    DCPSResult(action, controller.read_all(), identification=identification)
                )
            except Exception as error:
                if action == "connect":
                    if controller is not None:
                        try:
                            controller.close()
                        except Exception as close_error:
                            error.add_note(f"Closing failed power-supply connection also failed: {close_error}")
                        controller = None
                        identification = ""
                self._publish(DCPSResult(action, identification=identification, error=error))

    def _run_sequence(
        self,
        controller: _Controller,
        steps: tuple[tuple[int, bool, float], ...],
    ) -> None:
        for channel, enabled, delay in steps:
            if channel:
                controller.set_output(channel, enabled)
                if self._cancel_event.wait(delay):
                    raise RuntimeError("power sequence was cancelled while the application was closing")
