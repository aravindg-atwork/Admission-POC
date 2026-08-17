"""The fallback provider must be bounded like the primary is.

`llm.generate` capped its cloud PRIMARY at SARVAM_TIMEOUT (45s) per attempt,
then handed the FALLBACK the full uncapped `timeout` — 280s by default. That is
backwards: the fallback is the slower, less reliable path, and it was the one
allowed to run longest. One generate() was therefore worth 45 + 45 + 280 = 370s,
and the answer path makes three to five of them.

The cap is also misnamed. Sarvam has been dead on HTTP 402 for weeks, but
`SARVAM_TIMEOUT` still silently governs whichever cloud provider is primary —
Mistral today.

Providers are stubbed; no network, no keys.
"""

import unittest
from unittest import mock

from backend import config
from backend.generation import llm


class _StubProvider:
    """Records the timeout it was handed. Fails on demand."""

    def __init__(self, name, is_cloud, fail=False):
        self.name = name
        self.is_cloud = is_cloud
        self.fail = fail
        self.calls = []

    def configured(self):
        return True

    def chat(self, system_prompt, user_prompt, timeout, **kw):
        self.calls.append(timeout)
        if self.fail:
            raise RuntimeError(f"{self.name} is down")
        return ("an answer", self.name)


class _Harness(unittest.TestCase):
    def _run(self, primary, fallback, timeout=280):
        registry = {"primary": primary, "fallback": fallback}
        with mock.patch.object(llm.providers, "get", registry.get), \
             mock.patch.object(config, "CHAT_PRIMARY", "primary"), \
             mock.patch.object(config, "CHAT_FALLBACK", "fallback"), \
             mock.patch.object(llm, "_record_sarvam_call", lambda: None), \
             mock.patch.object(llm, "_sarvam_under_cap", lambda: True):
            return llm.generate("sys", "user", "question", timeout=timeout)


class CloudPrimary(_Harness):

    def test_cloud_primary_attempt_is_capped(self):
        primary = _StubProvider("mistral", is_cloud=True)
        self._run(primary, _StubProvider("local", is_cloud=False))
        self.assertEqual(primary.calls, [config.CLOUD_ATTEMPT_TIMEOUT])

    def test_cloud_primary_retries_once_still_capped(self):
        """Two attempts before giving up, each individually bounded — so the
        primary's worst case is 2 x the cap, not 2 x the request timeout.
        """
        primary = _StubProvider("mistral", is_cloud=True, fail=True)
        self._run(primary, _StubProvider("local", is_cloud=False))
        self.assertEqual(primary.calls,
                         [config.CLOUD_ATTEMPT_TIMEOUT, config.CLOUD_ATTEMPT_TIMEOUT])

    def test_a_local_primary_is_not_capped(self):
        """The cap exists because a stalled CLOUD call should fail over fast.
        A local provider has no such failover to protect.
        """
        primary = _StubProvider("selfhosted", is_cloud=False)
        self._run(primary, _StubProvider("other", is_cloud=False), timeout=280)
        self.assertEqual(primary.calls, [280])


class CloudFallback(_Harness):
    """The regression this file exists for."""

    def test_cloud_fallback_is_capped_too(self):
        """Previously handed the full 280s while the primary got 45s."""
        primary = _StubProvider("mistral", is_cloud=True, fail=True)
        fallback = _StubProvider("nvidia", is_cloud=True)
        self._run(primary, fallback, timeout=280)
        self.assertEqual(fallback.calls, [config.CLOUD_ATTEMPT_TIMEOUT])

    def test_worst_case_for_one_generate_is_bounded(self):
        """The arithmetic that produced the eighteen-minute hang. With both
        providers cloud, one generate() is now at most 3 x the cap rather than
        2 x cap + the full request timeout.
        """
        primary = _StubProvider("mistral", is_cloud=True, fail=True)
        fallback = _StubProvider("nvidia", is_cloud=True, fail=True)
        with self.assertRaises(RuntimeError):
            self._run(primary, fallback, timeout=280)
        worst = sum(primary.calls) + sum(fallback.calls)
        self.assertEqual(worst, 3 * config.CLOUD_ATTEMPT_TIMEOUT)
        self.assertLess(worst, 280)

    def test_a_caller_asking_for_less_than_the_cap_still_gets_less(self):
        """min(), not a flat override — a caller with a tighter budget than the
        cap must keep it. This is what lets a request budget be threaded
        through later without fighting this code.
        """
        primary = _StubProvider("mistral", is_cloud=True, fail=True)
        fallback = _StubProvider("nvidia", is_cloud=True)
        self._run(primary, fallback, timeout=5)
        self.assertEqual(primary.calls, [5, 5])
        self.assertEqual(fallback.calls, [5])


class ConfigNaming(unittest.TestCase):

    def test_cloud_attempt_timeout_exists(self):
        self.assertIsInstance(config.CLOUD_ATTEMPT_TIMEOUT, int)

    def test_sarvam_timeout_is_kept_as_an_alias(self):
        """Renaming without an alias would silently change behaviour on any
        deployment whose .env still sets SARVAM_TIMEOUT — including this one.
        """
        self.assertEqual(config.SARVAM_TIMEOUT, config.CLOUD_ATTEMPT_TIMEOUT)

    def test_the_old_env_var_is_still_honoured(self):
        env = {"SARVAM_TIMEOUT": "99"}
        self.assertEqual(self._resolve(env), 99)

    def test_the_new_env_var_wins_over_the_old(self):
        env = {"CLOUD_ATTEMPT_TIMEOUT": "20", "SARVAM_TIMEOUT": "99"}
        self.assertEqual(self._resolve(env), 20)

    def test_a_present_but_empty_value_falls_through_instead_of_crashing(self):
        """A bare "CLOUD_ATTEMPT_TIMEOUT=" line in .env — easy to leave behind
        when commenting a value out — returns "" rather than being absent. With
        a get() default that both shadows the alias and raises ValueError
        inside int() at import, taking the server down before it serves one
        request.
        """
        self.assertEqual(self._resolve({"CLOUD_ATTEMPT_TIMEOUT": ""}), 45)
        self.assertEqual(
            self._resolve({"CLOUD_ATTEMPT_TIMEOUT": "", "SARVAM_TIMEOUT": "99"}), 99)
        self.assertEqual(
            self._resolve({"CLOUD_ATTEMPT_TIMEOUT": "", "SARVAM_TIMEOUT": ""}), 45)

    @staticmethod
    def _resolve(env):
        """Re-run the config expression against a given environment."""
        return int(env.get("CLOUD_ATTEMPT_TIMEOUT")
                   or env.get("SARVAM_TIMEOUT")
                   or "45")


if __name__ == "__main__":
    unittest.main()
