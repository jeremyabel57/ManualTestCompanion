from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Protocol

from .visa import InstrumentSession


class _ScpiSession(Protocol):
    def query(self, command: str) -> str: ...

    def write(self, command: str) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class FrequencyStats:
    count: int
    frequency_hz: float
    mean_hz: float
    standard_deviation_hz: float
    minimum_hz: float
    maximum_hz: float
    allan_deviation_hz: float

    @property
    def stability_ppm(self) -> float | None:
        if self.mean_hz == 0:
            return None
        return self.allan_deviation_hz * 1_000_000 / self.mean_hz


class FrequencyCounter:
    """Agilent/Keysight frequency-counter sampling and Allan deviation."""

    def __init__(self, session: _ScpiSession | InstrumentSession) -> None:
        self.session = session

    def identify(self) -> str:
        return self.session.query("*IDN?").strip()

    def initialize(self) -> None:
        for command in (
            ":ABORt",
            "*RST",
            "*CLS",
            ":CONFigure:FREQuency (@1)",
            "*CLS",
            ":INPut1:COUPling AC",
            ":INPut1:IMPedance 50",
            ":INPut1:LEVel:AUTO OFF",
            ":INPut1:LEVel 0.0",
            ":INPut1:NREJect OFF",
            ":SENSe:FREQuency:MODE RCON",
            ":SENSe:FREQuency:GATE:TIME 0.1",
            ":SAMPle:COUNt 1000000",
            ":TRIGger:COUNt 1",
            ":TRIGger:DELay 0",
            ":CALCulate:STATe ON",
            ":CALCulate:AVERage:STATe ON",
            ":CALCulate:AVERage:CLEar",
            ":INITiate:IMMediate",
        ):
            self.session.write(command)

    def reset_statistics(self) -> None:
        for command in (
            ":ABORt",
            ":CALCulate:AVERage:CLEar",
            ":INITiate:IMMediate",
        ):
            self.session.write(command)

    def read_count(self) -> int:
        response = self.session.query(":DATA:POINts?")
        try:
            value = float(response.strip())
        except ValueError as error:
            raise ValueError(f"invalid frequency-counter sample count: {response!r}") from error
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            raise ValueError(f"invalid frequency-counter sample count: {response!r}")
        return int(value)

    def read_sample(self) -> FrequencyStats | None:
        count = self.read_count()
        if count <= 2:
            return None

        self.session.write(":ABORt")
        time.sleep(0.1)
        try:
            frequency = _parse_scalar(
                self.session.query(":DATA:LAST?"),
                "last frequency",
            )
            mean, standard_deviation, minimum, maximum = _parse_statistics(
                self.session.query(":CALCulate:AVERage:ALL?")
            )
            allan_deviation = _parse_scalar(
                self.session.query(":CALCulate:AVERage:ADEViation?"),
                "Allan deviation",
            )
        finally:
            self.session.write(":INITiate:IMMediate")
        return FrequencyStats(
            count,
            frequency,
            mean,
            standard_deviation,
            minimum,
            maximum,
            allan_deviation,
        )

    def close(self) -> None:
        self.session.close()


def _parse_scalar(response: str, name: str) -> float:
    try:
        value = float(response.strip().split(maxsplit=1)[0])
    except (ValueError, IndexError) as error:
        raise ValueError(f"invalid {name} response: {response!r}") from error
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite: {response!r}")
    return value


def _parse_statistics(response: str) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(part.strip()) for part in response.split(","))
    except ValueError as error:
        raise ValueError(f"invalid frequency statistics response: {response!r}") from error
    if len(values) < 4 or any(not math.isfinite(value) for value in values[:4]):
        raise ValueError(f"expected four finite frequency statistics: {response!r}")
    return values[0], values[1], values[2], values[3]
