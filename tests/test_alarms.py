import datetime
import importlib.util
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo


SPEC = importlib.util.spec_from_file_location(
    "clockenstein_alarms", Path(__file__).parents[1] / "daemon" / "alarms.py"
)
ALARMS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ALARMS)


class AlarmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ALARMS.AlarmStore(self.temp.name)
        self.timezone = ZoneInfo("Europe/Dublin")

    def tearDown(self):
        self.temp.cleanup()

    def test_one_off_alarm_disables_after_firing(self):
        alarm = self.store.create({"time": "07:30", "label": "Coffee"})
        fired = self.store.mark_fired(alarm)
        self.assertFalse(fired["enabled"])

    def test_repeating_alarm_stays_enabled_after_firing(self):
        alarm = self.store.create({"time": "07:30", "repeat": [0, 1, 2, 3, 4]})
        fired = self.store.mark_fired(alarm)
        self.assertTrue(fired["enabled"])

    def test_sound_interval_defaults_and_persists(self):
        default = self.store.create({"time": "07:30"})
        custom = self.store.create({"time": "08:30", "sound_interval": 12})
        self.assertEqual(default["sound_interval"], 3)
        self.assertEqual(custom["sound_interval"], 12)

    def test_date_specific_alarm_is_due_at_its_time(self):
        alarm = self.store.create({"time": "07:30", "date": "2025-01-01"})
        since = datetime.datetime(2025, 1, 1, 7, 29, tzinfo=self.timezone)
        until = datetime.datetime(2025, 1, 1, 7, 31, tzinfo=self.timezone)
        due = ALARMS.due_alarms(self.store.list(), since, until, self.timezone)
        self.assertEqual([item[0]["id"] for item in due], [alarm["id"]])
