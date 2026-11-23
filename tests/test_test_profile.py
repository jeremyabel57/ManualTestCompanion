from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from manual_test_companion.config import LegacyConfig
from manual_test_companion.test_profile import (
    I2CProfile,
    load_i2c_profile,
    load_measurement_script,
    load_scope_setup,
    save_i2c_profile,
)


_PROFILE = """\
[I2C]
mn=2
m0=fSCL, clock frequency
m1=tLOW, clock low time
sn=2
s0=SCL, clock
s1=SDA, data
[mI2C]
m0.1=0
m0.4=1
busi=2
busn=3
b2name=PORT_A
b3ch=CH4
b4ch=CH5
[other]
keep=this
"""


class I2CProfileTests(unittest.TestCase):
    def test_loads_profile_definition_and_legacy_preferences(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "profile.ini"
            path.write_text(_PROFILE, encoding="utf-8")

            profile = load_i2c_profile(path)

        self.assertEqual(
            [(item.symbol, item.description) for item in profile.measurements],
            [("fSCL", "clock frequency"), ("tLOW", "clock low time")],
        )
        self.assertEqual(
            [(item.name, item.description) for item in profile.signals],
            [("SCL", "clock"), ("SDA", "data")],
        )
        self.assertFalse(profile.measurements[0].included)
        self.assertTrue(profile.measurements[0].verify_before_capture)
        self.assertEqual((profile.bus_count, profile.selected_bus), (3, 2))
        self.assertEqual(profile.bus_names[1], "PORT_A")
        self.assertEqual(profile.channel_assignments[1], ("CH4", "CH5"))

    def test_saves_legacy_preferences_without_changing_other_sections(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "profile.ini"
            path.write_text(_PROFILE, encoding="utf-8")
            profile = load_i2c_profile(path)
            changed = I2CProfile(
                measurements=(
                    profile.measurements[0],
                    profile.measurements[1],
                ),
                signals=profile.signals,
                bus_count=4,
                selected_bus=3,
                bus_names=profile.bus_names,
                channel_assignments=tuple(
                    (("CH6", "CH7") if index == 2 else assignments)
                    for index, assignments in enumerate(profile.channel_assignments)
                ),
            )

            save_i2c_profile(path, changed)

            preferences = LegacyConfig(path, "mI2C")
            self.assertEqual(preferences.get_str("busn"), "4")
            self.assertEqual(preferences.get_str("busi"), "3")
            self.assertEqual(preferences.get_str("b5ch"), "CH6")
            self.assertEqual(preferences.get_str("b6ch"), "CH7")
            self.assertEqual(LegacyConfig(path, "other").get_str("keep"), "this")

    def test_rejects_profiles_missing_required_measurement_entries(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "profile.ini"
            path.write_text("[I2C]\nmn=1\nsn=1\ns0=SCL\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "empty m0"):
                load_i2c_profile(path)

    def test_loads_plain_scope_setup_commands(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "i2c.set"
            path.write_text("*RST;:ACQUIRE:STATE 1\n:CH1:BANDWIDTH 100E6", encoding="utf-8")

            commands = load_scope_setup(path)

        self.assertEqual(commands, ("*RST", ":ACQUIRE:STATE 1", ":CH1:BANDWIDTH 100E6"))

    def test_loads_zip_scope_setup_commands(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "i2c.set"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("i2c_lrn.set", "*RST;:CH1:LABEL 'SCL'")

            commands = load_scope_setup(path)

        self.assertEqual(commands, ("*RST", ":CH1:LABEL 'SCL'"))

    def test_loads_measurement_setup_and_capture_sections(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mI2C_fSCL.txt"
            path.write_text(
                "#set\n:CH1:LABEL 'SCL'\n#comment\n#set\n#get\n:MEASure:SOURce CH1\n:MEASure:FREQuency?\n#get\n",
                encoding="utf-8",
            )

            setup = load_measurement_script(path, capture=False)
            capture = load_measurement_script(path, capture=True)

        self.assertEqual(setup, (":CH1:LABEL 'SCL'",))
        self.assertEqual(capture, (":MEASure:SOURce CH1", ":MEASure:FREQuency?"))

    def test_rejects_measurement_script_without_requested_section(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mI2C_tLOW.txt"
            path.write_text("#set\n:CH1:LABEL 'SCL'\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "has no #get section"):
                load_measurement_script(path, capture=True)

    def test_rejects_setup_files_without_commands(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "i2c.set"
            path.write_text(";;;", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contains no SCPI commands"):
                load_scope_setup(path)


if __name__ == "__main__":
    unittest.main()
