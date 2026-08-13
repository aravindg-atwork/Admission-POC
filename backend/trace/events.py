"""Trace event shape and the per-request collector.

A trace event is a plain dict:

    {"traceId": "<uuid4, one per /api/chat request>", "projectId": "default",
     "seq": 0, "ts": 1755000000.123,
     "step": "guard" | "cache_lookup" | "routing" | "retrieval" |
             "table_lookup" | "generation" | "validation" | "final_answer",
     "detail": {...step-specific fields...}}

Live/ephemeral only, by design - see hub.py's module docstring for the
privacy note. Nothing here is ever written to disk.
"""

import time
import uuid

from . import hub


class TraceCollector:
    """One instance per /api/chat request, built alongside the guard-stage
    ctx (see rag/answer.py's _build_context) and passed around as
    `ctx.trace` - not the collector itself, just its bound `record` method,
    so guards.py/orchestrator.py/comparison.py can call `ctx.trace(step,
    **fields)` without needing to know a collector object exists at all, or
    that trace/hub.py exists - this is the one place that couples the two.

    Publishes each event to hub.py immediately as it's recorded, not
    batched until the request finishes - an admin watching the live trace
    sees each step (a guard firing, retrieval completing, generation
    starting) as it actually happens, which matters here specifically
    because a single request can take anywhere from under a second to over
    a minute (see llm.py's provider latency notes) - batching until the end
    would mean the live view showed nothing for the whole span of a slow
    request, then everything at once.
    """

    def __init__(self, project_id):
        self.trace_id = uuid.uuid4().hex
        self.project_id = project_id
        self._events = []

    def record(self, step, **detail):
        event = {
            "traceId": self.trace_id,
            "projectId": self.project_id,
            "seq": len(self._events),
            "ts": time.time(),
            "step": step,
            "detail": detail,
        }
        self._events.append(event)
        hub.publish(event)
        return event

    @property
    def events(self):
        return list(self._events)
