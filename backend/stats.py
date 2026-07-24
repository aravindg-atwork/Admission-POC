"""Usage stats for the dashboard and cost panel.

Tracks counts and timing only - never question or answer text - so the console
can show volume, cache effectiveness, and per-service cost exposure without
logging conversation content.

One stats file per project - every function takes that project's own
stats_path (see projects.py), so each project's dashboard/cost numbers are
its own.
"""

import json
import threading
import time

_lock = threading.Lock()
_RECENT_CAP = 25
_LATENCY_CAP = 200


def _empty():
    return {
        "total_questions": 0,
        "cache_hits": 0,
        "greetings": 0,
        "rag_calls": 0,
        "sarvam_calls": 0,
        "local_calls": 0,
        "lang_counts": {"latin": 0, "devanagari": 0, "tamil": 0},
        "latencies_ms": [],
        "recent": [],  # [{ts, language, source, model, latencyMs}] - no question/answer text
    }


def _load(stats_path):
    if not stats_path.exists():
        return _empty()
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
        merged = _empty()
        merged.update(data)
        return merged
    except ValueError:
        return _empty()


def _save(stats_path, d):
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(d), encoding="utf-8")


def record(stats_path, source, model, language, latency_ms):
    with _lock:
        d = _load(stats_path)
        d["total_questions"] += 1

        if source == "faq-cache":
            d["cache_hits"] += 1
        elif source == "greeting":
            d["greetings"] += 1
        else:
            d["rag_calls"] += 1

        if model and str(model).startswith("sarvam:"):
            d["sarvam_calls"] += 1
        elif source != "faq-cache":
            d["local_calls"] += 1

        d["lang_counts"][language] = d["lang_counts"].get(language, 0) + 1

        d["latencies_ms"] = (d.get("latencies_ms", []) + [latency_ms])[-_LATENCY_CAP:]
        d["recent"] = (d.get("recent", []) + [{
            "ts": time.time(), "language": language, "source": source,
            "model": model, "latencyMs": latency_ms,
        }])[-_RECENT_CAP:]

        _save(stats_path, d)


def snapshot(stats_path):
    d = _load(stats_path)
    lat = d.get("latencies_ms", [])
    total = d["total_questions"] or 1
    return {
        "totalQuestions": d["total_questions"],
        "cacheHits": d["cache_hits"],
        "cacheHitRate": round(d["cache_hits"] / total * 100, 1),
        "ragCalls": d["rag_calls"],
        "greetings": d["greetings"],
        "sarvamCalls": d["sarvam_calls"],
        "localCalls": d["local_calls"],
        "avgLatencyMs": round(sum(lat) / len(lat)) if lat else 0,
        "languages": d["lang_counts"],
        "recent": list(reversed(d.get("recent", []))),
    }
