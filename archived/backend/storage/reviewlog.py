"""The system's OWN self-detected near-misses - a validation FAIL, an
orchestrator decomposition that gave up and fell back - logged even on a day
no student happened to click dislike. Distinct from faq.py's flagged_path,
which only ever holds a STUDENT's dislike.

Same "never log question/answer content" discipline as stats.py - a record
is a shape (kind, reason, discriminator groups involved), never the text
itself, so this file stays safe to read/aggregate freely without becoming a
second copy of conversation content.
"""

import json
import threading
import time

from . import atomic

_lock = threading.Lock()
_CAP = 500  # bounds file growth; old entries age out, same idea as stats.py's _RECENT_CAP


def append(review_log_path, record):
    """`record` should already be shaped by the caller - typically
    {kind, reason, ...small_shape_fields}. `ts` is added here, not by the
    caller, so every record is comparably timestamped.
    """
    with _lock:
        entries = load(review_log_path)
        entries.append({**record, "ts": time.time()})
        entries = entries[-_CAP:]
        atomic.write_json(review_log_path, entries, ensure_ascii=False, indent=2)


def load(review_log_path):
    if not review_log_path.exists():
        return []
    try:
        return json.loads(review_log_path.read_text(encoding="utf-8") or "[]")
    except ValueError:
        return []
