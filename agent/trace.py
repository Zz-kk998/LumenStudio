"""JSONL traces never include API keys or image base64."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import threading

class Tracer:
    def __init__(self, path, callback=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.callback = callback

    def emit(self, kind, message, **fields):
        entry = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "type": kind, "message": message,
        }
        for k, v in fields.items():
            # Protect credentials and giant data URLs from accidental trace export.
            if k.lower() in ("api_key", "authorization", "image_data_url"):
                continue
            entry[k] = v
        with self.lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        if self.callback:
            self.callback(entry)
        return entry
