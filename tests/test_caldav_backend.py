import datetime
import json
import tempfile
import unittest
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "calendar"))
from unittest.mock import patch
from icalendar import Event

from backends.caldav import CalDAVBackend, CalDAVUnavailable, _event_ical, _without_alarms
from store import _component_to_dict


UTC = ZoneInfo("UTC")


class FakeCalendar:
    def __init__(self, url, name):
        self.url = url
        self.name = name


class CalDAVBackendTests(unittest.TestCase):
    def test_hidden_calendar_is_empty_until_refreshed_after_showing(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = CalDAVBackend(Path(directory), UTC)
            start, end = datetime.date(2026, 9, 1), datetime.date(2026, 9, 30)
            raw = {"calendar_id": "hidden", "url": "https://example.test/event.ics",
                   "ical": _event_ical({"date_start": start, "date_end": start,
                                        "all_day": True}, UTC, "event")}
            backend.accounts = [{"id": "account", "username": "me",
                                 "url": "https://example.test/", "calendars": [
                                     {"id": "hidden", "visible": False}], "events": [raw]}]
            with patch.object(backend, "_lookup_password", return_value="password"), \
                    patch.object(backend, "_open", return_value=(object(), [FakeCalendar("hidden", "Hidden")])):
                self.assertEqual(backend.refresh(start, end), [])
            self.assertEqual(backend.accounts[0]["events"], [])
            # Hiding clears cached events immediately, without waiting for a sync.
            backend.accounts[0]["events"] = [raw]
            backend.set_visible("hidden", False, "account")
            backend.clear_calendar_events("hidden", "account")
            self.assertEqual(backend.accounts[0]["events"], [])
            backend.set_visible("hidden", True, "account")
            self.assertEqual(backend.accounts[0]["events"], [])
            self.assertEqual(backend.get_events(), [])

    def test_timed_events_are_displayed_in_the_computer_timezone(self):
        event = Event()
        event.add("dtstart", datetime.datetime(2026, 9, 9, 16, 45,
                                                 tzinfo=datetime.timezone.utc))
        event.add("dtend", datetime.datetime(2026, 9, 9, 17, 45,
                                               tzinfo=datetime.timezone.utc))
        parsed = _component_to_dict(event, ZoneInfo("Europe/Dublin"))
        self.assertEqual(parsed["time_start"], datetime.time(17, 45))
        self.assertEqual(parsed["time_end"], datetime.time(18, 45))

    def test_connection_metadata_excludes_password(self):
        """Connecting stores account metadata on disk but sends the password to Secret Service."""
        with tempfile.TemporaryDirectory() as directory:
            backend = CalDAVBackend(Path(directory), UTC)
            calendars = [FakeCalendar("https://dav.example.test/calendars/me/work/", "Work")]
            with patch.object(backend, "_open", return_value=(object(), calendars)), \
                    patch.object(backend, "_store_password") as store_password:
                account_id = backend.connect("https://dav.example.test/", "me", "secret")

            saved = (Path(directory) / "accounts.json").read_text(encoding="utf-8")
            self.assertNotIn("secret", saved)
            self.assertEqual(json.loads(saved)[0]["username"], "me")
            store_password.assert_called_once_with(account_id, "me", "secret")

    def test_cached_event_is_read_only_while_offline(self):
        """CalDAV cache entries remain visible but cannot be edited offline."""
        with tempfile.TemporaryDirectory() as directory:
            backend = CalDAVBackend(Path(directory), UTC)
            info = {"id": "account", "url": "https://dav.example.test/", "username": "me",
                    "calendars": [{"id": "https://dav.example.test/work/", "name": "Work",
                                   "visible": True, "writable": True}],
                    "events": [{"calendar_id": "https://dav.example.test/work/",
                                "url": "https://dav.example.test/work/one.ics",
                                "ical": _event_ical({"summary": "Meeting", "all_day": False,
                                                     "date_start": datetime.date(2026, 8, 22),
                                                     "date_end": datetime.date(2026, 8, 22),
                                                     "time_start": datetime.time(9),
                                                     "time_end": datetime.time(10)}, UTC, "one")}],
                    "name": "me — dav.example.test"}
            backend.accounts = [info]
            event = backend.get_events()[0]
            self.assertEqual(event["provider"], "caldav")
            self.assertTrue(event["cached"])
            self.assertFalse(event["editable"])

    def test_caldav_event_does_not_create_an_alarm(self):
        """Clockenstein's universal notification is not stored in CalDAV."""
        payload = _event_ical({"summary": "Alert", "all_day": False,
                               "date_start": datetime.date.today() + datetime.timedelta(days=2),
                               "date_end": datetime.date.today() + datetime.timedelta(days=2),
                               "time_start": datetime.time(9), "time_end": datetime.time(10)}, UTC)
        self.assertNotIn("BEGIN:VALARM", payload)

    def test_remote_caldav_alarms_are_removed_from_cached_data(self):
        """Remote alarms are ignored rather than retained in Clockenstein's cache."""
        payload = _event_ical({"summary": "Alert", "all_day": False,
                               "date_start": datetime.date.today(),
                               "date_end": datetime.date.today(),
                               "time_start": datetime.time(9), "time_end": datetime.time(10)}, UTC)
        payload = payload.replace(
            "END:VEVENT", "BEGIN:VALARM\r\nACTION:AUDIO\r\nTRIGGER:-PT10M\r\nEND:VALARM\r\nEND:VEVENT"
        )
        self.assertNotIn("BEGIN:VALARM", _without_alarms(payload))

if __name__ == "__main__":
    unittest.main()
