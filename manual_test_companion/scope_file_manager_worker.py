from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from .scope_file_manager import ScopeDirectory, ScopeFileManager
from .visa import InstrumentSession


@dataclass(frozen=True)
class ScopeFMResult:
    action: str
    identification: str = ""
    directory: ScopeDirectory | None = None
    local_path: str = ""
    error: Exception | None = None


class ScopeFileManagerWorker:
    """Keep oscilloscope file-system commands off the Win32 thread."""

    def __init__(
        self,
        publish: Callable[[ScopeFMResult], None],
        *,
        manager_factory: Callable[[str], ScopeFileManager] | None = None,
    ) -> None:
        self._publish = publish
        self._manager_factory = manager_factory or (
            lambda address: ScopeFileManager(InstrumentSession(address, timeout=15))
        )
        self._requests: queue.Queue[tuple[str, object] | None] = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name="Oscilloscope file manager worker",
            daemon=True,
        )
        self._thread.start()

    def connect(self, address: str, last_folder: str = "") -> None:
        self._requests.put(("connect", (address, last_folder)))

    def disconnect(self) -> None:
        self._requests.put(("disconnect", None))

    def refresh(self) -> None:
        self._requests.put(("refresh", None))

    def change_directory(self, path: str) -> None:
        self._requests.put(("change_directory", path))

    def parent_directory(self, path: str) -> None:
        self._requests.put(("parent_directory", path))

    def download(self, name: str, destination: Path) -> None:
        self._requests.put(("download", (name, destination)))

    def upload(self, source: Path, remote_name: str) -> None:
        self._requests.put(("upload", (source, remote_name)))

    def close(self) -> None:
        self._requests.put(None)

    def _run(self) -> None:
        manager: ScopeFileManager | None = None
        identification = ""
        while True:
            request = self._requests.get()
            if request is None:
                if manager is not None:
                    manager.close()
                return

            action, value = request
            try:
                if action == "connect":
                    if manager is not None:
                        manager.close()
                    address, last_folder = cast(tuple[str, str], value)
                    manager = self._manager_factory(str(address))
                    identification, directory = manager.connect(str(last_folder))
                elif action == "disconnect":
                    if manager is not None:
                        manager.close()
                    manager = None
                    identification = ""
                    directory = None
                elif manager is None:
                    raise RuntimeError("connect to the oscilloscope before using its file system")
                elif action == "refresh":
                    directory = manager.read_directory()
                elif action == "change_directory":
                    directory = manager.change_directory(str(value))
                elif action == "parent_directory":
                    directory = manager.parent_directory(str(value))
                elif action == "download":
                    name, destination = cast(tuple[str, Path], value)
                    local_path = manager.download_file(str(name), Path(destination))
                    directory = manager.read_directory()
                    self._publish(
                        ScopeFMResult(
                            action,
                            identification,
                            directory,
                            local_path=str(local_path),
                        )
                    )
                    continue
                elif action == "upload":
                    source, remote_name = cast(tuple[Path, str], value)
                    directory = manager.upload_file(Path(source), str(remote_name))
                else:
                    raise ValueError(f"unknown oscilloscope file operation: {action}")
                self._publish(
                    ScopeFMResult(action, identification=identification, directory=directory)
                )
            except Exception as error:
                if action == "connect":
                    if manager is not None:
                        try:
                            manager.close()
                        except Exception as close_error:
                            error.add_note(
                                f"Closing failed oscilloscope connection also failed: {close_error}"
                            )
                        manager = None
                        identification = ""
                self._publish(
                    ScopeFMResult(action, identification=identification, error=error)
                )
