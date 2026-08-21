"""A ceiling on concurrent expensive requests.

ThreadingHTTPServer starts a thread per connection and never stops. That is
fine when a request is a file read, and it is not fine here: one answer makes
three to five provider calls, so each in-flight request holds a thread for
seconds AND holds a slot against a rate-limited upstream.

Without a ceiling the failure under load is the worst-shaped one available -
every student is admitted, they all queue at the provider, the provider starts
returning 429, and everybody gets a slow error instead of some people getting
fast answers. Measured on this deployment: a single SEQUENTIAL 75-question eval
run drew `HTTPError 429: Too Many Requests` from Mistral eleven times, and
where the fallback also failed the student got "request failed". CLAUDE.md
records the same shape for Groq - a whole day's token ceiling reached inside
one test run. Real concurrency reaches those limits much faster than a
sequential run.

So the queue is held here, where it is visible and refusable, rather than at
the provider where it is a 429. A refused request is a worse answer than an
answer and a much better one than work accepted only to time out.

Fails open, deliberately: a limit of 0 disables the ceiling rather than
wedging the server, because a misconfigured knob should not be able to take
the service down.
"""

import contextlib
import threading

from .. import config


class Limiter:
    """Bounded admission with a short grace wait.

    `wait_seconds` exists so a brief burst becomes a small delay instead of a
    refusal - the interesting overload is sustained, not instantaneous.
    """

    def __init__(self, limit, wait_seconds):
        self._limit = limit
        self._wait = wait_seconds
        self._semaphore = threading.BoundedSemaphore(limit) if limit > 0 else None
        self._lock = threading.Lock()
        self._in_flight = 0

    @property
    def in_flight(self):
        with self._lock:
            return self._in_flight

    @contextlib.contextmanager
    def acquire(self):
        """Yield True if admitted, False if refused.

        BoundedSemaphore, not Semaphore: releasing a slot that was never
        acquired raises here instead of silently inflating the ceiling. The
        refusal path below must therefore never release - which is the bug this
        shape is chosen to make loud rather than subtle, since an inflated
        ceiling only misbehaves under exactly the load the limit exists for.
        """
        if self._semaphore is None:
            yield True
            return

        admitted = self._semaphore.acquire(timeout=self._wait) if self._wait \
            else self._semaphore.acquire(blocking=False)
        if not admitted:
            yield False
            return

        with self._lock:
            self._in_flight += 1
        try:
            yield True
        finally:
            # finally, not a plain trailing call: a handler that raises must
            # still give its slot back, or the server degrades permanently
            # after a handful of errors.
            with self._lock:
                self._in_flight -= 1
            self._semaphore.release()


# One shared ceiling for the answer path. Static files and admin reads are
# cheap and deliberately not counted against it.
chat_limiter = Limiter(config.MAX_CONCURRENT_CHATS, config.CHAT_QUEUE_WAIT_SECONDS)


def refuse(handler):
    """Send the overload response."""
    handler.send_response(503)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Retry-After", str(config.CHAT_RETRY_AFTER_SECONDS))
    handler.send_header("Access-Control-Allow-Origin", "*")
    body = (
        '{"error": "busy", "answerText": "A lot of students are asking '
        'questions right now. Please try again in a few seconds."}'
    ).encode("utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionAbortedError):
        pass
