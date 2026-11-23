import queue
import threading
import unittest

from manual_test_companion.frequency_counter import FrequencyStats
from manual_test_companion.frequency_worker import FrequencyCounterWorker, FrequencyResult


class FakeFrequencyCounter:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.count = 10
        self.calls: list[str] = []

    def identify(self) -> str:
        self.calls.append("identify")
        return "mock frequency counter"

    def initialize(self) -> None:
        self.calls.append("initialize")

    def reset_statistics(self) -> None:
        self.calls.append("reset")

    def read_count(self) -> int:
        self.calls.append("count")
        return self.count

    def read_sample(self) -> FrequencyStats:
        self.calls.append("sample")
        return FrequencyStats(10, 10.1, 10, 0.1, 9.9, 10.2, 0.01)

    def close(self) -> None:
        self.closed.set()


class FrequencyWorkerTests(unittest.TestCase):
    def test_runs_counter_actions_off_thread_and_publishes_results(self) -> None:
        results: queue.Queue[FrequencyResult] = queue.Queue()
        counter = FakeFrequencyCounter()
        worker = FrequencyCounterWorker(
            results.put,
            counter_factory=lambda _address: counter,
        )
        try:
            worker.connect("raw:127.0.0.1:5025")
            connected = results.get(timeout=2)
            self.assertEqual(connected.identification, "mock frequency counter")

            worker.initialize()
            self.assertEqual(results.get(timeout=2).action, "initialize")

            worker.monitor()
            monitored = results.get(timeout=2)
            self.assertEqual(monitored.count, 10)
            self.assertEqual(monitored.stats.mean_hz, 10)

            worker.poll_capture(10)
            captured = results.get(timeout=2)
            self.assertTrue(captured.capture_complete)
            self.assertEqual(captured.stats.count, 10)
        finally:
            worker.close()

        self.assertTrue(counter.closed.wait(2))

    def test_reports_operations_before_connection_as_errors(self) -> None:
        results: queue.Queue[FrequencyResult] = queue.Queue()
        worker = FrequencyCounterWorker(
            results.put,
            counter_factory=lambda _address: FakeFrequencyCounter(),
        )
        try:
            worker.monitor()
            result = results.get(timeout=2)
            self.assertRegex(str(result.error), "connect to the frequency counter")
        finally:
            worker.close()

    def test_capture_waits_until_requested_sample_count(self) -> None:
        results: queue.Queue[FrequencyResult] = queue.Queue()
        counter = FakeFrequencyCounter()
        counter.count = 5
        worker = FrequencyCounterWorker(
            results.put,
            counter_factory=lambda _address: counter,
        )
        try:
            worker.connect("raw:127.0.0.1:5025")
            results.get(timeout=2)
            worker.poll_capture(10)

            result = results.get(timeout=2)

            self.assertEqual(result.count, 5)
            self.assertFalse(result.capture_complete)
            self.assertIsNone(result.stats)
            self.assertNotIn("sample", counter.calls)
        finally:
            worker.close()


if __name__ == "__main__":
    unittest.main()
