"""In-flight work is bounded, and overload is refused rather than absorbed.

ThreadingHTTPServer spawns a thread per connection with no ceiling. At the
10-50 concurrent students this deployment is sized for, with an answer path
that makes three to five provider calls, that is not backpressure - it is
thread accumulation, and every one of those threads is also holding a slot
against the upstream provider.

This is not hypothetical. A single sequential 75-question eval run already
drove Mistral to `HTTPError 429: Too Many Requests` eleven times, and when the
fallback also failed the student got "request failed". CLAUDE.md records the
same shape for Groq: a 100k-tokens/day ceiling reached inside one test run.
Concurrency will reach these limits far faster than a sequential run does.

Refusing a request with 503 + Retry-After is a worse answer than answering it
and a much better one than accepting work that will queue behind a rate limit
until it times out. Degrade visibly.

No network, no keys.
"""

import threading
import time
import unittest

from backend.http import concurrency


class Limiter(unittest.TestCase):

    def test_admits_up_to_the_limit(self):
        limiter = concurrency.Limiter(2, wait_seconds=0)
        with limiter.acquire() as first, limiter.acquire() as second:
            self.assertTrue(first)
            self.assertTrue(second)

    def test_refuses_beyond_the_limit(self):
        limiter = concurrency.Limiter(1, wait_seconds=0)
        with limiter.acquire() as first:
            self.assertTrue(first)
            with limiter.acquire() as second:
                self.assertFalse(second)

    def test_a_slot_is_released_when_the_request_finishes(self):
        limiter = concurrency.Limiter(1, wait_seconds=0)
        with limiter.acquire() as first:
            self.assertTrue(first)
        with limiter.acquire() as second:
            self.assertTrue(second)

    def test_a_slot_is_released_even_when_the_request_raises(self):
        """A handler that blows up must not leak its slot, or the server
        degrades permanently after a few errors — exactly the failure mode
        this is meant to prevent.
        """
        limiter = concurrency.Limiter(1, wait_seconds=0)
        with self.assertRaises(RuntimeError):
            with limiter.acquire() as admitted:
                self.assertTrue(admitted)
                raise RuntimeError("handler exploded")
        with limiter.acquire() as after:
            self.assertTrue(after)

    def test_a_refused_request_does_not_release_a_slot_it_never_held(self):
        """The subtle bug: if the refusal path still calls release(), the
        semaphore's count grows every time the server is overloaded, and the
        limit silently stops applying under exactly the load it exists for.
        """
        limiter = concurrency.Limiter(1, wait_seconds=0)
        with limiter.acquire() as first:
            self.assertTrue(first)
            for _ in range(5):
                with limiter.acquire() as refused:
                    self.assertFalse(refused)
        # Still exactly one slot, not six.
        with limiter.acquire() as a:
            self.assertTrue(a)
            with limiter.acquire() as b:
                self.assertFalse(b)

    def test_it_waits_briefly_before_refusing(self):
        """A burst that clears in milliseconds should be absorbed, not
        refused — a short wait converts a spike into a small delay.
        """
        limiter = concurrency.Limiter(1, wait_seconds=2.0)
        holder_done = threading.Event()

        def hold():
            with limiter.acquire():
                time.sleep(0.15)
            holder_done.set()

        thread = threading.Thread(target=hold)
        thread.start()
        time.sleep(0.02)
        started = time.time()
        with limiter.acquire() as admitted:
            waited = time.time() - started
            self.assertTrue(admitted, "should have waited for the slot")
        self.assertGreater(waited, 0.05)
        thread.join()
        self.assertTrue(holder_done.is_set())

    def test_zero_disables_the_limit(self):
        """An escape hatch: setting the limit to 0 must not wedge the server.
        A misconfigured ceiling should fail open, not closed.
        """
        limiter = concurrency.Limiter(0, wait_seconds=0)
        with limiter.acquire() as a, limiter.acquire() as b, limiter.acquire() as c:
            self.assertTrue(a and b and c)

    def test_reports_how_many_are_in_flight(self):
        limiter = concurrency.Limiter(4, wait_seconds=0)
        self.assertEqual(limiter.in_flight, 0)
        with limiter.acquire():
            self.assertEqual(limiter.in_flight, 1)
            with limiter.acquire():
                self.assertEqual(limiter.in_flight, 2)
        self.assertEqual(limiter.in_flight, 0)


class Config(unittest.TestCase):

    def test_the_default_limit_is_sane_for_the_stated_load(self):
        """Sized for 10-50 concurrent students against providers that
        rate-limit. The point is to hold a queue here, where it is visible and
        refusable, rather than at the provider, where it is a 429.
        """
        from backend import config
        self.assertGreater(config.MAX_CONCURRENT_CHATS, 0)
        self.assertLessEqual(config.MAX_CONCURRENT_CHATS, 64)


if __name__ == "__main__":
    unittest.main()
