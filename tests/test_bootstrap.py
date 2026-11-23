import subprocess
import unittest
from unittest.mock import patch

from manual_test_companion import __main__ as bootstrap


class DependencyBootstrapTests(unittest.TestCase):
    def test_does_not_run_pip_when_dependencies_are_available(self) -> None:
        with (
            patch.object(bootstrap.sys, "platform", "win32"),
            patch.object(bootstrap.importlib.util, "find_spec", return_value=object()),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            bootstrap.ensure_dependencies()

        run.assert_not_called()

    def test_installs_requirements_when_a_dependency_is_missing(self) -> None:
        def find_spec(module: str) -> object | None:
            return None if module == "pyvisa" else object()

        with (
            patch.object(bootstrap.sys, "platform", "win32"),
            patch.object(bootstrap.importlib.util, "find_spec", side_effect=find_spec),
            patch.object(bootstrap.subprocess, "run") as run,
        ):
            bootstrap.ensure_dependencies()

        command = run.call_args.args[0]
        self.assertEqual(command[:4], [bootstrap.sys.executable, "-m", "pip", "install"])
        self.assertEqual(command[4], "-r")
        self.assertTrue(command[5].endswith("requirements.txt"))
        self.assertTrue(run.call_args.kwargs["check"])

    def test_reports_dependency_installation_failure(self) -> None:
        def find_spec(module: str) -> object | None:
            return None if module == "pyvisa" else object()

        failure = subprocess.CalledProcessError(1, ["python", "-m", "pip"])
        with (
            patch.object(bootstrap.sys, "platform", "win32"),
            patch.object(bootstrap.importlib.util, "find_spec", side_effect=find_spec),
            patch.object(bootstrap.subprocess, "run", side_effect=failure),
            self.assertRaisesRegex(SystemExit, "Dependency installation failed"),
        ):
            bootstrap.ensure_dependencies()

    def test_refuses_to_install_windows_dependencies_on_other_platforms(self) -> None:
        with (
            patch.object(bootstrap.sys, "platform", "linux"),
            patch.object(bootstrap.subprocess, "run") as run,
            self.assertRaisesRegex(SystemExit, "requires Windows"),
        ):
            bootstrap.ensure_dependencies()

        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
