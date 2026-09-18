import datetime
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

DEFAULT_SOUND = os.path.join("@datadir@", "clockenstein", "sounds", "notification.oga")

def _get_data_dir():
    override = os.environ.get("CLOCKENSTEIN_DATA_DIR")
    return Path(override) if override else Path.home() / ".local" / "share" / "clockenstein"


class AlarmStore:
    """Alarm storage shared by Clocks and the daemon."""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else _get_data_dir()
        self.path = self.data_dir / "alarms.db"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self._connection(write=True) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS alarms (
                    id TEXT PRIMARY KEY NOT NULL,
                    time TEXT NOT NULL,
                    date TEXT,
                    repeat_days TEXT NOT NULL,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    last_fired INTEGER,
                    sound_enabled INTEGER NOT NULL CHECK (sound_enabled IN (0, 1)),
                    sound TEXT NOT NULL,
                    sound_interval INTEGER NOT NULL CHECK (sound_interval >= 1)
                )
            """)

    @contextmanager
    def _connection(self, write=False):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                if write:
                    # Lock before reading so another writer can't change an alarm
                    # between our lookup and update. SQLite waits for busy writers.
                    connection.execute("BEGIN IMMEDIATE")
                yield connection
        finally:
            connection.close()

    def list(self):
        with self._connection() as connection:
            return [self._from_row(row) for row in connection.execute(
                "SELECT * FROM alarms ORDER BY rowid"
            )]

    def create(self, values):
        alarm = self._normalise(values)
        alarm["id"] = str(uuid.uuid4())
        with self._connection(write=True) as connection:
            connection.execute("""
                INSERT INTO alarms (id, time, date, repeat_days, label, enabled,
                                    last_fired, sound_enabled, sound, sound_interval)
                VALUES (:id, :time, :date, :repeat_days, :label, :enabled,
                        :last_fired, :sound_enabled, :sound, :sound_interval)
            """, self._to_row(alarm))
        return alarm

    def update(self, alarm_id, values):
        with self._connection(write=True) as connection:
            row = connection.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,)).fetchone()
            if row is None:
                raise KeyError(alarm_id)
            alarm = self._normalise({**self._from_row(row), **values})
            alarm["id"] = alarm_id
            connection.execute("""
                UPDATE alarms SET time = :time, date = :date, repeat_days = :repeat_days,
                    label = :label, enabled = :enabled, last_fired = :last_fired,
                    sound_enabled = :sound_enabled, sound = :sound,
                    sound_interval = :sound_interval
                WHERE id = :id
            """, self._to_row(alarm))
        return alarm

    def get(self, alarm_id):
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,)).fetchone()
            return self._from_row(row) if row is not None else None

    def delete(self, alarm_id):
        with self._connection(write=True) as connection:
            result = connection.execute("DELETE FROM alarms WHERE id = ?", (alarm_id,))
            if result.rowcount == 0:
                raise KeyError(alarm_id)

    def set_enabled(self, alarm_id, enabled):
        return self.update(alarm_id, {"enabled": bool(enabled)})

    def mark_fired(self, alarm):
        with self._connection(write=True) as connection:
            # Only update firing history, never write the daemon's old alarm copy
            # over a user's edits or recreate an alarm they have deleted.
            connection.execute("UPDATE alarms SET last_fired = ? WHERE id = ?",
                               (int(datetime.datetime.now().timestamp()), alarm["id"]))
            row = connection.execute("SELECT * FROM alarms WHERE id = ?", (alarm["id"],)).fetchone()
            return self._from_row(row) if row is not None else None

    @staticmethod
    def _to_row(alarm):
        return {**alarm, "repeat_days": json.dumps(alarm["repeat"])}

    @staticmethod
    def _from_row(row):
        alarm = dict(row)
        alarm["repeat"] = json.loads(alarm.pop("repeat_days"))
        alarm["enabled"] = bool(alarm["enabled"])
        alarm["sound_enabled"] = bool(alarm["sound_enabled"])
        return alarm

    @staticmethod
    def _normalise(values):
        try:
            time = datetime.time.fromisoformat(values.get("time", ""))
        except ValueError as exc:
            raise ValueError("Invalid alarm time") from exc
        date = values.get("date") or None
        if date:
            try:
                datetime.date.fromisoformat(date)
            except ValueError as exc:
                raise ValueError("Invalid alarm date") from exc
        repeat = sorted({int(day) for day in values.get("repeat", []) if 0 <= int(day) <= 6})
        sound_interval = max(1, int(values.get("sound_interval", 3)))
        if date:
            repeat = []
        return {
            "id": values.get("id"),
            "time": time.strftime("%H:%M"),
            "date": date,
            "repeat": repeat,
            "label": str(values.get("label", "")).strip(),
            "enabled": bool(values.get("enabled", True)),
            "last_fired": values.get("last_fired"),
            "sound_enabled": bool(values.get("sound_enabled", True)),
            "sound": str(values.get("sound", DEFAULT_SOUND)),
            "sound_interval": sound_interval,
        }


def due_alarms(alarms, since, until, timezone):
    """Return alarms whose scheduled trigger occurs in the supplied interval."""
    if until < since:
        return []
    due = []
    for alarm in alarms:
        if not alarm.get("enabled", True):
            continue
        time = datetime.time.fromisoformat(alarm["time"])
        dates = []
        if alarm.get("date"):
            dates = [datetime.date.fromisoformat(alarm["date"])]
        elif alarm.get("repeat"):
            day = since.date()
            while day <= until.date():
                if day.weekday() in alarm["repeat"]:
                    dates.append(day)
                day += datetime.timedelta(days=1)
        else:
            dates = [since.date(), until.date()]
        for date in sorted(set(dates)):
            trigger = datetime.datetime.combine(date, time, timezone)
            if (alarm.get("last_fired") is not None
                    and trigger.timestamp() <= alarm["last_fired"]):
                continue
            if since < trigger <= until:
                due.append((alarm, trigger))
                break
    return sorted(due, key=lambda item: item[1])
