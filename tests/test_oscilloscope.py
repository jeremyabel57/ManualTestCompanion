import unittest

from manual_test_companion.oscilloscope import scope_url_from_address


class OscilloscopeAddressTests(unittest.TestCase):
    def test_builds_scope_url_from_legacy_address_with_instrument_suffix(self) -> None:
        self.assertEqual(
            scope_url_from_address("192.168.0.14   B028134"),
            "http://192.168.0.14/Tektronix/",
        )

    def test_discards_optional_port(self) -> None:
        self.assertEqual(
            scope_url_from_address("192.168.0.14:5025"),
            "http://192.168.0.14/Tektronix/",
        )

    def test_rejects_empty_or_url_injection_input(self) -> None:
        for value in ("", "  ", "192.168.0.14/path", "user@scope"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scope_url_from_address(value)


if __name__ == "__main__":
    unittest.main()
