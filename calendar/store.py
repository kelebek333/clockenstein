import datetime
import re
import uuid
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gi.repository import Gio, GLib
from icalendar import Event
from xapp.util import l10n
from clockenstein import DEFAULT_COLOR
from clockenstein.calendars import CalendarDatabase

_ = l10n("clockenstein")


def local_timezone():
    identifier = GLib.TimeZone.new_local().get_identifier()
    try:
        return ZoneInfo(identifier)
    except (ZoneInfoNotFoundError, ValueError):
        with open("/etc/localtime", "rb") as zone_file:
            return ZoneInfo.from_file(zone_file)


def watch_timezone_changes(callback):
    """Refresh the cached zone when the system updates /etc/localtime."""
    try:
        monitor = Gio.File.new_for_path("/etc").monitor_directory(
            Gio.FileMonitorFlags.NONE, None
        )
    except (AttributeError, GLib.Error):
        return None

    def changed(_monitor, file, other_file, _event_type):
        if any(item and item.get_basename() == "localtime" for item in (file, other_file)):
            callback()

    monitor.connect("changed", changed)
    return monitor


class LocalStore:
    """Local calendars and events in the shared calendar database."""

    def __init__(self, timezone: datetime.tzinfo, data_dir: Optional[Path] = None):
        self.timezone = timezone
        self.database = CalendarDatabase(data_dir)
        self.data_dir = self.database.data_dir
        self.database.ensure_local_calendar(_("Personal"), DEFAULT_COLOR)

    def list_calendars(self):
        calendars = self.database.get_calendars("local")
        for calendar in calendars:
            calendar["available"] = True
        return calendars

    def create_calendar(self, name, color=DEFAULT_COLOR, calendar_id=None):
        base = calendar_id or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "calendar"
        calendar = self.database.create_local_calendar(base, name.strip() or _("Calendar"), color)
        calendar["available"] = True
        return calendar

    def set_visible(self, calendar_id, visible, _account_id=None):
        self.database.update_calendar("local", "local", calendar_id, visible=bool(visible))

    def set_reminders(self, calendar_id, enabled, _account_id=None):
        self.database.update_calendar("local", "local", calendar_id, reminders=bool(enabled))

    def update_calendar(self, calendar_id, name, color):
        self.database.update_calendar("local", "local", calendar_id,
                                      name=name.strip() or _("Calendar"), color=color)
        return next(c for c in self.list_calendars() if c["id"] == calendar_id)

    def delete_calendar(self, calendar_id):
        if not self.database.delete_local_calendar(calendar_id):
            raise ValueError(_("At least one local calendar is required"))

    def get_events(self, start=None, end=None, include_hidden=False):
        return sorted(self.database.get_events("local", self.timezone, start, end, include_hidden),
                      key=_event_sort_key)

    def create_event(self, data):
        calendar_id = data.get("calendar_id") or self.list_calendars()[0]["id"]
        event = self._event_data(data)
        event["uid"] = data.get("uid") or str(uuid.uuid4())
        self.database.save_event("local", "local", calendar_id, event, self.timezone)
        return self.database.get_events("local", self.timezone, include_hidden=True,
                                    calendar_id=calendar_id, uid=event["uid"])[0]

    def update_event(self, uid, data):
        source_id = data.get("original_calendar_id") or self._find_calendar(uid)
        calendar_id = data.get("calendar_id") or source_id
        if not self.database.get_events("local", self.timezone, include_hidden=True,
                                    calendar_id=source_id, uid=uid):
            return None
        event = self._event_data(data)
        event["uid"] = uid
        self.database.save_event("local", "local", calendar_id, event, self.timezone, source_id)
        return self.database.get_events("local", self.timezone, include_hidden=True,
                                    calendar_id=calendar_id, uid=uid)[0]

    def delete_event(self, uid, calendar_id=None, _account_id=None):
        calendar_id = calendar_id or self._find_calendar(uid)
        return self.database.delete_event("local", "local", calendar_id, uid)

    def _find_calendar(self, uid):
        events = self.database.get_events("local", self.timezone, include_hidden=True, uid=uid)
        if not events:
            raise KeyError(_("Unknown event %s") % uid)
        return events[0]["calendar_id"]

    @staticmethod
    def _event_data(data):
        start = data.get("date_start") or datetime.date.today()
        return {"summary": data.get("summary", ""), "location": data.get("location", ""),
                "description": data.get("description", ""), "all_day": data.get("all_day", True),
                "date_start": start, "date_end": data.get("date_end") or start,
                "time_start": data.get("time_start") or datetime.time(9),
                "time_end": data.get("time_end") or datetime.time(10)}


