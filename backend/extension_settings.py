"""Extension auto-config: the extension registers on install, gets settings + API key.

Admin sets these values via the admin console ("Extension" tab), not the
extension popup. The extension calls /api/extension/register once on startup
and receives everything it needs.

This replaces the old approach of manually configuring 10+ fields in the
extension popup. The popup now only shows status and Google sign-in.
"""

import json
import threading
from copy import deepcopy

from . import config

_lock = threading.Lock()


def _load():
    if not config.EXTENSION_SETTINGS_PATH.exists():
        return deepcopy(config.DEFAULT_EXTENSION_SETTINGS)
    try:
        return {**config.DEFAULT_EXTENSION_SETTINGS,
                **json.loads(config.EXTENSION_SETTINGS_PATH.read_text(encoding="utf-8"))}
    except (ValueError, OSError):
        return deepcopy(config.DEFAULT_EXTENSION_SETTINGS)


def _save(settings):
    config.EXTENSION_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Only persist the keys that differ from defaults, to keep the file minimal.
    diff = {}
    for k, v in settings.items():
        default = config.DEFAULT_EXTENSION_SETTINGS.get(k)
        if isinstance(default, type(v)) and v != default:
            diff[k] = v
        elif k not in config.DEFAULT_EXTENSION_SETTINGS:
            diff[k] = v
    config.EXTENSION_SETTINGS_PATH.write_text(json.dumps(diff, indent=2), encoding="utf-8")


def get_settings():
    """Return the full extension settings dict (defaults merged with overrides)."""
    with _lock:
        return _load()


def update_settings(overrides):
    """Merge overrides into stored settings."""
    with _lock:
        current = _load()
        current.update(overrides)
        _save(current)
        return current


def get_registration():
    """Return the payload the extension needs on /api/extension/register.

    Includes a fresh API key for the extension, the backend URL, and all
    settings the admin configured.
    """
    from . import apikeys
    key_entry = apikeys.get_or_create_default(config.DEFAULT_PROJECT_ID)
    settings = get_settings()
    return {
        "backendUrl": f"http://localhost:{config.PORT}",
        "apiKey": key_entry["key"],
        **settings,
    }

