import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import config, rag, faq, projects

config.CHAT_PRIMARY = "selfhosted"
config.SELFHOSTED_MODEL_EN = "qwen2.5-3b-instruct"
config.SELFHOSTED_MODEL_INTL = "sarvam-1-gguf-Q4_K_M"

faq.clear(projects.faq_path("default"))

# The 3 questions that failed under the OLD free-form "hint" approach.
CASES = [
    ("A2", "4th yr tuition", "What is the fourth year tuition fee?", "41250",
     "was: invented 'for NRI/FN/PIO/OCI candidates' framing"),
    ("A3", "1st yr exam fee", "What is the first year examination fee?", "6000",
     "was: fabricated 'for other state candidates... 1500'"),
    ("A4", "internship reg fee", "What is the registration fee during the internship year?", "1500",
     "was: served Rs.34400 (the Total row, not the registration line item)"),
]

for qid, cat, question, expected, prior_failure in CASES:
    t0 = time.time()
    try:
        result = rag.answer("default", question, script_pref="auto", ui_language=None)
        dt = time.time() - t0
        ok = "CONTAINS-EXPECTED" if expected in result["answer"] else "MISSING-EXPECTED"
        print(f"### {qid} ({cat}) ###", flush=True)
        print(f"Q: {question}", flush=True)
        print(f"prior failure: {prior_failure}", flush=True)
        print(f"time={dt:.1f}s model={result['model']} source={result['source']} check={ok}", flush=True)
        print(f"A: {result['answer']}", flush=True)
        print(flush=True)
    except Exception as e:
        print(f"### {qid} ({cat}) ### EXCEPTION: {e!r}", flush=True)
        print(flush=True)

print("ALL DONE", flush=True)
