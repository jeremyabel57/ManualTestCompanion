from __future__ import annotations

from typing import Protocol

from .modbus import ModbusProtocolError, ModbusTcpClient


class _ModbusTransport(Protocol):
    high_word_first: bool

    def read_value(self, address: int, format_string: str) -> int | float | str: ...

    def write_value(
        self, address: int, value: int | float | str, format_string: str
    ) -> None: ...

    def close(self) -> None: ...


class F4TChamber:
    """Test Equity/Watlow F4T temperature and output controls over Modbus TCP."""

    def __init__(
        self,
        client: _ModbusTransport | ModbusTcpClient,
        *,
        data_map: int | None = None,
        high_word_first: bool | None = None,
        units_celsius: bool | None = None,
    ) -> None:
        if data_map is not None and data_map not in {1, 2}:
            raise ValueError("F4T data_map must be 1 or 2")
        self.client = client
        self.data_map = data_map
        self._high_word_first = high_word_first
        self._units_celsius = units_celsius

    @property
    def units_celsius(self) -> bool:
        self._configure()
        return bool(self._units_celsius)

    def read_temperature_c(self) -> float:
        return self._to_celsius(float(self._read(1)))

    def read_setpoint_c(self) -> float:
        return self._to_celsius(float(self._read(0)))

    def set_setpoint_c(self, temperature: float) -> None:
        self._configure()
        device_temperature = temperature if self._units_celsius else celsius_to_fahrenheit(temperature)
        self._write(0, device_temperature)

    def read_enabled(self) -> bool:
        return bool(int(self._read(2)) & 1)

    def set_enabled(self, enabled: bool) -> None:
        self._configure()
        value = (62 | int(enabled)) if self.data_map == 1 else int(enabled)
        self._write(2, value)

    def read_heating_percent(self) -> float:
        return self._read_output(3)

    def read_cooling_percent(self) -> float:
        return self._read_output(4)

    def close(self) -> None:
        self.client.close()

    def _configure(self) -> None:
        if self.data_map is None:
            try:
                probe = int(self.client.read_value(100, "1i"))
            except ModbusProtocolError:
                self.data_map = 1
            else:
                self.data_map = 1 if probe == 0 or probe >> 8 == 0x83 else 2

        if self._high_word_first is None:
            self._high_word_first = True
            if self.data_map == 1:
                try:
                    order = int(self.client.read_value(14092, "1i"))
                    if order | 1 != 1331:
                        order = int(self.client.read_value(6736, "1i"))
                    if order | 1 == 1331:
                        self._high_word_first = not bool(order & 1)
                except ModbusProtocolError:
                    self._high_word_first = True
            self.client.high_word_first = self._high_word_first

        if self._units_celsius is None:
            if self.data_map == 1:
                self._units_celsius = int(self.client.read_value(6730, "1i")) == 15
            else:
                self._units_celsius = bool(int(self.client.read_value(901, "1i")) & 1)

    def _read(self, index: int) -> float | int:
        self._configure()
        if self.data_map == 1:
            address, format_string = ((2782, "2f"), (27586, "2f"), (16594, "1i"))[index]
            value = self.client.read_value(address, format_string)
            return int(value) if index == 2 else float(value)
        address = (300, 100, 2000)[index]
        value = int(self.client.read_value(address, "1i"))
        return value if index == 2 else value / 10

    def _write(self, index: int, value: float | int) -> None:
        self._configure()
        if self.data_map == 1 and index != 2:
            address, format_string = (2782, "2f")
            self.client.write_value(address, value, format_string)
            return
        address = (2782, 27586, 16594)[index] if self.data_map == 1 else (300, 100, 2000)[index]
        format_string = "1i" if index == 2 or self.data_map == 2 else "2f"
        device_value = int(value) if index == 2 else int(round(float(value) * 10))
        self.client.write_value(address, device_value, format_string)

    def _read_output(self, index: int) -> float:
        self._configure()
        if self.data_map == 1:
            address = 2804 if index == 3 else 2806
            return float(self.client.read_value(address, "2f"))
        address = 103 if index == 3 else 107
        return int(self.client.read_value(address, "1i")) / 10

    def _to_celsius(self, temperature: float) -> float:
        self._configure()
        return temperature if self._units_celsius else fahrenheit_to_celsius(temperature)


def celsius_to_fahrenheit(temperature: float) -> float:
    return temperature * 9 / 5 + 32


def fahrenheit_to_celsius(temperature: float) -> float:
    return (temperature - 32) * 5 / 9
