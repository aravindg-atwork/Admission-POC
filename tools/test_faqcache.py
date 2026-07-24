"""Test FAQ cache: same question twice; second should be instant (source=faq-cache)."""
import json
import time
import urllib.request

KEY = "aas_ZdcJwB9E5XrusIYB0pO0HYk-WK4kzEs8Qz4HSLd-vJY"
URL = "http://localhost:5050/api/chat"


def ask(q):
    body = json.dumps({"question": q}).encode("utf-8")
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json", "X-API-Key": KEY},
                                 method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=280) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    return d, time.time() - t0


q = "What are the eligibility criteria for admission?"
print("=== 1st ask (cold RAG+LLM) ===")
d1, t1 = ask(q)
print(f"source={d1['source']} model={d1['model']} {t1:.1f}s")

print("\n=== 2nd ask, same question (should hit FAQ cache) ===")
d2, t2 = ask(q)
print(f"source={d2['source']} model={d2['model']} {t2:.1f}s")

print("\n=== 3rd ask, reworded (semantic cache match?) ===")
d3, t3 = ask("What is the eligibility to get admission?")
print(f"source={d3['source']} model={d3['model']} {t3:.1f}s")
