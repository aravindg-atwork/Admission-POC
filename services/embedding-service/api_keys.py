"""
Lightweight API-key store for the embedding service.

Lets multiple consuming apps each hold their own key and get switched on/off
independently, without touching code or restarting anything. Backed by a
single JSON file, which is enough at POC scale — swap for a real table later.
"""

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_STORE_PATH = Path(os.environ.get("API_KEYS_FILE", "api_keys.json"))
_lock = threading.Lock()


def _load() -> List[dict]:
    if not _STORE_PATH.exists():
        return []
    return json.loads(_STORE_PATH.read_text())


def _save(keys: List[dict]) -> None:
    _STORE_PATH.write_text(json.dumps(keys, indent=2))


def list_keys() -> List[dict]:
    return _load()


def create_key(label: str) -> dict:
    with _lock:
        keys = _load()
        entry = {
            "id": secrets.token_hex(6),
            "key": "eas_" + secrets.token_urlsafe(32),
            "label": label or "unlabeled",
            "active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        keys.append(entry)
        _save(keys)
        return entry


def set_active(key_id: str, active: bool) -> Optional[dict]:
    with _lock:
        keys = _load()
        for entry in keys:
            if entry["id"] == key_id:
                entry["active"] = active
                _save(keys)
                return entry
        return None


def delete_key(key_id: str) -> bool:
    with _lock:
        keys = _load()
        remaining = [k for k in keys if k["id"] != key_id]
        if len(remaining) == len(keys):
            return False
        _save(remaining)
        return True


def is_key_active(key_value: str) -> bool:
    return any(k["key"] == key_value and k["active"] for k in _load())
