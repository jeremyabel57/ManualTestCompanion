from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from manual_test_companion.scope_file_manager import (
    ScopeDirectory,
    ScopeDirectoryEntry,
    ScopeFileManager,
    parse_scope_directory,
    scope_join_path,
    scope_parent_path,
)


class FakeInstrumentSession:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.binary_commands: list[tuple[str, bytes]] = []
        self.binary_reply = b"\x00scope image\r\n"
        self.event_status = "0"

    def query(self, command: str) -> str:
        self.commands.append(("query", command))
        if command == "*IDN?":
            return "TEKTRONIX,MSO58B,SERIAL,1.0\n"
        if command == "FILESystem:CWD?":
            return '"C:/Users"'
        if command == "FILESystem:DIR?":
            return '"waveforms/","trace.wfm","notes,with,commas.txt"'
        if command == "*ESR?":
            return self.event_status
        raise AssertionError(f"unexpected query: {command}")

    def write(self, command: str) -> None:
        self.commands.append(("write", command))

    def query_binary(self, command: str) -> bytes:
        self.commands.append(("query_binary", command))
        return self.binary_reply

    def write_binary_block(self, command: str, payload: bytes) -> None:
        self.binary_commands.append((command, payload))

    def close(self) -> None:
        self.commands.append(("close", ""))


class ScopeFileManagerTests(unittest.TestCase):
    def test_connect_restores_last_directory_and_parses_files(self) -> None:
        session = FakeInstrumentSession()
        manager = ScopeFileManager(session)

        identification, directory = manager.connect("C:/Users")

        self.assertEqual(identification, "TEKTRONIX,MSO58B,SERIAL,1.0")
        self.assertEqual(
            directory,
            ScopeDirectory(
                "C:/Users",
                (
                    ScopeDirectoryEntry("waveforms/", True),
                    ScopeDirectoryEntry("trace.wfm", False),
                    ScopeDirectoryEntry("notes,with,commas.txt", False),
                ),
            ),
        )
        self.assertEqual(
            session.commands[:2],
            [
                ("query", "*IDN?"),
                ("write", 'FILESystem:CWD "C:/Users"'),
            ],
        )

    def test_download_writes_binary_data_atomically(self) -> None:
        session = FakeInstrumentSession()
        manager = ScopeFileManager(session)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "trace.wfm"

            result = manager.download_file("trace.wfm", destination)

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), session.binary_reply)
        self.assertEqual(
            session.commands[0],
            ("query_binary", 'FILESystem:READFile "trace.wfm"'),
        )

    def test_captures_png_screenshot_and_cleans_up_remote_files(self) -> None:
        session = FakeInstrumentSession()
        session.binary_reply = b"\x89PNG\r\n\x1a\nscope image"
        manager = ScopeFileManager(session)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "scope.png"

            with patch("manual_test_companion.scope_file_manager.time.sleep"):
                result = manager.capture_screenshot(destination)

            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), session.binary_reply)

        self.assertIn(
            ("write", 'SAVE:IMAGe "C:/Temp_Scope.png"'),
            session.commands,
        )
        self.assertIn(
            ("write", 'FILESystem:REName "C:/Temp_Scope.png","C:/Temp2_Scope.png"'),
            session.commands,
        )
        self.assertIn(
            ("query_binary", 'FILESystem:READFile "C:/Temp2_Scope.png"'),
            session.commands,
        )
        self.assertEqual(
            session.commands[-2:],
            [
                ("write", 'FILESystem:DELEte "C:/Temp2_Scope.png"'),
                ("write", 'FILESystem:DELEte "C:/Temp_Scope.png"'),
            ],
        )

    def test_screenshot_timeout_cleans_up_temporary_files(self) -> None:
        session = FakeInstrumentSession()
        session.event_status = "16"
        manager = ScopeFileManager(session)

        with (
            patch(
                "manual_test_companion.scope_file_manager.time.monotonic",
                side_effect=(0.0, 1.0),
            ),
            patch("manual_test_companion.scope_file_manager.time.sleep"),
            self.assertRaisesRegex(TimeoutError, "did not finish"),
        ):
            manager.capture_screenshot(Path("scope.png"), timeout=0.1)

        self.assertEqual(
            session.commands[-2:],
            [
                ("write", 'FILESystem:DELEte "C:/Temp2_Scope.png"'),
                ("write", 'FILESystem:DELEte "C:/Temp_Scope.png"'),
            ],
        )

    def test_upload_uses_ieee_block_and_refreshes_directory(self) -> None:
        session = FakeInstrumentSession()
        manager = ScopeFileManager(session)
        with TemporaryDirectory() as directory:
            source = Path(directory) / "upload.wfm"
            source.write_bytes(b"waveform payload")

            result = manager.upload_file(source, "upload.wfm")

        self.assertEqual(
            session.binary_commands,
            [('FILESystem:WRITEFile "upload.wfm",', b"waveform payload")],
        )
        self.assertEqual(result.path, "C:/Users")

    def test_rejects_remote_names_that_can_escape_the_current_directory(self) -> None:
        manager = ScopeFileManager(FakeInstrumentSession())

        for name in ("", "../outside.wfm", "folder/file.wfm", 'bad"name.wfm'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manager.download_file(name, Path("trace.wfm"))

    def test_parents_and_joins_scope_paths_with_windows_and_posix_separators(self) -> None:
        self.assertEqual(scope_parent_path("C:/Users/Scope"), "C:/Users")
        self.assertEqual(scope_parent_path("C:\\Users\\Scope"), "C:\\Users")
        self.assertEqual(scope_parent_path("C:/"), "C:/")
        self.assertEqual(scope_join_path("C:/Users", "Scope"), "C:/Users/Scope")
        self.assertEqual(scope_join_path("C:\\Users", "Scope"), "C:\\Users\\Scope")
        self.assertEqual(scope_join_path("C:/Users", "D:/Other"), "D:/Other")

    def test_parses_empty_and_malformed_directory_responses(self) -> None:
        self.assertEqual(parse_scope_directory(""), ())
        with self.assertRaisesRegex(ValueError, "directory listing"):
            parse_scope_directory('"unterminated')


if __name__ == "__main__":
    unittest.main()
