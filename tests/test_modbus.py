import socket
import struct
import threading
import unittest

from manual_test_companion.modbus import (
    ModbusProtocolError,
    ModbusTcpClient,
    build_read_request,
    build_write_request,
    decode_register_value,
    encode_register_value,
)


class ModbusFrameTests(unittest.TestCase):
    def test_builds_legacy_read_and_multiple_register_write_frames(self) -> None:
        self.assertEqual(
            build_read_request(0x101, 0x1234, 2),
            bytes.fromhex("010100000006010312340002"),
        )
        self.assertEqual(
            build_write_request(0x101, 0x1234, bytes.fromhex("41480000")),
            bytes.fromhex("01010000000b0110123400020441480000"),
        )

    def test_encodes_and_decodes_word_ordered_register_formats(self) -> None:
        self.assertEqual(encode_register_value(25.5, "2f"), bytes.fromhex("41cc0000"))
        self.assertEqual(encode_register_value(25.5, "2f", high_word_first=False), bytes.fromhex("000041cc"))
        self.assertEqual(decode_register_value(bytes.fromhex("41cc0000"), "2f"), 25.5)
        self.assertEqual(
            decode_register_value(bytes.fromhex("000041cc"), "2f", high_word_first=False),
            25.5,
        )
        self.assertEqual(encode_register_value("AB", "2s"), bytes.fromhex("00410042"))
        self.assertEqual(decode_register_value(bytes.fromhex("00410042"), "2s"), "AB")

    def test_rejects_malformed_formats_and_register_payloads(self) -> None:
        with self.assertRaises(ValueError):
            encode_register_value(1, "3i")
        with self.assertRaises(ValueError):
            build_read_request(1, 0, 126)
        with self.assertRaises(ValueError):
            decode_register_value(b"\x00\x01", "2i")


class ModbusTcpClientTests(unittest.TestCase):
    def test_reads_and_writes_using_a_local_modbus_tcp_peer(self) -> None:
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
                    read_request = _receive_exactly(connection, 12)
                    transaction_id, protocol_id, length, unit_id, function, address, quantity = (
                        struct.unpack(">HHHBBHH", read_request)
                    )
                    if (protocol_id, length, unit_id, function, address, quantity) != (
                        0,
                        6,
                        1,
                        3,
                        0x1234,
                        2,
                    ):
                        raise AssertionError(f"unexpected read request: {read_request.hex()}")
                    response = (
                        struct.pack(">HHHBBBH", transaction_id, 0, 7, unit_id, 3, 4, 0x41CC)
                        + struct.pack(">H", 0)
                    )
                    connection.sendall(response[:3])
                    connection.sendall(response[3:])

                    write_header = _receive_exactly(connection, 13)
                    (
                        write_transaction_id,
                        protocol_id,
                        length,
                        unit_id,
                        function,
                        address,
                        quantity,
                        byte_count,
                    ) = struct.unpack(">HHHBBHHB", write_header)
                    data = _receive_exactly(connection, byte_count)
                    if (protocol_id, length, unit_id, function, address, quantity, data) != (
                        0,
                        11,
                        1,
                        0x10,
                        0x2345,
                        2,
                        bytes.fromhex("41cc0000"),
                    ):
                        raise AssertionError(f"unexpected write request: {write_header.hex()}{data.hex()}")
                    connection.sendall(
                        struct.pack(">HHHBBHH", write_transaction_id, 0, 6, unit_id, 0x10, address, quantity)
                    )
            except BaseException as error:
                server_errors.append(error)
            finally:
                listener.close()

        server = threading.Thread(target=serve, daemon=True)
        server.start()
        try:
            with ModbusTcpClient("127.0.0.1", port, timeout=2) as client:
                self.assertEqual(client.read_value(0x1234, "2f"), 25.5)
                client.write_value(0x2345, 25.5, "2f")
        finally:
            server.join(timeout=5)

        self.assertFalse(server.is_alive(), "local Modbus peer did not finish")
        self.assertEqual(server_errors, [])

    def test_reports_modbus_exception_responses(self) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(4)
        port = listener.getsockname()[1]

        def serve_exception() -> None:
            connection = listener.accept()[0]
            with connection:
                request = _receive_exactly(connection, 12)
                transaction_id = struct.unpack(">H", request[:2])[0]
                connection.sendall(struct.pack(">HHHBBB", transaction_id, 0, 3, 1, 0x83, 2))
            listener.close()

        server = threading.Thread(target=serve_exception, daemon=True)
        server.start()
        client = ModbusTcpClient("127.0.0.1", port, timeout=2)
        try:
            with self.assertRaisesRegex(ModbusProtocolError, "exception code: 2"):
                client.read_registers(0x100, 1)
        finally:
            client.close()
            server.join(timeout=5)
        self.assertFalse(server.is_alive(), "local Modbus peer did not finish")


def _receive_exactly(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise AssertionError("client closed before completing the request")
        data.extend(chunk)
    return bytes(data)


if __name__ == "__main__":
    unittest.main()
