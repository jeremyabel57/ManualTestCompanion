import queue
import threading
import unittest

from manual_test_companion.chamber_worker import ChamberResult, ChamberWorker


class FakeChamber:
    def __init__(self) -> None:
        self.temperature_c = 23.0
        self.setpoint_c = 25.0
        self.enabled = False
        self.closed = threading.Event()

    def read_temperature_c(self) -> float:
        return self.temperature_c

    def read_setpoint_c(self) -> float:
        return self.setpoint_c

    def read_enabled(self) -> bool:
        return self.enabled

    def read_heating_percent(self) -> float:
        return 12.5

    def read_cooling_percent(self) -> float:
        return 0.0

    def set_setpoint_c(self, temperature: float) -> None:
        self.setpoint_c = temperature

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def close(self) -> None:
        self.closed.set()


class ChamberWorkerTests(unittest.TestCase):
    def test_runs_operations_off_thread_and_publishes_readings(self) -> None:
        results: queue.Queue[ChamberResult] = queue.Queue()
        chamber = FakeChamber()
        worker = ChamberWorker(results.put, client_factory=lambda _host: chamber)

        try:
            worker.connect("127.0.0.1")
            connected = results.get(timeout=2)
            self.assertEqual(connected.action, "connect")
            self.assertEqual(connected.reading.temperature_c, 23.0)

            worker.set_setpoint(30)
            updated = results.get(timeout=2)
            self.assertEqual(updated.action, "setpoint")
            self.assertEqual(updated.reading.setpoint_c, 30)

            worker.set_enabled(True)
            enabled = results.get(timeout=2)
            self.assertTrue(enabled.reading.enabled)
        finally:
            worker.close()

        self.assertTrue(chamber.closed.wait(2))

    def test_reports_commands_before_connect_as_errors(self) -> None:
        results: queue.Queue[ChamberResult] = queue.Queue()
        worker = ChamberWorker(results.put, client_factory=lambda _host: FakeChamber())
        try:
            worker.refresh()
            result = results.get(timeout=2)
            self.assertRegex(str(result.error), "connect to the chamber")
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
