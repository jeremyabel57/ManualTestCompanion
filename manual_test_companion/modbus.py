from __future__ import annotations

import math
import re
import socket
import struct
import threading
from dataclasses import dataclass


class ModbusProtocolError(RuntimeError):
    """Raised when a Modbus TCP peer returns an invalid or exceptional response."""


@dataclass(frozen=True)
class RegisterFormat:
    word_count: int
    kind: str

    @classmethod
    def parse(cls, value: str) -> RegisterFormat:
        match = re.fullmatch(r"([1-9]\d*)([ifs])", value.strip().lower())
        if match is None:
            raise ValueError(f"unsupported Modbus register format: {value!r}")
        count = int(match.group(1))
        kind = match.group(2)
        if kind in {"i", "f"} and count not in {1, 2}:
            raise ValueError(f"{kind!r} values require one or two registers")
        return cls(count, kind)


def build_read_request(
    transaction_id: int,
    address: int,
    quantity: int,
    unit_id: int = 1,
) -> bytes:
    _validate_unsigned("transaction ID", transaction_id, 16)
    _validate_unsigned("register address", address, 16)
    _validate_unsigned("unit ID", unit_id, 8)
    if not 1 <= quantity <= 125:
        raise ValueError("read quantity must be between 1 and 125 registers")
    return struct.pack(">HHHBBHH", transaction_id, 0, 6, unit_id, 0x03, address, quantity)


def build_write_request(
    transaction_id: int,
    address: int,
    data: bytes,
    unit_id: int = 1,
) -> bytes:
    _validate_unsigned("transaction ID", transaction_id, 16)
    _validate_unsigned("register address", address, 16)
    _validate_unsigned("unit ID", unit_id, 8)
    if not data or len(data) % 2:
        raise ValueError("write data must contain a non-zero whole number of registers")
    quantity = len(data) // 2
    if quantity > 123:
        raise ValueError("write quantity must not exceed 123 registers")
    byte_count = len(data)
    length = 7 + byte_count
    return (
        struct.pack(">HHHBBHHB", transaction_id, 0, length, unit_id, 0x10, address, quantity, byte_count)
        + data
    )


def encode_register_value(
    value: int | float | str,
    format_string: str,
    *,
    high_word_first: bool = True,
) -> bytes:
    register_format = RegisterFormat.parse(format_string)
    if register_format.kind == "s":
        if not isinstance(value, str):
            raise TypeError("string register formats require a string value")
        encoded = value.encode("utf-16-be")
        return encoded + (b"\x00" if len(encoded) % 2 else b"")

    if register_format.kind == "i":
        width = register_format.word_count * 2
        integer = int(value)
        encoded = (integer % (1 << (width * 8))).to_bytes(width, "big")
    else:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Modbus floating-point writes require a finite number")
        encoded = struct.pack(">e" if register_format.word_count == 1 else ">f", number)
    return _apply_word_order(encoded, high_word_first)


def decode_register_value(data: bytes, format_string: str, *, high_word_first: bool = True) -> int | float | str:
    register_format = RegisterFormat.parse(format_string)
    expected_length = register_format.word_count * 2
    if len(data) != expected_length:
        raise ValueError(
            f"format {format_string!r} requires {expected_length} bytes, got {len(data)}"
        )
    if register_format.kind == "s":
        return data.decode("utf-16-be").rstrip("\x00")
    ordered = _apply_word_order(data, high_word_first)
    if register_format.kind == "i":
        return int.from_bytes(ordered, "big")
    return struct.unpack(">e" if register_format.word_count == 1 else ">f", ordered)[0]


def _apply_word_order(data: bytes, high_word_first: bool) -> bytes:
    if len(data) > 2 and not high_word_first:
        words = [data[index : index + 2] for index in range(0, len(data), 2)]
        return b"".join(reversed(words))
    return data


def _validate_unsigned(name: str, value: int, bits: int) -> None:
    if not isinstance(value, int) or not 0 <= value < (1 << bits):
        raise ValueError(f"{name} must be an unsigned {bits}-bit integer")


