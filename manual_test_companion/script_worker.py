from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

from .modbus import ModbusTcpClient
from .script import ScriptCancelled, ScriptRunner
from .visa import InstrumentSession


class _Session(Protocol):
    def close(self) -> None: ...


class _VisaSession(_Session, Protocol):
    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...


class _ModbusSession(_Session, Protocol):
    def read_value(self, address: int, format_string: str) -> int | float | str: ...

    def write_value(
        self, address: int, value: int | float | str, format_string: str
    ) -> None: ...


@dataclass(frozen=True)
class ScriptEvent:
    kind: str
    text: str


@dataclass(frozen=True)
class ScriptJob:
    source: str
    visa_address: str = ""
    modbus_host: str = ""
    variables: dict[str, object] | None = None


class ScriptWorker:
    """Run one user script off the Win32 thread and publish output events."""

    def __init__(
        self,
        publish: Callable[[ScriptEvent], None],
        *,
        visa_factory: Callable[[str], _VisaSession] | None = None,
        modbus_factory: Callable[[str], _ModbusSession] | None = None,
    ) -> None:
        self._publish = publish
        self._visa_factory = visa_factory or (lambda address: InstrumentSession(address))
        self._modbus_factory = modbus_factory or (lambda host: ModbusTcpClient(host))
        self._thread: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._lock = threading.Lock()
        self._queued_scripts: deque[ScriptJob] = deque()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        source: str,
        *,
        visa_address: str = "",
        modbus_host: str = "",
        variables: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a script is already running")
            cancel_event = threading.Event()
            thread = threading.Thread(
                target=self._run,
                args=(source, visa_address, modbus_host, variables or {}, cancel_event),
                name="ManualTestCompanion script",
                daemon=True,
            )
            self._cancel_event = cancel_event
            self._thread = thread
            thread.start()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._queued_scripts)

    def queue_script(
        self,
        source: str,
        *,
        visa_address: str = "",
        modbus_host: str = "",
        variables: dict[str, object] | None = None,
    ) -> None:
        with self._lock:
            self._queued_scripts.append(
                ScriptJob(
                    source,
                    visa_address.strip(),
                    modbus_host.strip(),
                    dict(variables or {}),
                )
            )

    def clear_queue(self) -> None:
        with self._lock:
            self._queued_scripts.clear()

    def start_queued(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("a script is already running")
            if not self._queued_scripts:
                raise RuntimeError("script queue is empty")
            jobs = list(self._queued_scripts)
            self._queued_scripts.clear()
            cancel_event = threading.Event()
            thread = threading.Thread(
                target=self._run_queue,
                args=(jobs, cancel_event),
                name="ManualTestCompanion master queue",
                daemon=True,
            )
            self._cancel_event = cancel_event
            self._thread = thread
            thread.start()

    def cancel(self) -> None:
        with self._lock:
            cancel_event = self._cancel_event
        if cancel_event is not None:
            cancel_event.set()

    def _run_queue(
        self,
        jobs: list[ScriptJob],
        cancel_event: threading.Event,
    ) -> None:
        for index, job in enumerate(jobs, start=1):
            if cancel_event.is_set():
                self._publish(ScriptEvent("cancelled", "Master queue cancelled."))
                return
            self._publish(ScriptEvent("queued_started", f"Starting queued script {index} of {len(jobs)}."))
            visa: _VisaSession | None = None
            modbus: _ModbusSession | None = None
            terminal_event: ScriptEvent
            try:
                if job.visa_address:
                    visa = self._visa_factory(job.visa_address)
                if job.modbus_host:
                    modbus = self._modbus_factory(job.modbus_host)
                variables = ScriptRunner(
                    visa=visa,
                    modbus=modbus,
                    variables=job.variables,
                    cancel_event=cancel_event,
                    logger=lambda text: self._publish(ScriptEvent("output", text)),
                ).run(job.source)
                terminal_event = ScriptEvent(
                    "completed",
                    f"Script {index} completed ({len(variables)} variables).",
                )
            except ScriptCancelled:
                terminal_event = ScriptEvent("cancelled", f"Script {index} cancelled.")
            except Exception as error:
                terminal_event = ScriptEvent("failed", f"Script {index}: {type(error).__name__}: {error}")
            close_errors: list[str] = []
            for session in (visa, modbus):
                if session is not None:
                    try:
                        session.close()
                    except Exception as error:
                        close_errors.append(f"Failed to close instrument session: {error}")
            if close_errors:
                terminal_event = ScriptEvent("failed", "\n".join([terminal_event.text, *close_errors]))
            self._publish(terminal_event)
            if terminal_event.kind in {"cancelled", "failed"}:
                return
        self._publish(ScriptEvent("queue_completed", f"Master queue completed ({len(jobs)} scripts)."))

    def _run(
        self,
        source: str,
        visa_address: str,
        modbus_host: str,
        variables: dict[str, object],
        cancel_event: threading.Event,
    ) -> None:
        visa: _VisaSession | None = None
        modbus: _ModbusSession | None = None
        terminal_event: ScriptEvent
        try:
            self._publish(ScriptEvent("started", "Script started."))
            if visa_address.strip():
                visa = self._visa_factory(visa_address.strip())
            if modbus_host.strip():
                modbus = self._modbus_factory(modbus_host.strip())
            variables = ScriptRunner(
                visa=visa,
                modbus=modbus,
                variables=variables,
                cancel_event=cancel_event,
                logger=lambda text: self._publish(ScriptEvent("output", text)),
            ).run(source)
            terminal_event = ScriptEvent(
                "completed", f"Script completed ({len(variables)} variables)."
            )
        except ScriptCancelled:
            terminal_event = ScriptEvent("cancelled", "Script cancelled.")
        except Exception as error:
            terminal_event = ScriptEvent("failed", f"{type(error).__name__}: {error}")
        close_errors: list[str] = []
        for session in (visa, modbus):
            if session is not None:
                try:
                    session.close()
                except Exception as error:
                    close_errors.append(f"Failed to close instrument session: {error}")
        if close_errors:
            terminal_event = ScriptEvent(
                "failed",
                "\n".join([terminal_event.text, *close_errors]),
            )
        self._publish(terminal_event)
