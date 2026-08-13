import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import rag

CASES = [
    ("ta", "ta", "முதல் ஆண்டு கல்விக் கட்டணம் என்ன?", "27500"),
    ("ta-hostel", "ta", "நாக்பூரில் விடுதிக் கட்டணம் என்ன?", None),
    ("mr-docs", "mr", "प्रवेशासाठी कोणती कागदपत्रे लागतात?", None),
    ("hi-nri", "hi", "एनआरआई उम्मीदवारों के लिए विशेष शुल्क क्या है?", "12000"),
    ("en-fake", None, "Is there a scholarship for sports quota students?", None),
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
