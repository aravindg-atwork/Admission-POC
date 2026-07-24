"""Test language routing with proper UTF-8 (avoids shell mangling of Indic text)."""
import json
import sys
import time
import urllib.request

KEY = "aas_ZdcJwB9E5XrusIYB0pO0HYk-WK4kzEs8Qz4HSLd-vJY"
URL = "http://localhost:5050/api/chat"

questions = {
    "Hindi": "प्रवेश के लिए पात्रता मानदंड क्या हैं?",
    "Marathi": "प्रवेशासाठी पात्रता निकष काय आहेत?",
}

target = sys.argv[1] if len(sys.argv) > 1 else None

for label, q in questions.items():
    if target and label.lower() != target.lower():
        continue
    print(f"\n=== {label}: {q} ===")
    body = json.dumps({"question": q}).encode("utf-8")
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json", "X-API-Key": KEY},
                                 method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=280) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    dt = time.time() - t0
    print(f"model: {d['model']} | lang: {d['language']} | {dt:.1f}s")
    print(d["answerText"][:700])
