from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from manual_test_companion.config import LegacyConfig


class LegacyConfigTests(unittest.TestCase):
    def test_reads_legacy_window_settings_and_uses_defaults_for_invalid_values(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ManualTestCompanion.ini"
            path.write_text(
                "[mts]\nwx=120\nwy=not-a-number\n[Chamber]\nSetPoint=25\n",
                encoding="utf-8",
            )

            config = LegacyConfig(path)

            self.assertEqual(config.get_int("wx", 60), 120)
            self.assertEqual(config.get_int("wy", 60), 60)

    def test_reads_and_updates_string_values_in_a_non_default_section(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ManualTestCompanion.ini"
            path.write_text("[mts]\nwx=10\n[Chamber]\nIpAddr=192.168.0.25\nSetPoint=25\n", encoding="utf-8")

            config = LegacyConfig(path, "Chamber")
            self.assertEqual(config.get_str("IpAddr"), "192.168.0.25")
            config.update({"IpAddr": "192.168.0.42", "SetPoint": 26.5})

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                "[mts]\nwx=10\n[Chamber]\nIpAddr=192.168.0.42\nSetPoint=26.5\n",
            )

    def test_updates_main_window_values_without_rewriting_other_settings(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ManualTestCompanion.ini"
            original = (
                "; keep this comment\r\n"
                "[mts]\r\n"
                "wx=10\r\n"
                "tab=2\r\n"
                "[Chamber]\r\n"
                "SetPoint=25\r\n"
            )
            path.write_bytes(original.encode("utf-8"))

            LegacyConfig(path).update({"wx": 200, "tab": 6, "ww": 900})

            self.assertEqual(
                path.read_bytes().decode("utf-8"),
                "; keep this comment\r\n"
                "[mts]\r\n"
                "wx=200\r\n"
                "tab=6\r\n"
                "ww=900\r\n"
                "[Chamber]\r\n"
                "SetPoint=25\r\n",
            )

    def test_creates_configuration_file_when_missing(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "ManualTestCompanion.ini"

            LegacyConfig(path).update({"wx": 80})

            self.assertEqual(path.read_text(encoding="utf-8"), "[mts]\nwx=80\n")

    def test_adds_missing_keys_when_existing_section_has_no_final_newline(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ManualTestCompanion.ini"
            path.write_text("[mts]", encoding="utf-8")

            LegacyConfig(path).update({"wx": 80})

            self.assertEqual(path.read_text(encoding="utf-8"), "[mts]\nwx=80\n")


if __name__ == "__main__":
    unittest.main()
