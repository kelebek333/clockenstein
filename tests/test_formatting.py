import datetime
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clockenstein.formatting import format_time


class TimeFormattingTests(unittest.TestCase):
    def test_locale_time_format_removes_seconds_and_its_separator(self):
        with patch("clockenstein.formatting.locale.nl_langinfo", return_value="%I:%M:%S %p"):
            self.assertEqual(format_time(datetime.time(13, 5, 42)), "01:05 PM")

    def test_locale_time_format_removes_alternative_seconds(self):
        with patch("clockenstein.formatting.locale.nl_langinfo", return_value="%H.%M.%OS"):
            self.assertEqual(format_time(datetime.time(13, 5, 42)), "13.05")

    def test_locale_time_format_expands_composite_directives(self):
        with patch("clockenstein.formatting.locale.nl_langinfo", return_value="%r"):
            self.assertEqual(format_time(datetime.time(13, 5, 42)), "01:05 PM")

    def test_forced_clock_formats_omit_seconds(self):
        value = datetime.time(13, 5, 42)
        self.assertEqual(format_time(value, "12-hour"), "1:05 PM")
        self.assertEqual(format_time(value, "24-hour"), "13:05")


if __name__ == "__main__":
    unittest.main()
