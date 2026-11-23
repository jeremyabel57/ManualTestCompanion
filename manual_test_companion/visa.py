from __future__ import annotations

import select
import socket
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InstrumentAddress:
    host: str
    port: int | str
    raw_socket: bool

    @classmethod
    def parse(cls, value: str) -> InstrumentAddress:
        address = value.strip().split(maxsplit=1)[0] if value.strip() else ""
        if not address:
            raise ValueError("instrument address must not be empty")
        raw_socket = address[:4].casefold() == "raw:"
        if raw_socket:
            address = address[4:]
        if ":" in address:
            host, port_text = address.split(":", 1)
            if not port_text:
                raise ValueError(f"instrument address has an empty port: {value!r}")
        else:
            host = address
            port_text = "5025" if raw_socket else "inst0"
        if not host:
            raise ValueError(f"instrument address has no host: {value!r}")
        if raw_socket:
            try:
                port: int | str = int(port_text)
            except ValueError as error:
                raise ValueError(f"raw socket port must be numeric: {port_text!r}") from error
            if not 1 <= port <= 65535:
                raise ValueError(f"raw socket port is out of range: {port}")
        else:
            port = port_text
        return cls(host=host, port=port, raw_socket=raw_socket)

    @property
    def visa_resource(self) -> str:
        if self.raw_socket:
            return f"TCPIP::{self.host}::{self.port}::SOCKET"
        return f"TCPIP0::{self.host}::{self.port}::INSTR"


