import datetime
import hashlib
import json
import os
import tempfile
from pathlib import Path


class SyncDownload:
    """Latest library responses for a calendar, separate from the event store."""

    def __init__(self, data_dir, provider, account_id, calendar_id, start, end):
        account = hashlib.sha256(account_id.encode()).hexdigest()[:20]
        calendar = hashlib.sha256(calendar_id.encode()).hexdigest()[:20]
        self.path = Path(data_dir) / "sync" / provider / account / calendar
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.identity = {"provider": provider, "account_id": account_id, "calendar_id": calendar_id,
                         "start": start.isoformat(), "end": end.isoformat()}
        self.requests = []

    def add(self, start, end, response):
        self.requests.append({"start": start.isoformat(), "end": end.isoformat(),
                              "response": response})

    def save(self):
        self._write("latest.json", {**self.identity, "fetched_at": self._get_timestamp(),
                                    "requests": self.requests})

    def finish(self, error=None):
        self._write("status.json", {**self.identity, "attempted_at": self._get_timestamp(),
                                    "success": error is None, "error": str(error) if error else None})

    def _write(self, name, data):
        write_private_json(self.path / name, data)

    @staticmethod
    def _get_timestamp():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_private_json(path, data):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as stream:
            temp = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
