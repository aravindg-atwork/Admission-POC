"""In-memory pub/sub broadcast hub for the live admin trace view (Request 3).

Genuinely different privacy posture from stats.py/reviewlog.py, deliberately
so - this broadcasts full real question/answer text, live, to any currently
connected, admin-token-authenticated viewer. Nothing here is ever written to
disk: subscriber state lives entirely in this process's memory, gone the
instant the process restarts or the last admin disconnects. That is the
explicit, owner-confirmed design (see the 2026-08-13 plan) - "lively see the
agent working" needs real question/answer content to be useful, not just
anonymized step names, and this is a live-viewing feature, not a permanent
searchable transcript archive.

The one non-negotiable correctness property: publish() must never block a
real /api/chat request thread on a slow admin viewer. Each subscriber gets
its own bounded queue; publish uses put_nowait and silently drops the event
for that one slow/stuck subscriber on queue.Full rather than waiting - a
stuck browser tab must never be able to slow down a student's chat request.
"""

import queue
import threading

_lock = threading.Lock()
_subscribers = set()


def subscribe():
    """Registers a new bounded queue and returns it. Callers (the SSE route
    handler) must call unsubscribe() when the connection closes, however it
    closes - see http/trace_routes.py's try/finally.
    """
    q = queue.Queue(maxsize=200)
    with _lock:
        _subscribers.add(q)
    return q


def unsubscribe(q):
    with _lock:
        _subscribers.discard(q)


def publish(event):
    """Broadcasts one trace event to every currently-connected subscriber.
    Called once per ctx.trace(...) (see trace/events.py's TraceCollector),
    so an admin watching /admin/trace/stream sees each step as it actually
    happens - a guard firing, retrieval completing, the final answer -
    rather than only the whole trace at once after the request is done.
    """
    with _lock:
        subscribers = list(_subscribers)
    for q in subscribers:
        try:
            q.put_nowait(event)
        except queue.Full:
            # That one viewer's queue is backed up (a stuck/slow browser
            # tab) - drop the event for them specifically. Never blocks,
            # never affects any other subscriber or the publishing request.
            pass
