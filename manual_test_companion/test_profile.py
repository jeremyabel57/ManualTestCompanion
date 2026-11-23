from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from .config import LegacyConfig


_MAX_BUSES = 8
SCOPE_CHANNELS = tuple(
    [f"CH{index}" for index in range(1, 9)]
    + [f"MATH{index}" for index in range(1, 9)]
    + [f"BUS{index}" for index in range(1, 9)]
    + [f"REF{index}" for index in range(1, 9)]
)


@dataclass(frozen=True)
class TestMeasurement:
    symbol: str
    description: str
    included: bool
    verify_before_capture: bool


@dataclass(frozen=True)
class TestSignal:
    name: str
    description: str


@dataclass(frozen=True)
class I2CProfile:
    measurements: tuple[TestMeasurement, ...]
    signals: tuple[TestSignal, ...]
    bus_count: int
    selected_bus: int
    bus_names: tuple[str, ...]
    channel_assignments: tuple[tuple[str, ...], ...]


def load_i2c_profile(path: Path) -> I2CProfile:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        with path.open("r", encoding="utf-8-sig") as source:
            parser.read_file(source)
    except (OSError, configparser.Error) as error:
        raise ValueError(f"could not read I2C test profile {path}: {error}") from error

    if not parser.has_section("I2C"):
        raise ValueError(f"I2C test profile {path} has no [I2C] section")
    definition = parser["I2C"]
    measurement_count = _read_count(definition, "mn", path)
    signal_count = _read_count(definition, "sn", path)
    if measurement_count < 1 or signal_count < 1:
        raise ValueError(f"I2C test profile {path} must define measurements and signals")

    measurements: list[tuple[str, str]] = []
    for index in range(measurement_count):
        symbol, separator, description = definition.get(f"m{index}", "").partition(",")
        symbol = symbol.strip()
        if not symbol:
            raise ValueError(f"I2C test profile {path} has an empty m{index} measurement")
        measurements.append((symbol, description.strip() if separator else ""))

    signals: list[TestSignal] = []
    for index in range(signal_count):
        name, separator, description = definition.get(f"s{index}", "").partition(",")
        name = name.strip()
        if not name:
            raise ValueError(f"I2C test profile {path} has an empty s{index} signal")
        signals.append(TestSignal(name, description.strip() if separator else ""))

    preferences = LegacyConfig(path, "mI2C")
    bus_count = _bounded_int(preferences.get_str("busn", "1"), 1, _MAX_BUSES, 1)
    selected_bus = _bounded_int(
        preferences.get_str("busi", "1"), 1, bus_count, 1
    )
    bus_names: list[str] = []
    channel_assignments: list[tuple[str, ...]] = []
    for bus_index in range(_MAX_BUSES):
        base = bus_index * signal_count
        bus_names.append(preferences.get_str(f"b{base}name", f"P{bus_index}").strip())
        channels = []
        for signal_index in range(signal_count):
            key_index = base + signal_index + 1
            channel = preferences.get_str(
                f"b{key_index}ch",
                SCOPE_CHANNELS[signal_index % len(SCOPE_CHANNELS)],
            ).strip()
            channels.append(channel if channel in SCOPE_CHANNELS else "")
        channel_assignments.append(tuple(channels))

    return I2CProfile(
        measurements=tuple(
            TestMeasurement(
                symbol,
                description,
                _read_flag(preferences, f"m{index}.1"),
                _read_flag(preferences, f"m{index}.4"),
            )
            for index, (symbol, description) in enumerate(measurements)
        ),
        signals=tuple(signals),
        bus_count=bus_count,
        selected_bus=selected_bus,
        bus_names=tuple(bus_names),
        channel_assignments=tuple(channel_assignments),
    )


def save_i2c_profile(path: Path, profile: I2CProfile) -> None:
    if not 1 <= profile.bus_count <= _MAX_BUSES:
        raise ValueError("I2C bus count must be between 1 and 8")
    if not 1 <= profile.selected_bus <= profile.bus_count:
        raise ValueError("selected I2C bus must be within the configured bus count")
    if len(profile.bus_names) != _MAX_BUSES or len(profile.channel_assignments) != _MAX_BUSES:
        raise ValueError("I2C profile must contain settings for all eight buses")

    values: dict[str, str | int] = {
        "busn": profile.bus_count,
        "busi": profile.selected_bus,
    }
    for index, measurement in enumerate(profile.measurements):
        values[f"m{index}.1"] = int(measurement.included)
        values[f"m{index}.4"] = int(measurement.verify_before_capture)
    signal_count = len(profile.signals)
    for bus_index, bus_name in enumerate(profile.bus_names):
        base = bus_index * signal_count
        values[f"b{base}name"] = bus_name
        for signal_index, signal in enumerate(profile.signals):
            key_index = base + signal_index + 1
            values[f"b{key_index}sig"] = f"{signal.name}:    "
            values[f"b{key_index}ch"] = profile.channel_assignments[bus_index][signal_index]
    LegacyConfig(path, "mI2C").update(values)


def _read_count(section: configparser.SectionProxy, key: str, path: Path) -> int:
    try:
        return int(section.get(key, "0"))
    except ValueError as error:
        raise ValueError(f"I2C test profile {path} has an invalid {key} value") from error


def _read_flag(config: LegacyConfig, key: str) -> bool:
    return config.get_str(key, "1") not in {"0", "false", "False"}


def _bounded_int(value: str, minimum: int, maximum: int, default: int) -> int:
    try:
        result = int(value)
    except ValueError:
        return default
    return min(maximum, max(minimum, result))