class InstrumentSession:
    """Persistent SCPI session using a raw socket or the system VISA backend."""

    _MAX_REPLY_SIZE = 1024 * 1024
    _MAX_BINARY_REPLY_SIZE = 512 * 1024 * 1024

    def __init__(self, address: str | InstrumentAddress, *, timeout: float = 1.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.address = (
            InstrumentAddress.parse(address) if isinstance(address, str) else address
        )
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._read_buffer = bytearray()
        self._resource_manager: Any = None
        self._resource: Any = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        with self._lock:
            if self.address.raw_socket:
                if self._socket is None:
                    self._socket = socket.create_connection(
                        (self.address.host, int(self.address.port)), self.timeout
                    )
                    self._socket.settimeout(self.timeout)
                return
            if self._resource is not None:
                return
            try:
                import pyvisa
            except ImportError as error:
                raise RuntimeError("PyVISA is required for VISA instrument connections") from error
            manager = pyvisa.ResourceManager()
            try:
                resource: Any = manager.open_resource(self.address.visa_resource)
                resource.timeout = round(self.timeout * 1000)
                resource.read_termination = "\n"
                resource.write_termination = "\n"
            except Exception:
                manager.close()
                raise
            self._resource_manager = manager
            self._resource = resource

    def write(self, command: str) -> None:
        with self._lock:
            self.connect()
            if self.address.raw_socket:
                try:
                    self._require_socket().sendall(_command_bytes(command))
                except OSError:
                    self.close()
                    raise
            else:
                self._require_resource().write(command)

    def query(self, command: str) -> str:
        with self._lock:
            self.connect()
            if self.address.raw_socket:
                try:
                    self._require_socket().sendall(_command_bytes(command))
                    return self._readline()
                except (OSError, ValueError):
                    self.close()
                    raise
            return str(self._require_resource().query(command)).rstrip("\r\n")

    def write_raw(self, data: bytes) -> None:
        with self._lock:
            self.connect()
            if self.address.raw_socket:
                try:
                    self._require_socket().sendall(data)
                except OSError:
                    self.close()
                    raise
            else:
                self._require_resource().write_raw(data)

    def query_binary(self, command: str) -> bytes:
        """Read a definite-length IEEE 488.2 binary block from an instrument."""
        with self._lock:
            self.connect()
            if self.address.raw_socket:
                try:
                    self._require_socket().sendall(_command_bytes(command))
                    return self._read_ieee_block()
                except (OSError, ValueError):
                    self.close()
                    raise
            resource = self._require_resource()
            resource.write(command)
            return _parse_ieee_block(bytes(resource.read_raw()))

    def write_binary_block(self, command: str, payload: bytes) -> None:
        header = _ieee_block_header(len(payload))
        self.write_raw(command.encode("utf-8") + header + payload + b"\r\n")

    def close(self) -> None:
        with self._lock:
            connection = self._socket
            self._socket = None
            self._read_buffer.clear()
            resource = self._resource
            manager = self._resource_manager
            self._resource = None
            self._resource_manager = None
            try:
                if connection is not None:
                    connection.close()
            finally:
                try:
                    if resource is not None:
                        resource.close()
                finally:
                    if manager is not None:
                        manager.close()

    def __enter__(self) -> InstrumentSession:
        self.connect()
        return self

    def __exit__(self, _exc_type: object, _exc_value: object, _traceback: object) -> None:
        del _exc_type, _exc_value, _traceback
        self.close()

    def _readline(self) -> str:
        connection = self._require_socket()
        while True:
            newline_index = self._read_buffer.find(b"\n")
            if newline_index >= 0:
                response = bytes(self._read_buffer[:newline_index])
                del self._read_buffer[: newline_index + 1]
                return response.rstrip(b"\r").decode("utf-8")
            if len(self._read_buffer) >= self._MAX_REPLY_SIZE:
                raise ValueError("instrument response exceeded the maximum line length")
            chunk = connection.recv(min(4096, self._MAX_REPLY_SIZE - len(self._read_buffer)))
            if not chunk:
                raise ConnectionError("instrument closed the connection before replying")
            self._read_buffer.extend(chunk)

    def _read_ieee_block(self) -> bytes:
        prefix = self._read_exact(2)
        if prefix[:1] != b"#" or prefix[1:2] not in b"0123456789":
            raise ValueError(f"instrument response is not an IEEE 488.2 block: {prefix!r}")
        digit_count = prefix[1] - ord("0")
        if digit_count == 0:
            raise ValueError("indefinite-length IEEE 488.2 blocks are not supported")
        length_text = self._read_exact(digit_count)
        if not length_text.isdigit():
            raise ValueError(f"invalid IEEE 488.2 block length: {length_text!r}")
        payload_length = int(length_text)
        if payload_length > self._MAX_BINARY_REPLY_SIZE:
            raise ValueError(
                f"binary reply exceeds the {self._MAX_BINARY_REPLY_SIZE}-byte limit"
            )
        payload = self._read_exact(payload_length)
        self._discard_block_terminator()
        return payload

    def _read_exact(self, size: int) -> bytes:
        connection = self._require_socket()
        while len(self._read_buffer) < size:
            chunk = connection.recv(min(65536, size - len(self._read_buffer)))
            if not chunk:
                raise ConnectionError("instrument closed the connection during a binary block")
            self._read_buffer.extend(chunk)
        result = bytes(self._read_buffer[:size])
        del self._read_buffer[:size]
        return result

    def _discard_block_terminator(self) -> None:
        connection = self._require_socket()
        if not self._read_buffer and select.select([connection], [], [], 0.05)[0]:
            self._read_buffer.extend(connection.recv(2))
        if self._read_buffer.startswith(b"\r\n"):
            del self._read_buffer[:2]
        elif self._read_buffer.startswith((b"\r", b"\n")):
            del self._read_buffer[:1]

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise RuntimeError("raw socket is not connected")
        return self._socket

    def _require_resource(self) -> Any:
        if self._resource is None:
            raise RuntimeError("VISA resource is not connected")
        return self._resource


def _command_bytes(command: str) -> bytes:
    return command.rstrip("\r\n").encode("utf-8") + b"\n"


def _ieee_block_header(payload_length: int) -> bytes:
    if payload_length < 0:
        raise ValueError("binary payload length must not be negative")
    length = str(payload_length).encode("ascii")
    if len(length) > 9:
        raise ValueError("IEEE 488.2 blocks support payloads up to 999999999 bytes")
    return b"#" + str(len(length)).encode("ascii") + length


def _parse_ieee_block(response: bytes) -> bytes:
    if len(response) < 2 or response[:1] != b"#" or response[1:2] not in b"0123456789":
        raise ValueError("instrument response is not an IEEE 488.2 binary block")
    digit_count = response[1] - ord("0")
    if digit_count == 0:
        raise ValueError("indefinite-length IEEE 488.2 blocks are not supported")
    length_start = 2
    payload_start = length_start + digit_count
    if len(response) < payload_start:
        raise ValueError("instrument returned a truncated IEEE 488.2 block header")
    length_text = response[length_start:payload_start]
    if not length_text.isdigit():
        raise ValueError(f"invalid IEEE 488.2 block length: {length_text!r}")
    payload_length = int(length_text)
    if payload_length > InstrumentSession._MAX_BINARY_REPLY_SIZE:
        raise ValueError(
            f"binary reply exceeds the {InstrumentSession._MAX_BINARY_REPLY_SIZE}-byte limit"
        )
    payload_end = payload_start + payload_length
    if len(response) < payload_end:
        raise ValueError("instrument returned a truncated IEEE 488.2 binary block")
    return response[payload_start:payload_end]
