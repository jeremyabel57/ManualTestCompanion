from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, cast

from .visa import InstrumentSession


class _ScpiSession(Protocol):
    def query(self, command: str) -> str: ...

    def write(self, command: str) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DCPSChannelReading:
    measured_voltage: float
    measured_current: float
    voltage_setpoint: float
    current_limit: float
    output_enabled: bool

    @property
    def measured_power_mw(self) -> float:
        return self.measured_voltage * self.measured_current * 1000


@dataclass(frozen=True)
class DCPSReading:
    channels: tuple[DCPSChannelReading, DCPSChannelReading, DCPSChannelReading, DCPSChannelReading]


class DCPSController:
    """Four-channel Keysight N6705B SCPI controls."""

    def __init__(self, session: _ScpiSession | InstrumentSession) -> None:
        self.session = session

    def identify(self) -> str:
        return self.session.query("*IDN?").strip()

    def read_all(self) -> DCPSReading:
        measured_voltages = self._query_channels(":MEAS:VOLT? (@1:4)")
        measured_currents = self._query_channels(":MEAS:CURR? (@1:4)")
        voltage_setpoints = self._query_channels(":VOLT? (@1:4)")
        current_limits = self._query_channels(":CURR? (@1:4)")
        output_states = self._query_channels(":OUTP:STAT? (@1:4)")
        channels = tuple(
            DCPSChannelReading(
                measured_voltage=measured_voltages[index],
                measured_current=measured_currents[index],
                voltage_setpoint=voltage_setpoints[index],
                current_limit=current_limits[index],
                output_enabled=bool(output_states[index]),
            )
            for index in range(4)
        )
        return DCPSReading(
            cast(
                tuple[
                    DCPSChannelReading,
                    DCPSChannelReading,
                    DCPSChannelReading,
                    DCPSChannelReading,
                ],
                channels,
            )
        )

    def set_voltage(self, channel: int, voltage: float) -> None:
        _validate_channel(channel)
        _validate_finite(voltage, "voltage")
        self.session.write(f":VOLT {_format_number(voltage)}, (@{channel})")

    def set_current_limit(self, channel: int, current: float) -> None:
        _validate_channel(channel)
        _validate_finite(current, "current limit")
        self.session.write(f":CURR {_format_number(current)}, (@{channel})")

    def set_output(self, channel: int, enabled: bool) -> None:
        _validate_channel(channel)
        state = "ON" if enabled else "OFF"
        self.session.write(f":OUTP {state}, (@{channel})")

    def emergency_off(self) -> None:
        self.session.write(":OUTP OFF, (@1:4)")

    def close(self) -> None:
        self.session.close()

    def _query_channels(self, command: str) -> tuple[float, float, float, float]:
        response = self.session.query(command)
        try:
            values = tuple(float(part.strip()) for part in response.split(","))
        except ValueError as error:
            raise ValueError(f"invalid channel response for {command}: {response!r}") from error
        if len(values) != 4 or any(not math.isfinite(value) for value in values):
            raise ValueError(f"expected four finite channel values for {command}: {response!r}")
        return cast(tuple[float, float, float, float], values)


def _validate_channel(channel: int) -> None:
    if not 1 <= channel <= 4:
        raise ValueError(f"channel must be between 1 and 4: {channel}")


def _validate_finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


def _format_number(value: float) -> str:
    return format(value, ".12g")
