import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import rag

CASES = [
    ("en", None, "What is the first year tuition fee?", "27500"),
    ("hi", "hi", "पहले वर्ष की ट्यूशन फीस कितनी है?", "27500"),
    ("mr", "mr", "पहिल्या वर्षाची ट्यूशन फी किती आहे?", "27500"),
    ("ta", "ta", "முதல் ஆண்டு கல்விக் கட்டணம் என்ன?", "27500"),
    ("hinglish", "hi", "Pehle year ka tuition fee kitna hai?", "27500"),
    ("en", None, "What is the hostel maintenance fee at Nagpur for the first year?", "12100"),
    ("en", None, "What is the total admission fee for unreserved category?", "62635"),
    ("en", None, "What is the special fee for NRI candidates?", "12000"),
    ("en", None, "What is the average salary after graduating from this course?", None),
    ("en", None, "How many rounds are there in the admission process?", None),
]

for label, ui_lang, question, expect in CASES:
    t0 = time.time()
    try:
        result = rag.answer("default", question, script_pref="auto", ui_language=ui_lang)
        dt = time.time() - t0
        ans = result["answer"]
        model = result["model"]
        pages = result["pages"]
        ok = ("CONTAINS-EXPECTED" if expect and expect in ans else
              ("NO-EXPECTED-FIGURE" if expect else "N/A"))
        print(f"=== [{label}] {question!r} ===", flush=True)
        print(f"  time={dt:.1f}s model={model} pages={pages} check={ok}", flush=True)
        print(f"  answer: {ans}", flush=True)
        print(flush=True)
    except Exception as e:
        print(f"=== [{label}] {question!r} === EXCEPTION: {e!r}", flush=True)
        print(flush=True)

print("DONE", flush=True)
