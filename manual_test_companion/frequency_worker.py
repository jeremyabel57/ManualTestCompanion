from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Protocol

from .frequency_counter import FrequencyCounter, FrequencyStats
from .visa import InstrumentSession


class _FrequencyCounter(Protocol):
    def identify(self) -> str: ...

    def initialize(self) -> None: ...

    def reset_statistics(self) -> None: ...

    def read_count(self) -> int: ...

    def read_sample(self) -> FrequencyStats | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class FrequencyResult:
    action: str
    identification: str = ""
    count: int | None = None
    stats: FrequencyStats | None = None
    capture_complete: bool = False
    error: Exception | None = None


class FrequencyCounterWorker:
    """Keep synchronous frequency-counter VISA operations off the UI thread."""

    def __init__(
        self,
        publish: Callable[[FrequencyResult], None],
        *,
        counter_factory: Callable[[str], _FrequencyCounter] | None = None,
    ) -> None:
        self._publish = publish
        self._counter_factory = counter_factory or (
            lambda address: FrequencyCounter(InstrumentSession(address, timeout=1.5))
        )
        self._requests: queue.Queue[tuple[str, object] | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name="Frequency counter worker",
            daemon=True,
        )
        self._thread.start()

    def connect(self, address: str) -> None:
        self._requests.put(("connect", address))

    def initialize(self) -> None:
        self._requests.put(("initialize", None))

    def reset_statistics(self) -> None:
        self._requests.put(("reset", None))

    def monitor(self) -> None:
        self._requests.put(("monitor", None))

    def poll_capture(self, target_count: int) -> None:
        self._requests.put(("capture", target_count))

    def close(self) -> None:
        self._requests.put(None)

    def _run(self) -> None:
        counter: _FrequencyCounter | None = None
        identification = ""
        while True:
            request = self._requests.get()
            if request is None:
                if counter is not None:
                    counter.close()
                return

            action, value = request
            try:
                if action == "connect":
                    if counter is not None:
                        counter.close()
                    counter = self._counter_factory(str(value))
                    identification = counter.identify()
                    result = FrequencyResult(action, identification=identification)
                elif counter is None:
                    raise RuntimeError("connect to the frequency counter before sending commands")
                elif action == "initialize":
                    counter.initialize()
                    result = FrequencyResult(action, identification=identification)
                elif action == "reset":
                    counter.reset_statistics()
                    result = FrequencyResult(action, identification=identification)
                elif action == "monitor":
                    stats = counter.read_sample()
                    count = stats.count if stats is not None else counter.read_count()
                    result = FrequencyResult(
                        action,
                        identification=identification,
                        count=count,
                        stats=stats,
                    )
                elif action == "capture":
                    target_count = int(value)
                    count = counter.read_count()
                    complete = count >= target_count
                    stats = counter.read_sample() if complete else None
                    result = FrequencyResult(
                        action,
                        identification=identification,
                        count=count,
                        stats=stats,
                        capture_complete=complete,
                    )
                else:
                    raise ValueError(f"unknown frequency-counter operation: {action}")
                self._publish(result)
            except Exception as error:
                if action == "connect":
                    if counter is not None:
                        try:
                            counter.close()
                        except Exception as close_error:
                            error.add_note(
                                f"Closing failed frequency-counter connection also failed: {close_error}"
                            )
                        counter = None
                        identification = ""
                self._publish(
                    FrequencyResult(
                        action,
                        identification=identification,
                        error=error,
                    )
                )