class CalendarManager:
    """Aggregate local calendars and optional online accounts for the UI."""

    def __init__(self, timezone: datetime.tzinfo, data_dir: Optional[Path] = None):
        self.timezone = timezone
        self.local = LocalStore(timezone, data_dir)
        from backends.google import GoogleBackend
        from backends.caldav import CalDAVBackend
        self.google = GoogleBackend(self.local.data_dir, timezone)
        self.caldav = CalDAVBackend(self.local.data_dir, timezone)

    def list_calendars(self):
        return (self.local.list_calendars() + self.google.list_calendars()
                + self.caldav.list_calendars())

    def get_events(self, start=None, end=None, include_hidden=False):
        return sorted(
            self.local.get_events(start, end, include_hidden)
            + self.google.get_events(start, end, include_hidden)
            + self.caldav.get_events(start, end, include_hidden),
            key=_event_sort_key,
        )

    def create_calendar(self, name, color=DEFAULT_COLOR):
        return self.local.create_calendar(name, color)

    def delete_local_calendar(self, calendar_id):
        return self.local.delete_calendar(calendar_id)

    def update_local_calendar(self, calendar_id, name, color):
        return self.local.update_calendar(calendar_id, name, color)

    def set_visible(self, provider, calendar_id, visible, account_id=None):
        self._backend(provider).set_visible(calendar_id, visible, account_id)

    def clear_calendar_events(self, provider, calendar_id, account_id):
        self._backend(provider).clear_calendar_events(calendar_id, account_id)

    def set_reminders(self, provider, calendar_id, enabled, account_id=None):
        self._backend(provider).set_reminders(calendar_id, enabled, account_id)

    def writable_calendars(self):
        return [c for c in self.list_calendars() if c.get("writable") and c.get("available")]

    def create_event(self, data):
        return self._backend(data.get("provider", "local")).create_event(data)

    def update_event(self, uid, data):
        return self._backend(data.get("provider", "local")).update_event(uid, data)

    def delete_event(self, uid, calendar_id=None, provider="local", account_id=None):
        return self._backend(provider).delete_event(uid, calendar_id, account_id)

    def _backend(self, provider):
        return {"local": self.local, "google": self.google, "caldav": self.caldav}[provider]

    @property
    def has_remote_accounts(self):
        return self.google.has_accounts or self.caldav.has_accounts

    def refresh_remote(self, start, end, google_limited_range=None,
                       google_restricted_range=None):
        return (self.google.refresh(start, end, google_limited_range,
                                    google_restricted_range)
                + self.caldav.refresh(start, end))


def _event_sort_key(e):
    return e["date_start"], e.get("time_start") or datetime.time.min


def _apply_data(ev: Event, data: dict, timezone: datetime.tzinfo):
    ev.add("summary", data.get("summary", ""))
    if data.get("location"):
        ev.add("location", data["location"])
    if data.get("description"):
        ev.add("description", data["description"])
    date_start = data.get("date_start") or datetime.date.today()
    date_end = data.get("date_end") or date_start
    if data.get("all_day", True):
        ev.add("dtstart", date_start)
        ev.add("dtend", date_end + datetime.timedelta(days=1))
    else:
        ev.add("dtstart", datetime.datetime.combine(
            date_start, data.get("time_start") or datetime.time(9), timezone))
        ev.add("dtend", datetime.datetime.combine(
            date_end, data.get("time_end") or datetime.time(10), timezone))


def _component_to_dict(component, timezone: datetime.tzinfo) -> dict:
    dtstart = component.get("dtstart").dt
    all_day = isinstance(dtstart, datetime.date) and not isinstance(dtstart, datetime.datetime)
    if component.get("dtend") is not None:
        dtend = component["dtend"].dt
    elif component.get("duration") is not None:
        dtend = dtstart + component["duration"].dt
    else:
        dtend = dtstart + datetime.timedelta(days=1) if all_day else dtstart
    source_start, source_end = dtstart, dtend
    if all_day:
        source_end = dtend - datetime.timedelta(days=1)
        date_start, date_end = dtstart, source_end
        time_start = time_end = None
    else:
        if dtstart.tzinfo is not None:
            dtstart = dtstart.astimezone(timezone)
        if dtend.tzinfo is not None:
            dtend = dtend.astimezone(timezone)
        date_start, date_end = dtstart.date(), dtend.date()
        time_start, time_end = dtstart.time().replace(tzinfo=None), dtend.time().replace(tzinfo=None)
    return {"uid": str(component.get("uid", "")), "summary": str(component.get("summary", "")),
            "location": str(component.get("location", "")), "description": str(component.get("description", "")),
            "all_day": all_day, "date_start": date_start, "date_end": date_end,
            "time_start": time_start, "time_end": time_end,
            "_start": source_start, "_end": source_end}
