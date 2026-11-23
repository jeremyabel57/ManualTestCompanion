import socket
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from manual_test_companion.visa import InstrumentAddress, InstrumentSession


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
