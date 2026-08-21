"""Crash-safe JSON writes.

Every store in this backend used to be written with a bare `write_text()`:

    path.write_text(json.dumps(entries), encoding="utf-8")

That opens the target in "w" mode, which truncates it to zero bytes
immediately, then refills it. Between those two moments the file on disk is
incomplete, and anything that interrupts the process there - a crash, a power
cut on the deployment box, an unserializable value halfway down the structure -
leaves a truncated file that `json.loads` cannot parse on the next start.

What that costs is not evenly distributed. The stores at risk are
`api-keys.json` (every integration's credential), `projects.json` (the registry
without which no project resolves), and `vector-store.json` - which HANDOFF
singles out as the one thing that must be copied by hand between machines,
because its contents were produced by paid embedding calls over the whole
corpus and cannot be cheaply regenerated.

The fix is the standard rename dance:

  1. Serialize to a string FIRST, so a `TypeError` on an unserializable value
     is raised before anything on disk has been touched.
  2. Write that string to a temp file in the SAME directory. Same directory
     matters: `os.replace` is only atomic within a single filesystem, and this
     project's data lives on an external volume.
  3. fsync, so the bytes are on the platter and not only in the page cache -
     otherwise a power cut can still lose them after a "successful" write.
  4. `os.replace` onto the target. Atomic on POSIX, and atomic on Windows too
     (unlike `os.rename`, which fails there if the destination exists) - which
     is the case that actually matters, since the deployment host is Windows.

A reader therefore sees either the entire previous file or the entire new one,
never a partial write.
"""

import json
import os
import re
import tempfile
import time
from pathlib import Path


def write_json(path, obj, _replace=os.replace, **dumps_kwargs):
    """Atomically write `obj` as JSON to `path`.

    `dumps_kwargs` is passed straight through to `json.dumps`, so callers keep
    the formatting they already relied on - `indent=2` to stay hand-readable,
    `ensure_ascii=False` to keep Devanagari legible in the FAQ caches rather
    than escaped to \\uXXXX.

    `_replace` is an injection point for tests to observe the rename; callers
    should never pass it.
    """
    path = Path(path)

    # Before anything touches the disk: if this raises, the existing file is
    # still whole. This is the ordering the old code got wrong.
    text = json.dumps(obj, **dumps_kwargs)

    path.parent.mkdir(parents=True, exist_ok=True)

    # delete=False because we hand the path to os.replace rather than letting
    # the context manager remove it. Same directory as the target - see the
    # module docstring on why that is not optional.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _replace(tmp_name, str(path))
    except BaseException:
        # Leaving a stray .tmp behind would accumulate silently in the data
        # directory on every failure. BaseException, not Exception: a
        # KeyboardInterrupt mid-write should clean up too.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# The shape mkstemp produces above: "<target name>.<random>.tmp". Matching the
# shape rather than a bare "*.tmp" so the sweep can never claim a scratch file
# that belongs to someone else in the same directory.
_TEMP_NAME_RE = re.compile(r"^.+\.[A-Za-z0-9_]+\.tmp$")

# A temp file younger than this may still belong to a write in flight. Deleting
# one mid-write would turn a harmless leak into the data loss this module
# exists to prevent, so the sweep only ever touches files old enough that no
# live write could still own them.
_TEMP_MIN_AGE_SECONDS = 3600


def sweep_stale_temp_files(root, min_age_seconds=_TEMP_MIN_AGE_SECONDS):
    """Delete leftover temp files under `root`. Returns how many were removed.

    write_json cleans up after itself on any exception, but SIGKILL and a power
    cut are uncatchable - so a hard crash leaves its temp file behind. They are
    inert (every reader opens a known path; nothing globs) but they accumulate
    beside multi-megabyte vector stores on a box nobody is watching.

    Safe by construction and by omission: it matches only the name shape this
    module creates, skips anything recent enough to belong to a live write, and
    swallows per-file errors. This runs at startup, and no cleanup helper
    should ever be the reason the server fails to boot.
    """
    root = Path(root)
    if not root.is_dir():
        return 0
    cutoff = time.time() - min_age_seconds
    removed = 0
    for path in root.rglob("*.tmp"):
        if not _TEMP_NAME_RE.match(path.name):
            continue
        try:
            if path.stat().st_mtime > cutoff:
                continue
            os.unlink(str(path))
            removed += 1
        except OSError:
            # Vanished under us, or not ours to delete. Either way, not fatal.
            continue
    return removed