class ModbusTcpClient:
    """Synchronous Modbus TCP client with validated MBAP framing."""

    def __init__(
        self,
        host: str,
        port: int = 502,
        *,
        unit_id: int = 1,
        timeout: float = 1.5,
        high_word_first: bool = True,
    ) -> None:
        if not host.strip():
            raise ValueError("host must not be empty")
        _validate_unsigned("port", port, 16)
        if port == 0:
            raise ValueError("port must be between 1 and 65535")
        _validate_unsigned("unit ID", unit_id, 8)
        if timeout <= 0 or not math.isfinite(timeout):
            raise ValueError("timeout must be a finite positive number")
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.high_word_first = high_word_first
        self._transaction_id = 0x100
        self._socket: socket.socket | None = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        with self._lock:
            if self._socket is not None:
                return
            self._socket = socket.create_connection((self.host, self.port), self.timeout)
            self._socket.settimeout(self.timeout)

    def close(self) -> None:
        with self._lock:
            self._close_socket()

    def read_registers(self, address: int, quantity: int) -> tuple[int, ...]:
        with self._lock:
            transaction_id = self._next_transaction_id()
            request = build_read_request(transaction_id, address, quantity, self.unit_id)
            response = self._exchange(transaction_id, request, 0x03)
            if len(response) < 2:
                raise ModbusProtocolError("read response is missing its byte count")
            byte_count = response[1]
            register_bytes = response[2:]
            if byte_count != len(register_bytes) or byte_count != quantity * 2:
                raise ModbusProtocolError(
                    f"read response declared {byte_count} bytes but returned {len(register_bytes)}"
                )
            return tuple(
                int.from_bytes(register_bytes[index : index + 2], "big")
                for index in range(0, byte_count, 2)
            )

    def write_registers(self, address: int, registers: bytes) -> None:
        with self._lock:
            transaction_id = self._next_transaction_id()
            request = build_write_request(transaction_id, address, registers, self.unit_id)
            response = self._exchange(transaction_id, request, 0x10)
            if len(response) != 5:
                raise ModbusProtocolError("write response has an invalid length")
            echoed_address, echoed_quantity = struct.unpack(">HH", response[1:])
            if echoed_address != address or echoed_quantity != len(registers) // 2:
                raise ModbusProtocolError("write response does not match the request")

    def read_value(self, address: int, format_string: str) -> int | float | str:
        register_format = RegisterFormat.parse(format_string)
        registers = self.read_registers(address, register_format.word_count)
        data = b"".join(value.to_bytes(2, "big") for value in registers)
        return decode_register_value(data, format_string, high_word_first=self.high_word_first)

    def write_value(self, address: int, value: int | float | str, format_string: str) -> None:
        data = encode_register_value(value, format_string, high_word_first=self.high_word_first)
        self.write_registers(address, data)

    def __enter__(self) -> ModbusTcpClient:
        self.connect()
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        del _exc_type, _exc_value, _traceback
        self.close()

    def _next_transaction_id(self) -> int:
        self._transaction_id = (self._transaction_id + 1) & 0xFFFF
        return self._transaction_id

    def _exchange(self, transaction_id: int, request: bytes, function_code: int) -> bytes:
        try:
            if self._socket is None:
                self._socket = socket.create_connection((self.host, self.port), self.timeout)
                self._socket.settimeout(self.timeout)
            self._socket.sendall(request)
            header = _recv_exactly(self._socket, 7)
            response_transaction, protocol_id, length, unit_id = struct.unpack(">HHHB", header)
            if not 2 <= length <= 254:
                raise ModbusProtocolError(f"invalid Modbus response length: {length}")
            if response_transaction != transaction_id:
                raise ModbusProtocolError("response transaction ID does not match the request")
            if protocol_id != 0:
                raise ModbusProtocolError(f"unexpected Modbus protocol ID: {protocol_id}")
            if unit_id != self.unit_id:
                raise ModbusProtocolError(f"unexpected Modbus unit ID: {unit_id}")
            pdu = _recv_exactly(self._socket, length - 1)
        except (OSError, ModbusProtocolError):
            self._close_socket()
            raise

        response_function = pdu[0]
        if response_function == function_code | 0x80:
            if len(pdu) < 2:
                raise ModbusProtocolError("Modbus exception response is missing its exception code")
            raise ModbusProtocolError(f"Modbus exception code: {pdu[1]}")
        if response_function != function_code:
            raise ModbusProtocolError(
                f"unexpected function code: 0x{response_function:02x}"
            )
        return pdu

    def _close_socket(self) -> None:
        if self._socket is None:
            return
        connection = self._socket
        self._socket = None
        connection.close()


def _recv_exactly(connection: socket.socket, length: int) -> bytes:
    received = bytearray()
    while len(received) < length:
        chunk = connection.recv(length - len(received))
        if not chunk:
            raise ModbusProtocolError("connection closed before the Modbus frame was complete")
        received.extend(chunk)
    return bytes(received)
