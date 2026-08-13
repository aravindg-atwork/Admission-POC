import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import config, rag, faq, projects

config.CHAT_PRIMARY = "selfhosted"
config.CHAT_FALLBACK = "selfhosted"
config.SELFHOSTED_MODEL_EN = "qwen2.5-3b-instruct"
config.SELFHOSTED_MODEL_INTL = "sarvam-1-gguf-Q4_K_M"
config.EMBEDDING_PROVIDER = "selfhosted"

faq.clear(projects.faq_path("default"))

CASES = [
    ("A1", "1st yr tuition", "en", None, "What is the first year tuition fee?", "27500"),
    ("A1", "1st yr tuition", "hi", "hi", "पहले वर्ष की ट्यूशन फीस कितनी है?", "27500"),
    ("A1", "1st yr tuition", "mr", "mr", "पहिल्या वर्षाची ट्यूशन फी किती आहे?", "27500"),

    ("B1", "hostel Nagpur 1yr", "en", None, "What is the hostel maintenance fee at Nagpur for the first year?", "12100"),
    ("B1", "hostel Nagpur 1yr", "hi", "hi", "नागपुर में पहले वर्ष के लिए छात्रावास रखरखाव शुल्क कितना है?", "12100"),
    ("B1", "hostel Nagpur 1yr", "mr", "mr", "नागपूरमध्ये पहिल्या वर्षासाठी वसतिगृह देखभाल शुल्क किती आहे?", "12100"),

    ("C1", "NRI special fee", "en", None, "What is the special fee for NRI candidates in the first year?", "12,000"),
    ("C1", "NRI special fee", "hi", "hi", "पहले वर्ष में एनआरआई उम्मीदवारों के लिए विशेष शुल्क क्या है?", "12,000"),
    ("C1", "NRI special fee", "mr", "mr", "पहिल्या वर्षी एनआरआय उमेदवारांसाठी विशेष शुल्क काय आहे?", "12,000"),

    ("F1", "OBC reservation pct", "en", None, "What percentage of seats are reserved for the OBC category?", "19"),
    ("F1", "OBC reservation pct", "hi", "hi", "ओबीसी श्रेणी के लिए कितने प्रतिशत सीटें आरक्षित हैं?", "19"),
    ("F1", "OBC reservation pct", "mr", "mr", "ओबीसी प्रवर्गासाठी किती टक्के जागा राखीव आहेत?", "19"),

    ("H1", "salary honesty", "en", None, "What is the average starting salary after graduating from this course?", None),
    ("H1", "salary honesty", "hi", "hi", "इस कोर्स से स्नातक होने के बाद औसत शुरुआती वेतन क्या है?", None),
    ("H1", "salary honesty", "mr", "mr", "या अभ्यासक्रमातून पदवी घेतल्यानंतर सरासरी सुरुवातीचा पगार किती आहे?", None),
]

for qid, cat, lang, ui_lang, question, expected in CASES:
    t0 = time.time()
    try:
        result = rag.answer("default", question, script_pref="auto", ui_language=ui_lang)
        dt = time.time() - t0
        check = ("CONTAINS-EXPECTED" if expected and expected in result["answer"]
                  else ("MISSING-EXPECTED" if expected else "N/A"))
        print(f"### {qid}[{lang}] ({cat}) ###", flush=True)
        print(f"Q: {question}", flush=True)
        print(f"time={dt:.1f}s model={result['model']} source={result['source']} check={check} pages={result['pages']}", flush=True)
        print(f"A: {result['answer']}", flush=True)
        print(flush=True)
    except Exception as e:
        print(f"### {qid}[{lang}] ({cat}) ### EXCEPTION: {e!r}", flush=True)
        print(flush=True)

print("ALL DONE", flush=True)
