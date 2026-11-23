import unittest

from manual_test_companion.expressions import (
    ExpressionError,
    evaluate_expression,
    interpolate_text,
)


class ExpressionTests(unittest.TestCase):
    def test_evaluates_autoit_variables_operators_and_numeric_strings(self) -> None:
        self.assertEqual(evaluate_expression("2.5 * $period", {"period": "4"}), 10.0)
        self.assertTrue(evaluate_expression("$count = 4 And not False", {"count": 4}))
        self.assertEqual(evaluate_expression("BitOR(1, 4)", {}), 5)

    def test_interpolates_expressions_into_scpi_text(self) -> None:
        self.assertEqual(
            interpolate_text(":SEARCH:LOW {2.5 * $period}", {"period": "4"}),
            ":SEARCH:LOW 10.0",
        )

    def test_supports_autoit_string_concatenation(self) -> None:
        self.assertEqual(evaluate_expression('"T" & "buf"', {}), "Tbuf")

    def test_rejects_unknown_names_and_arbitrary_function_calls(self) -> None:
        with self.assertRaisesRegex(ExpressionError, "unknown variable"):
            evaluate_expression("$missing + 1", {})
        with self.assertRaisesRegex(ExpressionError, "only supported built-in functions"):
            evaluate_expression("__import__('os').system('whoami')", {})


if __name__ == "__main__":
    unittest.main()
