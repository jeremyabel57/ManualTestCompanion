import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from manual_test_companion.visa import InstrumentAddress, InstrumentSession
from manual_test_companion.discovery import parse_subnet, probe_raw_tcp, scan_subnet
from manual_test_companion.discovery_worker import DiscoveryWorker


class DiscoveryTests(unittest.TestCase):
    def test_worker_publishes_background_result(self) -> None:
        import queue
        import time

        results: queue.Queue[object] = queue.Queue()
        worker = DiscoveryWorker(results.put)
        with patch("manual_test_companion.discovery_worker.scan_subnet", return_value=()) as scan:
            worker.start("192.168.0.0")
            result = results.get(timeout=2)

        scan.assert_called_once_with("192.168.0.0")
        self.assertEqual(result.error, None)
        self.assertEqual(result.devices, ())

    def test_parses_subnet_and_rejects_invalid_prefix(self) -> None:
        self.assertEqual(parse_subnet("192.168.0.0"), tuple(f"192.168.0.{index}" for index in range(1, 255)))
        with self.assertRaisesRegex(ValueError, "subnet"):
            parse_subnet("192.168.0")

    def test_raw_tcp_probe_uses_query_and_close(self) -> None:
        class FakeSocket:
            def settimeout(self, timeout: float) -> None:
                pass

            def sendall(self, payload: bytes) -> None:
                self.payload = payload

            def recv(self, size: int) -> bytes:
                return b"Fake Instrument\n"

            def close(self) -> None:
                pass

        with patch("manual_test_companion.discovery.socket.create_connection", return_value=FakeSocket()) as create:
            identity = probe_raw_tcp("192.168.0.25")

        create.assert_called_once()
        self.assertEqual(identity, "Fake Instrument")

    def test_scan_subnet_returns_sorted_discovered_devices(self) -> None:
        with patch("manual_test_companion.discovery.probe_raw_tcp", side_effect=lambda host, port, timeout: "Scope" if host == "192.168.0.14" else None):
            devices = scan_subnet("192.168.0.0", timeout=0.01, max_workers=8)

        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].host, "192.168.0.14")
        self.assertEqual(devices[0].address, "raw:192.168.0.14:5025")


