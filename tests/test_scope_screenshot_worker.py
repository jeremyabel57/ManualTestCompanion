from pathlib import Path
import threading
import unittest

from manual_test_companion.scope_screenshot_worker import (
    ScopeScreenshotResult,
    ScopeScreenshotWorker,
)


class FakeScopeFileManager:
    def __init__(self) -> None:
        self.destination: Path | None = None
        self.closed = False

    def capture_screenshot(self, destination: Path) -> Path:
        self.destination = destination
        return destination

    def close(self) -> None:
        self.closed = True


class ScopeScreenshotWorkerTests(unittest.TestCase):
    def test_captures_screenshot_off_thread_and_publishes_result(self) -> None:
        manager = FakeScopeFileManager()
        results: list[ScopeScreenshotResult] = []
        completed = threading.Event()

        def publish(result: ScopeScreenshotResult) -> None:
            results.append(result)
            completed.set()

        worker = ScopeScreenshotWorker(
            publish,
            manager_factory=lambda address: manager,
        )
        destination = Path("scope.png")
        try:
            worker.capture("192.168.0.14", destination)
            self.assertTrue(completed.wait(2))
        finally:
            worker.close()

        self.assertEqual(results, [ScopeScreenshotResult(destination)])
        self.assertEqual(manager.destination, destination)
        self.assertTrue(manager.closed)


if __name__ == "__main__":
    unittest.main()
