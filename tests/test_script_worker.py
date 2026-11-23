import queue
import threading
import time
import unittest
from unittest.mock import Mock

from manual_test_companion.script_worker import ScriptEvent, ScriptWorker


class FakeVisa:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.queries: list[str] = []

    def write(self, _command: str) -> None:
        pass

    def query(self, command: str) -> str:
        self.queries.append(command)
        return "mock-id"

    def close(self) -> None:
        self.closed.set()


class FakeModbus:
    def __init__(self) -> None:
        self.closed = threading.Event()
        self.reads: list[tuple[int, str]] = []

    def read_value(self, address: int, format_string: str) -> int:
        self.reads.append((address, format_string))
        return 42

    def write_value(self, _address: int, _value: int | float | str, _format: str) -> None:
        pass

    def close(self) -> None:
        self.closed.set()


class FailingCloseVisa(FakeVisa):
    def close(self) -> None:
        raise OSError("close failed")


class ScriptWorkerTests(unittest.TestCase):
    def test_passes_settings_variables_to_script_runner(self) -> None:
        events: queue.Queue[ScriptEvent] = queue.Queue()
        worker = ScriptWorker(events.put)

        worker.start(
            "log {$pn}",
            variables={"pn": "ABC123"},
        )

        received = [events.get(timeout=2) for _ in range(3)]
        self.assertEqual([event.kind for event in received], ["started", "output", "completed"])
        self.assertEqual(received[1].text, "ABC123")

    def test_runs_script_publishes_logs_and_closes_sessions(self) -> None:
        events: queue.Queue[ScriptEvent] = queue.Queue()
        visa = FakeVisa()
        modbus = FakeModbus()
        worker = ScriptWorker(
            events.put,
            visa_factory=lambda _address: visa,
            modbus_factory=lambda _host: modbus,
        )

        worker.start(
            "log starting\n$id=*IDN?\n$value=modbusread 1i 100",
            visa_address="raw:127.0.0.1",
            modbus_host="127.0.0.1",
        )

        received = [events.get(timeout=2) for _ in range(3)]
        self.assertEqual([event.kind for event in received], ["started", "output", "completed"])
        self.assertEqual(received[1].text, "starting")
        self.assertEqual(visa.queries, ["*IDN?"])
        self.assertEqual(modbus.reads, [(100, "1i")])
        self.assertTrue(visa.closed.wait(2))
        self.assertTrue(modbus.closed.wait(2))

    def test_runs_queued_scripts_sequentially(self) -> None:
        publish = Mock()
        visa_sessions = []
        close = Mock()

        def visa_factory(address: str) -> object:
            session = Mock()
            session.query.return_value = address
            session.write.return_value = None
            session.close = close
            visa_sessions.append(session)
            return session

        worker = ScriptWorker(publish, visa_factory=visa_factory)
        worker.queue_script("$first = 1", visa_address="raw:192.0.2.10:5025")
        worker.queue_script("print \"second\"", visa_address="raw:192.0.2.11:5025")

        worker.start_queued()
        deadline = time.monotonic() + 2
        while worker.is_running and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertFalse(worker.is_running)
        self.assertEqual(worker.pending_count, 0)
        texts = [call.args[0].text for call in publish.call_args_list]
        self.assertEqual(len(visa_sessions), 2)
        self.assertTrue(any(text.startswith("Script 1 completed") for text in texts))
        self.assertTrue(any(text.startswith("Script 2 completed") for text in texts))

    def test_reports_close_failure_instead_of_success(self) -> None:
        events: queue.Queue[ScriptEvent] = queue.Queue()
        worker = ScriptWorker(
            events.put,
            visa_factory=lambda _address: FailingCloseVisa(),
        )

        worker.start("log finished", visa_address="raw:127.0.0.1")

        received = [events.get(timeout=2) for _ in range(3)]
        self.assertEqual([event.kind for event in received], ["started", "output", "failed"])
        self.assertIn("Script completed", received[-1].text)
        self.assertIn("Failed to close instrument session: close failed", received[-1].text)

    def test_cancellation_and_duplicate_start_are_reported(self) -> None:
        events: queue.Queue[ScriptEvent] = queue.Queue()
        worker = ScriptWorker(events.put)
        worker.start("sleep 10000")
        self.assertEqual(events.get(timeout=2).kind, "started")
        with self.assertRaisesRegex(RuntimeError, "already running"):
            worker.start("set $value 1")
        worker.cancel()
        self.assertEqual(events.get(timeout=2).kind, "cancelled")


if __name__ == "__main__":
    unittest.main()
