import unittest
from unittest.mock import patch

from manual_test_companion.frequency_counter import FrequencyCounter, FrequencyStats


class FakeScpiSession:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.responses = {
            "*IDN?": "Agilent Technologies,53230A,MY123456,1.0\n",
            ":DATA:POINts?": "1000",
            ":DATA:LAST?": "+1.000001E+08",
            ":CALCulate:AVERage:ALL?": "100000000, 0.25, 99999999, 100000001",
            ":CALCulate:AVERage:ADEViation?": "0.01",
        }

    def query(self, command: str) -> str:
        self.commands.append(("query", command))
        value = self.responses[command]
        if isinstance(value, Exception):
            raise value
        return value

    def write(self, command: str) -> None:
        self.commands.append(("write", command))

    def close(self) -> None:
        pass


class FrequencyCounterTests(unittest.TestCase):
    def test_reads_statistics_and_restarts_continuous_acquisition(self) -> None:
        session = FakeScpiSession()
        counter = FrequencyCounter(session)

        with patch("manual_test_companion.frequency_counter.time.sleep"):
            result = counter.read_sample()

        self.assertEqual(
            result,
            FrequencyStats(
                count=1000,
                frequency_hz=100000100,
                mean_hz=100000000,
                standard_deviation_hz=0.25,
                minimum_hz=99999999,
                maximum_hz=100000001,
                allan_deviation_hz=0.01,
            ),
        )
        self.assertAlmostEqual(result.stability_ppm, 0.0001)
        self.assertEqual(
            session.commands,
            [
                ("query", ":DATA:POINts?"),
                ("write", ":ABORt"),
                ("query", ":DATA:LAST?"),
                ("query", ":CALCulate:AVERage:ALL?"),
                ("query", ":CALCulate:AVERage:ADEViation?"),
                ("write", ":INITiate:IMMediate"),
            ],
        )

    def test_skips_statistics_for_too_few_samples(self) -> None:
        session = FakeScpiSession()
        session.responses[":DATA:POINts?"] = "2"

        self.assertIsNone(FrequencyCounter(session).read_sample())
        self.assertEqual(session.commands, [("query", ":DATA:POINts?")])

    def test_restarts_acquisition_when_statistics_read_fails(self) -> None:
        session = FakeScpiSession()
        session.responses[":CALCulate:AVERage:ALL?"] = OSError("read failed")

        with patch("manual_test_companion.frequency_counter.time.sleep"):
            with self.assertRaisesRegex(OSError, "read failed"):
                FrequencyCounter(session).read_sample()

        self.assertEqual(session.commands[-1], ("write", ":INITiate:IMMediate"))

    def test_initializes_raw_continuous_frequency_measurement(self) -> None:
        session = FakeScpiSession()

        FrequencyCounter(session).initialize()

        self.assertEqual(session.commands[0], ("write", ":ABORt"))
        self.assertIn(("write", ":SENSe:FREQuency:MODE RCON"), session.commands)
        self.assertIn(("write", ":CALCulate:AVERage:CLEar"), session.commands)
        self.assertEqual(session.commands[-1], ("write", ":INITiate:IMMediate"))

    def test_rejects_malformed_sample_counts(self) -> None:
        session = FakeScpiSession()
        session.responses[":DATA:POINts?"] = "not-a-count"

        with self.assertRaisesRegex(ValueError, "sample count"):
            FrequencyCounter(session).read_count()


if __name__ == "__main__":
    unittest.main()
