import threading
import unittest

from manual_test_companion.script import ScriptCancelled, ScriptError, ScriptRunner


class FakeVisa:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.closed = False

    def write(self, command: str) -> None:
        self.writes.append(command)

    def query(self, command: str) -> str:
        self.queries.append(command)
        return "12.5"

    def close(self) -> None:
        self.closed = True


class FakeModbus:
    def __init__(self) -> None:
        self.reads: list[tuple[int, str]] = []
        self.writes: list[tuple[int, object, str]] = []

    def read_value(self, address: int, format_string: str) -> int | float | str:
        self.reads.append((address, format_string))
        return 42

    def write_value(self, address: int, value: int | float | str, format_string: str) -> None:
        self.writes.append((address, value, format_string))

    def close(self) -> None:
        pass


class ScriptRunnerTests(unittest.TestCase):
    def test_runs_nested_if_and_while_blocks(self) -> None:
        visa = FakeVisa()
        runner = ScriptRunner(visa)

        variables = runner.run(
            """
            set $i 0
            while $i < 3
                set $i $i + 1
                if $i = 2 then
                    write :TEST:VALUE 2
                else
                    write :TEST:VALUE 1
                end
            end
            """
        )

        self.assertEqual(variables["i"], 3)
        self.assertEqual(visa.writes, [":TEST:VALUE 1", ":TEST:VALUE 2", ":TEST:VALUE 1"])

    def test_runs_do_until_and_scpi_assignment_interpolation(self) -> None:
        visa = FakeVisa()
        logged: list[str] = []
        runner = ScriptRunner(visa, logger=logged.append)

        variables = runner.run(
            """
            $period=:MEASURE:PERIOD?
            do
                set $count 1
            until $count = 1
            write :SEARCH:LOW {2 * $period}
            log Period { $period }
            """
        )

        self.assertEqual(variables["period"], "12.5")
        self.assertEqual(variables["count"], 1)
        self.assertEqual(visa.queries, [":MEASURE:PERIOD?"])
        self.assertEqual(visa.writes, [":SEARCH:LOW 25.0"])
        self.assertEqual(logged, ["Period 12.5"])

    def test_routes_modbus_reads_and_writes(self) -> None:
        modbus = FakeModbus()
        runner = ScriptRunner(modbus=modbus)

        variables = runner.run(
            """
            $temperature=modbusread 1i 100
            modbuswrite 1i 101 $temperature + 1
            """
        )

        self.assertEqual(variables["temperature"], 42)
        self.assertEqual(modbus.reads, [(100, "1i")])
        self.assertEqual(modbus.writes, [(101, 43, "1i")])

    def test_eval_and_exec_run_python_with_script_variables_and_sessions(self) -> None:
        visa = FakeVisa()
        runner = ScriptRunner(visa)

        variables = runner.run(
            """
            set $base 4
            eval base + 3
            read $evaluated
            exec
                import math
                factorial = math.factorial(base)
                identity = visa.query("*IDN?")
            endexec
            """
        )

        self.assertEqual(variables["evaluated"], 7)
        self.assertEqual(variables["factorial"], 24)
        self.assertEqual(variables["identity"], "12.5")
        self.assertEqual(visa.queries, ["*IDN?"])

    def test_exec_python_errors_are_reported_with_script_line(self) -> None:
        with self.assertRaisesRegex(ScriptError, "line 1:.*ZeroDivisionError"):
            ScriptRunner().run("exec 1 / 0")

    def test_rejects_malformed_blocks_and_limits_infinite_loops(self) -> None:
        with self.assertRaisesRegex(ScriptError, "missing end"):
            ScriptRunner().run("if True\n  set $i 1")
        with self.assertRaisesRegex(ScriptError, "exceeded 2 iterations"):
            ScriptRunner(max_loop_iterations=2).run("while True\n  set $i 1\nend")
        with self.assertRaisesRegex(ScriptError, "binary upload and download"):
            ScriptRunner().run("download::capture.bin::*CLS")
        with self.assertRaisesRegex(ScriptError, "exec block is missing endexec"):
            ScriptRunner().run("exec\n  value = 1")

    def test_cancellation_is_reported(self) -> None:
        cancelled = threading.Event()
        cancelled.set()

        with self.assertRaises(ScriptCancelled):
            ScriptRunner(cancel_event=cancelled).run("set $i 1")


if __name__ == "__main__":
    unittest.main()
