from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from manual_test_companion.settings import (
    TestVariable,
    load_test_variables,
    save_test_variables,
)


class TestVariableSettingsTests(unittest.TestCase):
    def test_reads_legacy_variable_rows(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ManualTestCompanion.ini"
            path.write_text(
                "[Variables]\nv_r=2\nv_c=2\n"
                "v_0.0=pn\nv_0.1=ABC123\n"
                "v_1.0=$temp\nv_1.1=25C\n",
                encoding="utf-8",
            )

            variables = load_test_variables(path)

        self.assertEqual(
            variables,
            (TestVariable("pn", "ABC123"), TestVariable("$temp", "25C")),
        )

    def test_saves_variables_without_rewriting_other_sections(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ManualTestCompanion.ini"
            path.write_text("[mts]\nwx=100\n[Variables]\nv_r=1\nv_c=2\n", encoding="utf-8")

            save_test_variables(
                path,
                (TestVariable("pn", "ABC123"), TestVariable("$temp", "25C")),
            )

            text = path.read_text(encoding="utf-8")
            self.assertIn("[mts]\nwx=100\n", text)
            self.assertIn("v_r=2\n", text)
            self.assertIn("v_c=2\n", text)
            self.assertIn("v_0.0=pn\n", text)
            self.assertIn("v_1.1=25C\n", text)


if __name__ == "__main__":
    unittest.main()
