import threading
import unittest
from pathlib import Path

from manual_test_companion.scope_file_manager import (
    ScopeDirectory,
    ScopeDirectoryEntry,
)
from manual_test_companion.scope_file_manager_worker import (
    ScopeFMResult,
    ScopeFileManagerWorker,
)


class FakeScopeFileManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.directory = ScopeDirectory(
            "C:/",
            (ScopeDirectoryEntry("trace.wfm", False),),
        )
        self.closed = False
        self.closed_event = threading.Event()
        self.thread_ids: list[int] = []

    def connect(self, last_folder: str = "") -> tuple[str, ScopeDirectory]:
        self.thread_ids.append(threading.get_ident())
        self.calls.append(("connect", last_folder))
        return "TEKTRONIX,MSO58B,SERIAL,1.0", self.directory

    def read_directory(self) -> ScopeDirectory:
        self.thread_ids.append(threading.get_ident())
        self.calls.append(("refresh", ""))
        return self.directory

    def change_directory(self, path: str) -> ScopeDirectory:
        self.thread_ids.append(threading.get_ident())
        self.calls.append(("change_directory", path))
        return self.directory

    def parent_directory(self, path: str) -> ScopeDirectory:
        self.thread_ids.append(threading.get_ident())
        self.calls.append(("parent_directory", path))
        return self.directory

    def download_file(self, name: str, destination: Path) -> Path:
        self.thread_ids.append(threading.get_ident())
        self.calls.append(("download", (name, destination)))
        return destination

    def upload_file(self, source: Path, remote_name: str) -> ScopeDirectory:
        self.thread_ids.append(threading.get_ident())
        self.calls.append(("upload", (source, remote_name)))
        return self.directory

    def close(self) -> None:
        self.closed = True
        self.closed_event.set()


class ScopeFileManagerWorkerTests(unittest.TestCase):
    def test_runs_file_operations_off_thread_and_publishes_results(self) -> None:
        results: list[ScopeFMResult] = []
        completed = threading.Event()
        manager = FakeScopeFileManager()

        def publish(result: ScopeFMResult) -> None:
            results.append(result)
            completed.set()

        worker = ScopeFileManagerWorker(
            publish,
            manager_factory=lambda _address: manager,
        )
        try:
            worker.connect("192.168.0.14", "C:/")
            self.assertTrue(completed.wait(2))
            self.assertEqual(results[-1].action, "connect")
            self.assertEqual(results[-1].identification, "TEKTRONIX,MSO58B,SERIAL,1.0")

            completed.clear()
            worker.change_directory("C:/Scope")
            self.assertTrue(completed.wait(2))
            self.assertEqual(manager.calls[-1], ("change_directory", "C:/Scope"))
            self.assertNotEqual(manager.thread_ids[0], threading.get_ident())
        finally:
            worker.close()
        self.assertTrue(manager.closed_event.wait(2))

    def test_reports_commands_before_connection_as_errors(self) -> None:
        results: list[ScopeFMResult] = []
        completed = threading.Event()

        def publish(result: ScopeFMResult) -> None:
            results.append(result)
            completed.set()

        worker = ScopeFileManagerWorker(
            publish,
            manager_factory=lambda _address: FakeScopeFileManager(),
        )
        try:
            worker.refresh()
            self.assertTrue(completed.wait(2))
            self.assertEqual(results[0].action, "refresh")
            self.assertIsInstance(results[0].error, RuntimeError)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
