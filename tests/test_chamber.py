import unittest

from manual_test_companion.chamber import F4TChamber
from manual_test_companion.modbus import ModbusProtocolError


class FakeModbusClient:
    def __init__(self, values: dict[int, object]) -> None:
        self.values = values
        self.high_word_first = True
        self.reads: list[tuple[int, str]] = []
        self.writes: list[tuple[int, object, str]] = []
        self.closed = False

    def read_value(self, address: int, format_string: str) -> int | float | str:
        self.reads.append((address, format_string))
        value = self.values[address]
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def write_value(self, address: int, value: int | float | str, format_string: str) -> None:
        self.writes.append((address, value, format_string))

    def close(self) -> None:
        self.closed = True


class F4TChamberTests(unittest.TestCase):
    def test_detects_new_register_map_and_controls_outputs(self) -> None:
        client = FakeModbusClient(
            {
                100: ModbusProtocolError("illegal address"),
                14092: 1330,
                6730: 15,
                27586: 22.5,
                2782: 23.0,
                16594: 63,
                2804: 35.5,
                2806: 0.0,
            }
        )
        chamber = F4TChamber(client)

        self.assertEqual(chamber.read_temperature_c(), 22.5)
        self.assertEqual(chamber.read_setpoint_c(), 23.0)
        self.assertTrue(chamber.read_enabled())
        self.assertEqual(chamber.read_heating_percent(), 35.5)
        self.assertEqual(chamber.read_cooling_percent(), 0.0)
        chamber.set_setpoint_c(25.5)
        chamber.set_enabled(False)

        self.assertEqual(chamber.data_map, 1)
        self.assertTrue(client.high_word_first)
        self.assertEqual(client.writes, [(2782, 25.5, "2f"), (16594, 62, "1i")])

    def test_detects_legacy_map_and_converts_fahrenheit_setpoint(self) -> None:
        client = FakeModbusClient({100: [4660, 770], 901: 0})
        chamber = F4TChamber(client)

        self.assertAlmostEqual(chamber.read_temperature_c(), 25.0)
        self.assertFalse(chamber.units_celsius)
        chamber.set_setpoint_c(25.0)
        chamber.set_enabled(True)

        self.assertEqual(chamber.data_map, 2)
        self.assertEqual(client.writes, [(300, 770, "1i"), (2000, 1, "1i")])

    def test_reports_failed_modbus_probe_errors_other_than_register_exceptions(self) -> None:
        client = FakeModbusClient({100: OSError("connection refused")})

        with self.assertRaisesRegex(OSError, "connection refused"):
            F4TChamber(client).read_temperature_c()


if __name__ == "__main__":
    unittest.main()
