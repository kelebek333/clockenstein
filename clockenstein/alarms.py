import datetime
import json
import os
import uuid
from pathlib import Path

DEFAULT_SOUND = os.path.join("@datadir@", "clockenstein", "sounds", "notification.oga")

def _data_dir():
    override = os.environ.get("CLOCKENSTEIN_DATA_DIR")
    return Path(override) if override else Path.home() / ".local" / "share" / "clockenstein"


class AlarmStore:
    """Small, daemon-owned store for alarms rather than calendar events."""

    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else _data_dir()
        self.path = self.data_dir / "alarms.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def list(self):
        try:
            alarms = json.loads(self.path.read_text(encoding="utf-8"))
            return alarms if isinstance(alarms, list) else []
        except (OSError, ValueError):
            return []

    def create(self, values):
        alarm = self._normalise(values)
        alarm["id"] = str(uuid.uuid4())
        self._replace(alarm)
        return alarm

    def update(self, alarm_id, values):
        existing = self.get(alarm_id)
        if existing is None:
            raise KeyError(alarm_id)
        alarm = self._normalise({**existing, **values})
        alarm["id"] = alarm_id
        self._replace(alarm)
        return alarm

    def get(self, alarm_id):
        return next((alarm for alarm in self.list() if alarm.get("id") == alarm_id), None)

    def delete(self, alarm_id):
        alarms = self.list()
        updated = [alarm for alarm in alarms if alarm.get("id") != alarm_id]
        if len(updated) == len(alarms):
            raise KeyError(alarm_id)
        self._save(updated)

    def set_enabled(self, alarm_id, enabled):
        return self.update(alarm_id, {"enabled": bool(enabled)})

    def mark_fired(self, alarm):
        return self.update(alarm["id"], {
            "last_fired": int(datetime.datetime.now().timestamp()),
        })

    def _replace(self, replacement):
        alarms = self.list()
        for index, alarm in enumerate(alarms):
            if alarm.get("id") == replacement["id"]:
                alarms[index] = replacement
                break
        else:
            alarms.append(replacement)
        self._save(alarms)

    def _save(self, alarms):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(alarms, indent=2), encoding="utf-8")
        temporary.replace(self.path)

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
            if since < trigger <= until:
                due.append((alarm, trigger))
                break
    return sorted(due, key=lambda item: item[1])
