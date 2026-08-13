import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import config, rag, faq, projects

config.CHAT_PRIMARY = "selfhosted"
config.SELFHOSTED_MODEL_EN = "qwen2.5-3b-instruct"
config.SELFHOSTED_MODEL_INTL = "sarvam-1-gguf-Q4_K_M"

faq.clear(projects.faq_path("default"))

# (id, category, ui_lang, question, expect_substring_or_None)
QUESTIONS = [
    ("A1", "1st yr tuition", "hi", "पहले वर्ष की ट्यूशन फीस कितनी है?"),
    ("A1", "1st yr tuition", "mr", "पहिल्या वर्षाची ट्यूशन फी किती आहे?"),
    ("A2", "4th yr tuition", "hi", "चौथे वर्ष की ट्यूशन फीस कितनी है?"),
    ("A2", "4th yr tuition", "mr", "चौथ्या वर्षाची ट्यूशन फी किती आहे?"),
    ("A3", "1st yr exam fee", "hi", "पहले वर्ष की परीक्षा शुल्क कितनी है?"),
    ("A3", "1st yr exam fee", "mr", "पहिल्या वर्षाची परीक्षा फी किती आहे?"),
    ("A4", "internship reg fee", "hi", "इंटर्नशिप वर्ष के दौरान पंजीकरण शुल्क कितना है?"),
    ("A4", "internship reg fee", "mr", "इंटर्नशिप वर्षादरम्यान नोंदणी फी किती आहे?"),
    ("A5", "total admission unreserved", "hi", "अनारक्षित श्रेणी के उम्मीदवार के लिए कुल प्रवेश शुल्क कितना है?"),
    ("A5", "total admission unreserved", "mr", "अनारक्षित प्रवर्गातील उमेदवारासाठी एकूण प्रवेश शुल्क किती आहे?"),
    ("A6", "total admission reserved", "hi", "आरक्षित श्रेणी के उम्मीदवार के लिए कुल प्रवेश शुल्क कितना है?"),
    ("A6", "total admission reserved", "mr", "आरक्षित प्रवर्गातील उमेदवारासाठी एकूण प्रवेश शुल्क किती आहे?"),
    ("B1", "hostel maint Nagpur 1yr", "hi", "नागपुर में पहले वर्ष के लिए छात्रावास रखरखाव शुल्क कितना है?"),
    ("B1", "hostel maint Nagpur 1yr", "mr", "नागपूरमध्ये पहिल्या वर्षासाठी वसतिगृह देखभाल शुल्क किती आहे?"),
    ("D1", "min marks unreserved", "hi", "अनारक्षित श्रेणी के उम्मीदवारों के लिए न्यूनतम कितने प्रतिशत अंक चाहिए?"),
    ("D1", "min marks unreserved", "mr", "अनारक्षित प्रवर्गातील उमेदवारांसाठी किमान किती टक्के गुण आवश्यक आहेत?"),
    ("D3", "min age", "hi", "प्रवेश के लिए न्यूनतम आयु कितनी आवश्यक है?"),
    ("D3", "min age", "mr", "प्रवेशासाठी किमान वय किती आवश्यक आहे?"),
    ("F1", "OBC reservation pct", "hi", "ओबीसी श्रेणी के लिए कितने प्रतिशत सीटें आरक्षित हैं?"),
    ("F1", "OBC reservation pct", "mr", "ओबीसी प्रवर्गासाठी किती टक्के जागा राखीव आहेत?"),
    ("H1", "salary honesty", "hi", "इस कोर्स से स्नातक होने के बाद औसत शुरुआती वेतन क्या है?"),
    ("H1", "salary honesty", "mr", "या अभ्यासक्रमातून पदवी घेतल्यानंतर सरासरी सुरुवातीचा पगार किती आहे?"),
]

for qid, cat, ui_lang, question in QUESTIONS:
    t0 = time.time()
    try:
        result = rag.answer("default", question, script_pref="auto", ui_language=ui_lang)
        dt = time.time() - t0
        print(f"### {qid}[{ui_lang}] ({cat}) ###", flush=True)
        print(f"Q: {question}", flush=True)
        print(f"time={dt:.1f}s model={result['model']} source={result['source']} pages={result['pages']}", flush=True)
        print(f"A: {result['answer']}", flush=True)
        print(flush=True)
    except Exception as e:
        print(f"### {qid}[{ui_lang}] ({cat}) ### EXCEPTION: {e!r}", flush=True)
        print(flush=True)

print("ALL DONE", flush=True)
