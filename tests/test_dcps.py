import unittest

from manual_test_companion.dcps import DCPSController


class FakeScpiSession:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.closed = False

    def query(self, command: str) -> str:
        self.commands.append(("query", command))
        if command == "*IDN?":
            return "Keysight Technologies,N6705B,MY53000443,D.02.15\n"
        responses = {
            ":MEAS:VOLT? (@1:4)": "12, 12, 3.3, 0",
            ":MEAS:CURR? (@1:4)": "0.5, 0.1, 0.2, 0",
            ":VOLT? (@1:4)": "12, 12, 3.3, 0",
            ":CURR? (@1:4)": "5, 5, 2.5, 1",
            ":OUTP:STAT? (@1:4)": "1, 0, 1, 0",
        }
        return responses[command]

    def write(self, command: str) -> None:
        self.commands.append(("write", command))

    def close(self) -> None:
        self.closed = True


class DCPSControllerTests(unittest.TestCase):
    def test_reads_four_channel_snapshot_and_identification(self) -> None:
        session = FakeScpiSession()
        supply = DCPSController(session)

        self.assertEqual(
            supply.identify(),
            "Keysight Technologies,N6705B,MY53000443,D.02.15",
        )
        reading = supply.read_all()

        self.assertEqual(len(reading.channels), 4)
        self.assertEqual(reading.channels[0].measured_voltage, 12)
        self.assertEqual(reading.channels[0].measured_power_mw, 6000)
        self.assertTrue(reading.channels[0].output_enabled)
        self.assertFalse(reading.channels[1].output_enabled)
        self.assertEqual(
            [command for kind, command in session.commands if kind == "query"][1:],
            [
                ":MEAS:VOLT? (@1:4)",
                ":MEAS:CURR? (@1:4)",
                ":VOLT? (@1:4)",
                ":CURR? (@1:4)",
                ":OUTP:STAT? (@1:4)",
            ],
        )

    def test_writes_channel_commands_and_rejects_invalid_values(self) -> None:
        session = FakeScpiSession()
        supply = DCPSController(session)

        supply.set_voltage(2, 3.3)
        supply.set_current_limit(3, 2.5)
        supply.set_output(4, True)
        supply.emergency_off()

        self.assertEqual(
            session.commands,
            [
                ("write", ":VOLT 3.3, (@2)"),
                ("write", ":CURR 2.5, (@3)"),
                ("write", ":OUTP ON, (@4)"),
                ("write", ":OUTP OFF, (@1:4)"),
            ],
        )
        with self.assertRaisesRegex(ValueError, "channel"):
            supply.set_output(5, False)
        with self.assertRaisesRegex(ValueError, "finite"):
            supply.set_voltage(1, float("nan"))

    def test_rejects_incomplete_channel_response(self) -> None:
        class BadSession(FakeScpiSession):
            def query(self, command: str) -> str:
                if command == ":MEAS:VOLT? (@1:4)":
                    return "12, 12"
                return super().query(command)

        with self.assertRaisesRegex(ValueError, "expected four finite channel values"):
            DCPSController(BadSession()).read_all()


if __name__ == "__main__":
    unittest.main()
