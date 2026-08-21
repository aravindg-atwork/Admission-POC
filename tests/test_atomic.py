"""Tests for storage/atomic.py — crash-safe JSON writes.

Every JSON file in this backend was written with a bare `write_text()`, which
truncates the target the moment it opens and refills it in place. A crash, a
power cut, or a serialization error anywhere in between leaves a half-written
file, and the affected store is the API-key registry, the project registry, or
the vector store holding 39MB of paid embeddings.

The fix is the standard one: serialize first, write to a temp file in the same
directory, fsync, then os.replace onto the target. os.replace is atomic on both
POSIX and Windows, which matters because the deployment host is Windows.

No network, no keys.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from backend.storage import atomic


class WriteJson(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_writes_readable_json(self):
        target = self.dir / "store.json"
        atomic.write_json(target, [{"id": "a"}])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), [{"id": "a"}])

    def test_creates_missing_parent_directories(self):
        """Matches the mkdir(parents=True, exist_ok=True) every caller did
        for itself before.
        """
        target = self.dir / "projects" / "bvsc" / "store.json"
        atomic.write_json(target, {"ok": True})
        self.assertTrue(target.exists())

    def test_overwrites_an_existing_file(self):
        target = self.dir / "store.json"
        atomic.write_json(target, {"v": 1})
        atomic.write_json(target, {"v": 2})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"v": 2})

    def test_leaves_no_temp_file_behind(self):
        target = self.dir / "store.json"
        atomic.write_json(target, {"ok": True})
        self.assertEqual([p.name for p in self.dir.iterdir()], ["store.json"])

    def test_a_serialization_error_leaves_the_original_intact(self):
        """The whole point. `write_text` truncates on open, so an unserializable
        value destroyed the previous contents before failing. Serializing to a
        string first means a bad object never reaches the disk at all.
        """
        target = self.dir / "store.json"
        atomic.write_json(target, {"good": True})

        with self.assertRaises(TypeError):
            atomic.write_json(target, {"bad": object()})

        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"good": True})

    def test_a_serialization_error_leaves_no_temp_file(self):
        target = self.dir / "store.json"
        atomic.write_json(target, {"good": True})
        with self.assertRaises(TypeError):
            atomic.write_json(target, {"bad": object()})
        self.assertEqual([p.name for p in self.dir.iterdir()], ["store.json"])

    def test_temp_file_is_created_in_the_target_directory(self):
        """os.replace is only atomic within one filesystem. A temp file in the
        system temp dir could land on a different volume — and on this project
        the data directory is an external drive, so that is not hypothetical.
        """
        target = self.dir / "store.json"
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src).parent)
            return real_replace(src, dst)

        atomic.write_json(target, {"ok": True}, _replace=spy)
        self.assertEqual(seen, [self.dir])

    def test_passes_through_json_formatting_options(self):
        """Callers rely on specific formatting: indent=2 keeps the files
        hand-readable, and ensure_ascii=False keeps Devanagari legible rather
        than escaped.
        """
        target = self.dir / "store.json"
        atomic.write_json(target, {"q": "फी किती आहे?"}, ensure_ascii=False, indent=2)
        raw = target.read_text(encoding="utf-8")
        self.assertIn("फी", raw)
        self.assertIn("\n  ", raw)

    def test_defaults_to_compact_ascii_like_json_dumps(self):
        target = self.dir / "store.json"
        atomic.write_json(target, {"q": "फी"})
        self.assertIn("\\u", target.read_text(encoding="utf-8"))

    def test_accepts_a_string_path(self):
        target = self.dir / "store.json"
        atomic.write_json(str(target), {"ok": True})
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
