import queue
import threading
import unittest

from manual_test_companion.dcps import DCPSChannelReading, DCPSReading
from manual_test_companion.dcps_worker import DCPSResult, DCPSWorker


def _reading() -> DCPSReading:
    channel = DCPSChannelReading(12, 0.1, 12, 5, False)
    return DCPSReading((channel, channel, channel, channel))


class FakeController:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.closed = threading.Event()

    def identify(self) -> str:
        self.calls.append(("identify",))
        return "mock DC supply"

    def read_all(self) -> DCPSReading:
        self.calls.append(("read_all",))
        return _reading()

    def set_voltage(self, channel: int, voltage: float) -> None:
        self.calls.append(("voltage", channel, voltage))

    def set_current_limit(self, channel: int, current: float) -> None:
        self.calls.append(("current", channel, current))

    def set_output(self, channel: int, enabled: bool) -> None:
        self.calls.append(("output", channel, enabled))

    def emergency_off(self) -> None:
        self.calls.append(("emergency_off",))

    def close(self) -> None:
        self.closed.set()


class DCPSWorkerTests(unittest.TestCase):
    def test_runs_scpi_operations_in_background_and_publishes_snapshots(self) -> None:
        results: queue.Queue[DCPSResult] = queue.Queue()
        controller = FakeController()
        worker = DCPSWorker(results.put, controller_factory=lambda _address: controller)
        try:
            worker.connect("raw:127.0.0.1:5025")
            connected = results.get(timeout=2)
            self.assertEqual(connected.action, "connect")
            self.assertEqual(connected.identification, "mock DC supply")

            worker.set_voltage(1, 12)
            updated = results.get(timeout=2)
            self.assertEqual(updated.action, "voltage")
            self.assertEqual(updated.reading, _reading())

            worker.run_sequence(((2, True, 0), (1, False, 0)))
            sequenced = results.get(timeout=2)
            self.assertEqual(sequenced.action, "sequence")
            self.assertIn(("output", 2, True), controller.calls)
            self.assertIn(("output", 1, False), controller.calls)
        finally:
            worker.close()

        self.assertTrue(controller.closed.wait(2))

    def test_reports_operations_before_connection_as_errors(self) -> None:
        results: queue.Queue[DCPSResult] = queue.Queue()
        worker = DCPSWorker(results.put, controller_factory=lambda _address: FakeController())
        try:
            worker.refresh()
            result = results.get(timeout=2)
            self.assertEqual(result.action, "refresh")
            self.assertRegex(str(result.error), "connect to the power supply")
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
