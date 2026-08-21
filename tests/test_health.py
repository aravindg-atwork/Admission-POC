"""/healthz is a liveness probe, not a dependency check.

The admin console already has a health strip, but it sits behind the admin
token and it pings every upstream (embeddings, Ollama, the self-hosted server)
with a 2s timeout each. That is right for a dashboard a human reads and wrong
for something a service supervisor polls on a timer:

  - Authenticated means nothing outside the console can watch the process.
  - Upstream-dependent means the probe goes red when Mistral or BGE-M3 is
    down, even though this process is fine. A supervisor would then restart a
    healthy server, repeatedly, and the restart cannot fix an upstream outage.

So /healthz answers exactly one question - is THIS process alive and able to
serve - and it answers it without a single outbound call.

No network, no keys.
"""

import unittest
from unittest import mock

from backend import config
from backend.http import health_routes


class Payload(unittest.TestCase):

    def test_reports_ok_when_the_process_can_serve(self):
        status, body = health_routes.build_health()
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_makes_no_outbound_network_calls(self):
        """The whole point. If this probe can be made to hang or fail by an
        upstream, it is not a liveness probe.
        """
        def explode(*a, **kw):
            raise AssertionError("/healthz made a network call")

        with mock.patch("urllib.request.urlopen", explode):
            status, _ = health_routes.build_health()
        self.assertEqual(status, 200)

    def test_reports_unhealthy_when_the_project_registry_is_unreadable(self):
        """A real "this process cannot serve" condition: without the registry
        no project resolves, so every request 500s. That IS worth a restart.
        """
        with mock.patch.object(health_routes.projects, "list_projects",
                               side_effect=OSError("disk gone")):
            status, body = health_routes.build_health()
        self.assertEqual(status, 503)
        self.assertEqual(body["status"], "unhealthy")

    def test_includes_uptime(self):
        _, body = health_routes.build_health()
        self.assertIn("uptimeSeconds", body)
        self.assertGreaterEqual(body["uptimeSeconds"], 0)

    def test_includes_project_count(self):
        with mock.patch.object(health_routes.projects, "list_projects",
                               return_value=[{"id": "a"}, {"id": "b"}]):
            _, body = health_routes.build_health()
        self.assertEqual(body["projects"], 2)

    def test_never_leaks_the_admin_token(self):
        """It is unauthenticated by design, so anything in the payload is
        public. The boot banner already prints the token to stdout; this must
        not repeat that mistake over HTTP.
        """
        _, body = health_routes.build_health()
        rendered = repr(body)
        self.assertNotIn(config.ADMIN_TOKEN, rendered)
        for secret in ("apiKey", "api_key", "token", "key"):
            self.assertNotIn(secret.lower(),
                             " ".join(body.keys()).lower(), secret)


if __name__ == "__main__":
    unittest.main()
