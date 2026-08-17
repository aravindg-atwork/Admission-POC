"""The storage layer actually writes through atomic.write_json.

test_atomic.py proves the helper is correct. This proves every store was
rewired to use it — which is the part that silently rots, because a store that
goes back to `write_text` still passes all of its own tests and only fails
during a crash nobody is watching for.

Rather than assert on the source, each test performs a real save through the
module's own public API with atomic.write_json patched out, and asserts the
call happened. That way renaming or reformatting the call site cannot produce
a false pass, and a genuine regression to a direct write fails here.

No network, no keys.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.storage import atomic, reviewlog, stats, vectorstore


class WritesGoThroughAtomic(unittest.TestCase):
    """Each store's write path must call the atomic helper."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_vectorstore_save_is_atomic(self):
        """The highest-stakes file in the project: 39MB of paid embeddings."""
        with mock.patch.object(atomic, "write_json", wraps=atomic.write_json) as spy:
            vectorstore.save(self.dir / "vector-store.json", [{"text": "x", "vector": [1.0]}])
        spy.assert_called_once()

    def test_stats_record_is_atomic(self):
        with mock.patch.object(atomic, "write_json", wraps=atomic.write_json) as spy:
            stats.record(self.dir / "stats.json", "rag", "mistral", "en", 1200)
        spy.assert_called()

    def test_reviewlog_append_is_atomic(self):
        with mock.patch.object(atomic, "write_json", wraps=atomic.write_json) as spy:
            reviewlog.append(self.dir / "review-log.json", {"kind": "test"})
        spy.assert_called()


class RoundTrips(unittest.TestCase):
    """Behaviour is unchanged: what each store writes, it can still read."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_vectorstore_round_trips(self):
        """load() enriches each entry with the runtime aids `_norm` and
        `_terms`, so the comparison is on the persisted fields only.
        """
        entries = [{"text": "chunk one", "page": 4, "vector": [0.1, 0.2]}]
        path = self.dir / "vector-store.json"
        vectorstore.save(path, entries)
        loaded = vectorstore.load(path)
        self.assertEqual(len(loaded), 1)
        for field in ("text", "page", "vector"):
            self.assertEqual(loaded[0][field], entries[0][field], field)

    def test_saving_loaded_entries_back_cannot_destroy_the_store(self):
        """`vectorstore.save` does NOT strip the runtime aids the way
        `faq._save` strips `_norm`, and `_terms` is a set, which json cannot
        serialize. No caller does save(load(path)) today — ingest always builds
        a fresh list — so this is latent rather than live.

        What is asserted here is that the latent path is *safe*: because
        atomic.write_json serializes before touching the disk, the existing
        store survives intact instead of being truncated by a write that was
        always going to fail.
        """
        path = self.dir / "vector-store.json"
        vectorstore.save(path, [{"text": "chunk one", "vector": [0.1, 0.2]}])
        enriched = vectorstore.load(path)
        self.assertIn("_terms", enriched[0])  # load added a set

        with self.assertRaises(TypeError):
            vectorstore.save(path, enriched)

        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))[0]["text"],
                         "chunk one")

    def test_vectorstore_save_invalidates_the_mtime_cache(self):
        """load() memoizes on mtime; a save that left the cache warm would
        serve the previous corpus until the process restarted.
        """
        path = self.dir / "vector-store.json"
        vectorstore.save(path, [{"text": "old", "vector": [1.0]}])
        self.assertEqual(vectorstore.load(path)[0]["text"], "old")
        vectorstore.save(path, [{"text": "new", "vector": [1.0]}])
        self.assertEqual(vectorstore.load(path)[0]["text"], "new")

    def test_reviewlog_round_trips(self):
        path = self.dir / "review-log.json"
        reviewlog.append(path, {"kind": "validation_regenerated"})
        loaded = reviewlog.load(path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["kind"], "validation_regenerated")

    def test_stats_round_trips(self):
        path = self.dir / "stats.json"
        stats.record(path, "rag", "mistral-small-latest", "en", 1200)
        self.assertTrue(path.exists())
        self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_devanagari_survives_the_round_trip_unescaped(self):
        """The FAQ caches pass ensure_ascii=False so the files stay readable.
        Losing that through the helper would not break parsing, so nothing else
        would catch it.
        """
        path = self.dir / "review-log.json"
        reviewlog.append(path, {"question": "फी किती आहे?"})
        self.assertIn("फी", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
