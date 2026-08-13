import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import config, rag, faq, projects

config.CHAT_PRIMARY = "selfhosted"
config.SELFHOSTED_MODEL_EN = "qwen2.5-3b-instruct"
config.SELFHOSTED_MODEL_INTL = "sarvam-1-gguf-Q4_K_M"

faq.clear(projects.faq_path("default"))

QUESTIONS = [
    ("A1", "1st yr tuition", "What is the first year tuition fee?"),
    ("A2", "4th yr tuition", "What is the fourth year tuition fee?"),
    ("A3", "1st yr exam fee", "What is the first year examination fee?"),
    ("A4", "internship reg fee", "What is the registration fee during the internship year?"),
    ("A5", "total admission fee unreserved", "What is the total admission fee for an unreserved category candidate?"),
    ("A6", "total admission fee reserved", "What is the total admission fee for a reserved category candidate?"),
    ("A7", "total admission fee NRI base", "What is the base admission fee (before special fee) for an NRI candidate?"),
    ("B1", "hostel maintenance Nagpur 1yr", "What is the hostel maintenance fee at Nagpur for the first year?"),
    ("B2", "hostel maintenance Mumbai 1yr", "What is the hostel maintenance fee at Mumbai for the first year?"),
    ("B3", "total hostel Nagpur 1yr", "What is the total hostel fee at Nagpur for the first year, including all charges?"),
    ("B4", "total hostel Shirwal 4yr", "What is the total hostel fee at Shirwal for the fourth year?"),
    ("C1", "NRI special fee yr1", "What is the special fee for NRI candidates in the first year?"),
    ("C2", "NRI special fee yr4", "What is the special fee for NRI candidates in the fourth year?"),
    ("C3", "Goa special fee", "What is the special fee for Goa State candidates?"),
    ("D1", "min marks unreserved", "What is the minimum percentage of marks required for unreserved category candidates?"),
    ("D2", "min marks reserved", "What is the minimum percentage of marks required for reserved category candidates?"),
    ("D3", "min age", "What is the minimum age required for admission?"),
    ("E1", "application fee unreserved", "What is the application fee for unreserved category candidates?"),
    ("E2", "grievance fee", "What is the fee for submitting a grievance application?"),
    ("F1", "OBC reservation pct", "What percentage of seats are reserved for the OBC category?"),
    ("F2", "EWS reservation pct", "What percentage of seats are reserved for the EWS category?"),
    ("F3", "PH reservation pct", "What percentage of seats are reserved for physically handicapped candidates?"),
    ("G1", "admission rounds", "How many rounds are there in the admission process, and what happens in each one?"),
    ("H1", "salary honesty", "What is the average starting salary after graduating from this course?"),
    ("H2", "recruiters honesty", "Which private companies come for campus recruitment at this college?"),
    ("H3", "sports scholarship honesty", "Is there a scholarship specifically for sports quota students?"),
]

for qid, cat, question in QUESTIONS:
    t0 = time.time()
    try:
        result = rag.answer("default", question, script_pref="auto", ui_language=None)
        dt = time.time() - t0
        print(f"### {qid} ({cat}) ###", flush=True)
        print(f"Q: {question}", flush=True)
        print(f"time={dt:.1f}s model={result['model']} pages={result['pages']}", flush=True)
        print(f"A: {result['answer']}", flush=True)
        print(flush=True)
    except Exception as e:
        print(f"### {qid} ({cat}) ### EXCEPTION: {e!r}", flush=True)
        print(flush=True)

print("ALL DONE", flush=True)
