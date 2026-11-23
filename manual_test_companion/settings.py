from __future__ import annotations

from dataclasses import dataclass

from .config import LegacyConfig


@dataclass(frozen=True)
class TestVariable:
    name: str
    value: str


def load_test_variables(config_path) -> tuple[TestVariable, ...]:
    config = LegacyConfig(config_path, "Variables")
    row_count = max(0, config.get_int("v_r", 0))
    column_count = config.get_int("v_c", 0)
    if row_count == 0:
        row_count = config.get_int("v_n", 0)
        column_count = 1
    if row_count == 0 or column_count == 0:
        return ()

    variables: list[TestVariable] = []
    for row in range(row_count):
        if column_count >= 2:
            name = config.get_str(f"v_{row}.0", "").strip()
            value = config.get_str(f"v_{row}.1", "")
        else:
            name = ""
            value = config.get_str(f"v_{row}", "")
        if name or value:
            variables.append(TestVariable(name, value))
    return tuple(variables)


def save_test_variables(config_path, variables: tuple[TestVariable, ...]) -> None:
    values: dict[str, str | int] = {
        "v_r": len(variables),
        "v_c": 2,
    }
    for row, variable in enumerate(variables):
        values[f"v_{row}.0"] = variable.name
        values[f"v_{row}.1"] = variable.value
    LegacyConfig(config_path, "Variables").update(values)
