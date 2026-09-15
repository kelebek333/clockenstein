import datetime
import importlib.util
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("clockenstein_daemon", ROOT / "daemon" / "daemon.py")
DAEMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DAEMON)
AGENT_SPEC = importlib.util.spec_from_file_location(
    "clockenstein_notification_agent", ROOT / "agent" / "agent.py"
)
AGENT = importlib.util.module_from_spec(AGENT_SPEC)
AGENT_SPEC.loader.exec_module(AGENT)


class NotificationSchedulerTests(unittest.TestCase):
    def test_reminder_uses_the_named_system_timezone(self):
        event = {"uid": "one", "date_start": datetime.date(2026, 9, 9),
                 "time_start": datetime.time(17, 45)}
        start = DAEMON._event_start(event, ZoneInfo("Europe/Dublin"))
        self.assertEqual(start.isoformat(), "2026-09-09T17:45:00+01:00")

    def test_global_lead_time_applies_to_every_event(self):
        tz = datetime.datetime.now().astimezone().tzinfo
        event_start = datetime.datetime.now(tz).replace(second=0, microsecond=0) \
            + datetime.timedelta(hours=2)
        event = {
            "uid": "one",
            "summary": "Meeting",
            "date_start": event_start.date(),
            "time_start": event_start.time().replace(tzinfo=None),
        }
        due = DAEMON._due_notifications(
            [event], event_start - datetime.timedelta(minutes=11),
            event_start - datetime.timedelta(minutes=9), 10, tz
        )
        self.assertEqual(due, [event])

    def test_interval_boundary_prevents_duplicate_notifications(self):
        tz = datetime.datetime.now().astimezone().tzinfo
        event_start = datetime.datetime.now(tz).replace(second=0, microsecond=0) \
            + datetime.timedelta(hours=1)
        trigger = event_start - datetime.timedelta(minutes=15)
        event = {
            "uid": "one",
            "date_start": event_start.date(),
            "time_start": event_start.time().replace(tzinfo=None),
        }
        self.assertEqual(DAEMON._due_notifications(
            [event], trigger, trigger + datetime.timedelta(seconds=30), 15, tz), [])

    def test_relative_start_time_updates_after_event_begins(self):
        now = datetime.datetime.now().astimezone().replace(microsecond=0)
        start = int((now - datetime.timedelta(minutes=3)).timestamp())
        self.assertEqual(
            AGENT._relative_start_label(start, now),
            "This event started 3 minutes ago",
        )



if __name__ == "__main__":
    unittest.main()
