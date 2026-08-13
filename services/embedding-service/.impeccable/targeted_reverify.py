import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import rag, faq, projects

faq.clear(projects.faq_path("default"))

# (label, ui_lang, question, expected_note) - prerequisite calls populate the
# cache exactly like the original run did; the paired test call right after
# is the one that previously collided.
SEQUENCE = [
    ("B1[en] (prereq: Nagpur hostel maint 1yr)", None, "What is the hostel maintenance fee at Nagpur for the first year?", "12100"),
    ("B2[en] (Mumbai hostel maint 1yr - was served Nagpur's 12100)", None, "What is the hostel maintenance fee at Mumbai for the first year?", "14850"),
    ("B3[en] (total Nagpur hostel 1yr - was served maintenance-only 12100)", None, "What is the total hostel fee at Nagpur for the first year, including all charges?", "27300"),

    ("B1[hi] (prereq)", "hi", "नागपुर में पहले वर्ष के लिए छात्रावास रखरखाव शुल्क कितना है?", "12100"),
    ("B2[hi] (Mumbai - was served Nagpur's 12100)", "hi", "मुंबई में पहले वर्ष के लिए छात्रावास रखरखाव शुल्क कितना है?", "14850"),
    ("B3[hi] (total Nagpur - was served maintenance-only)", "hi", "नागपुर में पहले वर्ष के लिए सभी शुल्कों सहित कुल छात्रावास शुल्क कितना है?", "27300"),

    ("B1[mr] (prereq)", "mr", "नागपूरमध्ये पहिल्या वर्षासाठी वसतिगृह देखभाल शुल्क किती आहे?", "12100"),
    ("B2[mr] (Mumbai - was served Nagpur's 12100)", "mr", "मुंबईमध्ये पहिल्या वर्षासाठी वसतिगृह देखभाल शुल्क किती आहे?", "14850"),
    ("B3[mr] (total Nagpur - was served maintenance-only)", "mr", "नागपूरमध्ये पहिल्या वर्षासाठी सर्व शुल्कांसह एकूण वसतिगृह शुल्क किती आहे?", "27300"),

    ("A7[hi] (prereq: NRI base fee)", "hi", "एनआरआई उम्मीदवार के लिए विशेष शुल्क से पहले का मूल प्रवेश शुल्क कितना है?", "63135"),
    ("C1[hi] (NRI SPECIAL fee yr1 - was served A7's base fee)", "hi", "पहले वर्ष में एनआरआई उम्मीदवारों के लिए विशेष शुल्क क्या है?", "12,000 or 12000"),

    ("A3[mr] (prereq: exam fee)", "mr", "पहिल्या वर्षाची परीक्षा फी किती आहे?", "6000"),
    ("C1[mr] (NRI SPECIAL fee yr1 - was served exam fee answer)", "mr", "पहिल्या वर्षी एनआरआय उमेदवारांसाठी विशेष शुल्क काय आहे?", "12,000 or 12000"),

    ("B4[hi] (prereq: Shirwal hostel 4yr)", "hi", "शिरवल में चौथे वर्ष के लिए कुल छात्रावास शुल्क कितना है?", "25575"),
    ("C2[hi] (NRI SPECIAL fee yr4 - was served Shirwal hostel fee)", "hi", "चौथे वर्ष में एनआरआई उम्मीदवारों के लिए विशेष शुल्क क्या है?", "18,000 or 18000"),

    ("B4[mr] (prereq: Shirwal hostel 4yr)", "mr", "शिरवळमध्ये चौथ्या वर्षासाठी एकूण वसतिगृह शुल्क किती आहे?", "25575"),
    ("C2[mr] (NRI SPECIAL fee yr4 - was served Shirwal hostel fee)", "mr", "चौथ्या वर्षी एनआरआय उमेदवारांसाठी विशेष शुल्क काय आहे?", "18,000 or 18000"),

    ("E1[mr] (prereq: application fee)", "mr", "अनारक्षित प्रवर्गातील उमेदवारांसाठी अर्ज शुल्क किती आहे?", "1000"),
    ("E2[mr] (grievance fee - was served application fee)", "mr", "तक्रार अर्ज सादर करण्यासाठी शुल्क किती आहे?", "200"),

    ("D2[hi] (prereq: min marks reserved %)", "hi", "आरक्षित श्रेणी के उम्मीदवारों के लिए न्यूनतम कितने प्रतिशत अंक चाहिए?", "47.5"),
    ("F3[hi] (PH seat % - was served min-marks % answer)", "hi", "शारीरिक रूप से विकलांग उम्मीदवारों के लिए कितने प्रतिशत सीटें आरक्षित हैं?", "5"),

    ("A5[hi] (non-cache: had misattached govt-funding qualifier)", "hi", "अनारक्षित श्रेणी के उम्मीदवार के लिए कुल प्रवेश शुल्क कितना है?", "62635, no govt-funding condition"),

    ("G1[hi] (non-cache: structural imprecision on rounds)", "hi", "प्रवेश प्रक्रिया में कितने राउंड होते हैं, और हर राउंड में क्या होता है?", "4 rounds, no CAP/institutional-quota language"),
]

for label, ui_lang, question, note in SEQUENCE:
    t0 = time.time()
    try:
        result = rag.answer("default", question, script_pref="auto", ui_language=ui_lang)
        dt = time.time() - t0
        print(f"### {label} ###", flush=True)
        print(f"Q: {question}", flush=True)
        print(f"expected: {note}", flush=True)
        print(f"time={dt:.1f}s model={result['model']} pages={result['pages']}", flush=True)
        print(f"A: {result['answer']}", flush=True)
        print(flush=True)
    except Exception as e:
        print(f"### {label} ### EXCEPTION: {e!r}", flush=True)
        print(flush=True)

print("ALL DONE", flush=True)
