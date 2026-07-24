
"""API key store: generate / activate / deactivate / delete.

Every consumer (the admission site's own widget, the browser extension, any
integration) holds its own key, so any one can be revoked without touching the
others. Backed by a single JSON file - enough at POC scale.
"""

import json
import secrets
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()


def _load():
    if not config.KEYS_PATH.exists():
        return []
    return json.loads(config.KEYS_PATH.read_text(encoding="utf-8") or "[]")


def _save(keys):
    config.KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.KEYS_PATH.write_text(json.dumps(keys, indent=2), encoding="utf-8")


def _new_entry(label):
    return {
        "id": secrets.token_hex(6),
        "key": "aas_" + secrets.token_urlsafe(32),
        "label": label or "unlabeled",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def list_keys():
    with _lock:
        return _load()


def create(label):
    with _lock:
        keys = _load()
        entry = _new_entry(label)
        keys.append(entry)
        _save(keys)
        return entry


def set_active(key_id, active):
    with _lock:
        keys = _load()
        for entry in keys:
            if entry["id"] == key_id:
                entry["active"] = active
                _save(keys)
                return entry
        return None


def delete(key_id):
    with _lock:
        keys = _load()
        remaining = [k for k in keys if k["id"] != key_id]
        if len(remaining) == len(keys):
            return False
        _save(remaining)
        return True


def is_active(key_value):
    if not key_value:
        return False
    with _lock:
        return any(k["key"] == key_value and k["active"] for k in _load())


def get_or_create_default():
    with _lock:
        keys = _load()
        for entry in keys:
            if entry["label"] == config.DEFAULT_KEY_LABEL:
                return entry
        entry = _new_entry(config.DEFAULT_KEY_LABEL)
        keys.append(entry)
        _save(keys)
        return entry
