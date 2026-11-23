from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
import zipfile

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


def load_measurement_script(path: Path, *, capture: bool) -> tuple[str, ...]:
    """Read the #set or #get SCPI section from a legacy measurement script."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"could not read measurement script {path}: {error}") from error

    wanted = "#get" if capture else "#set"
    commands: list[str] = []
    inside = False
    saw_wanted = False

    for raw_line in lines:
        line = raw_line.strip()
        marker = line.casefold()
        if marker in {"#set", "#get"}:
            if marker == wanted:
                inside = not inside
                if inside:
                    saw_wanted = True
            else:
                inside = False
            continue
        if inside and line and not line.startswith("#"):
            commands.append(line)

    if not saw_wanted:
        raise ValueError(f"measurement script {path} has no {wanted} section")
    if not commands:
        raise ValueError(f"measurement script {path} {wanted} section is empty")
    return tuple(commands)


def load_scope_setup(path: Path) -> tuple[str, ...]:
    """Load SCPI commands from a plain setup file or legacy ZIP .set file."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as archive:
                setup_members = [
                    member
                    for member in archive.infolist()
                    if not member.is_dir() and member.filename.casefold().endswith(".set")
                ]
                if not setup_members:
                    raise ValueError(f"scope setup {path} contains no .set payload")
                payload = archive.read(setup_members[0]).decode("utf-8-sig")
        else:
            payload = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as error:
        raise ValueError(f"could not read scope setup {path}: {error}") from error

    commands: list[str] = []
    for line in payload.replace("\r", "").split("\n"):
        for command in line.split(";"):
            command = command.strip()
            if command:
                commands.append(command)
    if not commands:
        raise ValueError(f"scope setup {path} contains no SCPI commands")
    return tuple(commands)


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
