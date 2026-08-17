"""The query embedding must not inherit the ingest timeout.

Both call paths went through one `embed()` with a hard-coded `timeout=600`.
That figure is right for an ingest batch of full OCR'd table pages on a CPU
service, and absurd for the single short question a student just typed — it
means one slow or half-dead embedding call (HANDOFF: the service "occasionally
503s") pins a request thread for ten minutes.

Ten minutes is most of the eighteen-minute hang recorded against Q66, and no
client timeout fired because nothing bounded the request.

No network: urlopen is stubbed and the timeout it was handed is asserted on.
"""

import io
import json
import unittest
from unittest import mock

from backend import config
from backend.generation import embeddings


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _local_payload(n=1):
    return json.dumps({"embeddings": [[0.1, 0.2]] * n}).encode("utf-8")


def _selfhosted_payload(n=1):
    return json.dumps({"data": [[0.1, 0.2]] * n}).encode("utf-8")


class QueryTimeout(unittest.TestCase):

    def setUp(self):
        self.seen = {}

        def fake_urlopen(req, timeout=None):
            self.seen["timeout"] = timeout
            payload = (_selfhosted_payload()
                       if config.EMBEDDING_PROVIDER == "selfhosted"
                       else _local_payload())
            return _FakeResponse(payload)

        patcher = mock.patch("urllib.request.urlopen", fake_urlopen)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_embed_query_uses_the_short_timeout(self):
        embeddings.embed_query("what is the fee?")
        self.assertEqual(self.seen["timeout"], config.EMBEDDING_QUERY_TIMEOUT)

    def test_the_query_timeout_is_survivable_for_a_waiting_student(self):
        """The specific number matters more than the mechanism here: whatever
        it is set to, a student is holding a browser open behind it.
        """
        self.assertLessEqual(config.EMBEDDING_QUERY_TIMEOUT, 30)

    def test_embed_query_returns_a_single_vector_not_a_list_of_them(self):
        self.assertEqual(embeddings.embed_query("what is the fee?"), [0.1, 0.2])

    def test_batch_embed_keeps_the_generous_ingest_timeout(self):
        """Unchanged on purpose. A batch of whole OCR'd table pages genuinely
        is slow, and 120s was already measured as too short once tables started
        being embedded as single chunks.
        """
        embeddings.embed(["chunk one", "chunk two"])
        self.assertEqual(self.seen["timeout"], config.EMBEDDING_INGEST_TIMEOUT)

    def test_an_explicit_timeout_wins(self):
        embeddings.embed(["chunk"], timeout=42)
        self.assertEqual(self.seen["timeout"], 42)

    def test_ingest_timeout_stays_generous(self):
        self.assertGreaterEqual(config.EMBEDDING_INGEST_TIMEOUT, 300)

    def test_selfhosted_provider_honours_the_query_timeout_too(self):
        """Two provider functions, and only patching one of them would leave
        the live configuration (EMBEDDING_PROVIDER=selfhosted) unbounded.
        """
        with mock.patch.object(config, "EMBEDDING_PROVIDER", "selfhosted"):
            embeddings.embed_query("what is the fee?")
        self.assertEqual(self.seen["timeout"], config.EMBEDDING_QUERY_TIMEOUT)

    def test_selfhosted_batch_still_gets_the_ingest_timeout(self):
        with mock.patch.object(config, "EMBEDDING_PROVIDER", "selfhosted"):
            embeddings.embed(["a", "b"])
        self.assertEqual(self.seen["timeout"], config.EMBEDDING_INGEST_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
