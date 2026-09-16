import datetime
import tempfile
import unittest
from zoneinfo import ZoneInfo

from clockenstein import alarms as ALARMS


class AlarmTests(unittest.TestCase):
    def test_multi_day_check_selects_earliest_trigger(self):
        alarm = {"time": "07:30", "repeat": list(range(7)), "enabled": True}
        since = datetime.datetime(2026, 9, 1, tzinfo=self.timezone)
        until = since + datetime.timedelta(days=5)
        due = ALARMS.due_alarms([alarm], since, until, self.timezone)
        self.assertEqual(due[0][1], since.replace(hour=7, minute=30))

    def test_recorded_occurrence_is_skipped_but_next_day_can_ring(self):
        since = datetime.datetime(2026, 9, 1, tzinfo=self.timezone)
        trigger = since.replace(hour=7, minute=30)
        alarm = self.store.create({"time": "07:30", "repeat": list(range(7)),
                                   "last_fired": int(trigger.timestamp())})
        due = ALARMS.due_alarms(self.store.list(), since, since + datetime.timedelta(days=2),
                               self.timezone)
        self.assertEqual(due, [(alarm, trigger + datetime.timedelta(days=1))])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ALARMS.AlarmStore(self.temp.name)
        self.timezone = ZoneInfo("Europe/Dublin")

    def tearDown(self):
        self.temp.cleanup()

    def test_one_off_alarm_stays_enabled_after_firing(self):
        alarm = self.store.create({"time": "07:30", "label": "Coffee"})
        fired = self.store.mark_fired(alarm)
        self.assertTrue(fired["enabled"])

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
