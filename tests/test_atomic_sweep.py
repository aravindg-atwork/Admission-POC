"""Stray temp files left by a hard crash get swept at startup.

atomic.write_json cleans up its own temp file on any exception, but SIGKILL and
a power cut are uncatchable — so a hard crash leaves a `<target>.<rand>.tmp`
beside the real file. Demonstrated: killing a process between the fsync and the
rename leaves exactly one.

They are inert, since every reader opens a known path and never globs. But they
accumulate next to 39MB vector stores, and on the deployment box nobody is
watching the data directory.

The sweep is deliberately conservative: only files matching the shape this
module creates, and only ones old enough that no live write could still own
them. Deleting a temp file another thread is mid-write to would turn a harmless
leak into data loss.

No network, no keys.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path

from backend.storage import atomic


class SweepStaleTempFiles(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _stale(self, name, age_seconds):
        path = self.dir / name
        path.write_text("partial")
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        return path

    def test_removes_an_old_temp_file(self):
        stale = self._stale("api-keys.json.abc123.tmp", 7200)
        removed = atomic.sweep_stale_temp_files(self.dir)
        self.assertFalse(stale.exists())
        self.assertEqual(removed, 1)

    def test_keeps_a_recent_temp_file(self):
        """A concurrent write in flight owns its temp file. Deleting it would
        turn a harmless leak into data loss.
        """
        fresh = self._stale("api-keys.json.abc123.tmp", 5)
        atomic.sweep_stale_temp_files(self.dir)
        self.assertTrue(fresh.exists())

    def test_never_touches_real_data_files(self):
        keys = self.dir / "api-keys.json"
        keys.write_text("[]")
        old = time.time() - 999999
        os.utime(keys, (old, old))
        atomic.sweep_stale_temp_files(self.dir)
        self.assertTrue(keys.exists())

    def test_ignores_unrelated_tmp_files(self):
        """Only the shape this module creates: <name>.<random>.tmp. Someone
        else's scratch file in the data directory is not ours to delete.
        """
        theirs = self._stale("scratch.tmp", 7200)
        atomic.sweep_stale_temp_files(self.dir)
        self.assertTrue(theirs.exists())

    def test_recurses_into_project_directories(self):
        """The stores that matter most live in data/projects/<id>/."""
        nested = self.dir / "projects" / "bvsc"
        nested.mkdir(parents=True)
        stale = nested / "vector-store.json.xyz789.tmp"
        stale.write_text("partial")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        atomic.sweep_stale_temp_files(self.dir)
        self.assertFalse(stale.exists())

    def test_a_missing_directory_is_not_an_error(self):
        """Runs at startup, before anything guarantees the tree exists."""
        self.assertEqual(atomic.sweep_stale_temp_files(self.dir / "nope"), 0)

    def test_survives_a_file_vanishing_mid_sweep(self):
        """Another process may clean up the same file first. A startup helper
        must never be the reason the server fails to boot.
        """
        self._stale("api-keys.json.abc123.tmp", 7200)
        real_unlink = os.unlink

        def racy(path):
            real_unlink(path)
            raise FileNotFoundError(path)  # simulate the double-remove

        import unittest.mock as mock
        with mock.patch.object(os, "unlink", racy):
            self.assertEqual(atomic.sweep_stale_temp_files(self.dir), 0)


if __name__ == "__main__":
    unittest.main()