class InstrumentAddressTests(unittest.TestCase):
    def test_parses_legacy_address_forms_and_trailing_device_labels(self) -> None:
        vxi = InstrumentAddress.parse("192.168.0.14   B028134")
        raw = InstrumentAddress.parse("RAW:192.168.0.25:5025")

        self.assertEqual(vxi.visa_resource, "TCPIP0::192.168.0.14::inst0::INSTR")
        self.assertFalse(vxi.raw_socket)
        self.assertEqual(raw.visa_resource, "TCPIP::192.168.0.25::5025::SOCKET")
        self.assertTrue(raw.raw_socket)

    def test_rejects_empty_or_invalid_raw_addresses(self) -> None:
        for address in ("", "raw:", "raw:127.0.0.1:bad", "raw:127.0.0.1:70000"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                InstrumentAddress.parse(address)


class RawInstrumentSessionTests(unittest.TestCase):
    def test_queries_a_raw_scpi_instrument_and_closes_cleanly(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(4)
        port = listener.getsockname()[1]
        server_errors: list[BaseException] = []

        def serve() -> None:
            try:
                connection = listener.accept()[0]
                with connection:
                    connection.settimeout(4)
                    command = _receive_line(connection)
                    if command != b"*IDN?\n":
                        raise AssertionError(f"unexpected SCPI command: {command!r}")
                    connection.sendall(b"Vendor,Model,Serial,1.0\r\n")
            except BaseException as error:
                server_errors.append(error)
            finally:
                listener.close()

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        with InstrumentSession(f"raw:127.0.0.1:{port}", timeout=2) as session:
            self.assertEqual(session.query("*IDN?"), "Vendor,Model,Serial,1.0")
        server.join(timeout=5)

        self.assertFalse(server.is_alive(), "local instrument server did not finish")
        self.assertEqual(server_errors, [])

    def test_reads_an_ieee_binary_block_and_keeps_the_session_usable(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(4)
        port = listener.getsockname()[1]
        payload = b"\x00#123\n,XYZ"
        server_errors: list[BaseException] = []

        def serve() -> None:
            try:
                connection = listener.accept()[0]
                with connection:
                    connection.settimeout(4)
                    command = _receive_line(connection)
                    if command != b'FILESystem:READFile "trace.wfm"\n':
                        raise AssertionError(f"unexpected SCPI command: {command!r}")
                    length = f"{len(payload):02d}".encode("ascii")
                    connection.sendall(b"#2" + length + payload + b"\r\n")
                    command = _receive_line(connection)
                    if command != b"*IDN?\n":
                        raise AssertionError(f"unexpected SCPI command: {command!r}")
                    connection.sendall(b"Vendor,Model,Serial,1.0\r\n")
            except BaseException as error:
                server_errors.append(error)
            finally:
                listener.close()

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        with InstrumentSession(f"raw:127.0.0.1:{port}", timeout=2) as session:
            self.assertEqual(session.query_binary('FILESystem:READFile "trace.wfm"'), payload)
            self.assertEqual(session.query("*IDN?"), "Vendor,Model,Serial,1.0")
        server.join(timeout=5)

        self.assertFalse(server.is_alive(), "local instrument server did not finish")
        self.assertEqual(server_errors, [])

    def test_queries_a_vxi11_resource_through_the_pyvisa_backend(self) -> None:
        resource = Mock()
        resource.query.return_value = "Vendor,Model,Serial,1.0\n"
        manager = Mock()
        manager.open_resource.return_value = resource
        pyvisa = SimpleNamespace(ResourceManager=Mock(return_value=manager))

        with patch.dict("sys.modules", {"pyvisa": pyvisa}):
            with InstrumentSession("192.168.0.14   B028134", timeout=2.5) as session:
                self.assertEqual(session.query("*IDN?"), "Vendor,Model,Serial,1.0")

        manager.open_resource.assert_called_once_with("TCPIP0::192.168.0.14::inst0::INSTR")
        self.assertEqual(resource.timeout, 2500)
        self.assertEqual(resource.read_termination, "\n")
        self.assertEqual(resource.write_termination, "\n")
        resource.close.assert_called_once_with()
        manager.close.assert_called_once_with()

    def test_reads_ieee_binary_block_through_pyvisa(self) -> None:
        resource = Mock()
        resource.read_raw.return_value = b"#210abcdefghij\r\n"
        manager = Mock()
        manager.open_resource.return_value = resource
        pyvisa = SimpleNamespace(ResourceManager=Mock(return_value=manager))

        with patch.dict("sys.modules", {"pyvisa": pyvisa}):
            with InstrumentSession("192.168.0.14", timeout=2) as session:
                self.assertEqual(session.query_binary('FILESystem:READFile "a.wfm"'), b"abcdefghij")

        resource.write.assert_called_once_with('FILESystem:READFile "a.wfm"')
        resource.read_raw.assert_called_once_with()

    def test_writes_ieee_binary_block_through_pyvisa(self) -> None:
        resource = Mock()
        manager = Mock()
        manager.open_resource.return_value = resource
        pyvisa = SimpleNamespace(ResourceManager=Mock(return_value=manager))

        with patch.dict("sys.modules", {"pyvisa": pyvisa}):
            with InstrumentSession("192.168.0.14", timeout=2) as session:
                session.write_binary_block('FILESystem:WRITEFile "a.wfm",', b"\x00abc")

        resource.write_raw.assert_called_once_with(
            b'FILESystem:WRITEFile "a.wfm",#14\x00abc\r\n'
        )


def _receive_line(connection: socket.socket) -> bytes:
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = connection.recv(1)
        if not chunk:
            raise AssertionError("instrument session closed before sending a command")
        data.extend(chunk)
    return bytes(data)


if __name__ == "__main__":
    unittest.main()
