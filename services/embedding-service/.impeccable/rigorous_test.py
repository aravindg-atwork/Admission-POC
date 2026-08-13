import sys, time
sys.path.insert(0, "/Users/aravind/Desktop/AI Assistant POC/Admission-POC")
from backend import rag, faq, projects

faq.clear(projects.faq_path("default"))

QUESTIONS = [
    # id, category, en, hi, mr
    ("A1", "1st yr tuition", "What is the first year tuition fee?",
     "पहले वर्ष की ट्यूशन फीस कितनी है?", "पहिल्या वर्षाची ट्यूशन फी किती आहे?"),
    ("A2", "4th yr tuition", "What is the fourth year tuition fee?",
     "चौथे वर्ष की ट्यूशन फीस कितनी है?", "चौथ्या वर्षाची ट्यूशन फी किती आहे?"),
    ("A3", "1st yr exam fee", "What is the first year examination fee?",
     "पहले वर्ष की परीक्षा शुल्क कितनी है?", "पहिल्या वर्षाची परीक्षा फी किती आहे?"),
    ("A4", "internship reg fee", "What is the registration fee during the internship year?",
     "इंटर्नशिप वर्ष के दौरान पंजीकरण शुल्क कितना है?", "इंटर्नशिप वर्षादरम्यान नोंदणी फी किती आहे?"),
    ("A5", "total admission fee unreserved", "What is the total admission fee for an unreserved category candidate?",
     "अनारक्षित श्रेणी के उम्मीदवार के लिए कुल प्रवेश शुल्क कितना है?",
     "अनारक्षित प्रवर्गातील उमेदवारासाठी एकूण प्रवेश शुल्क किती आहे?"),
    ("A6", "total admission fee reserved", "What is the total admission fee for a reserved category candidate?",
     "आरक्षित श्रेणी के उम्मीदवार के लिए कुल प्रवेश शुल्क कितना है?",
     "आरक्षित प्रवर्गातील उमेदवारासाठी एकूण प्रवेश शुल्क किती आहे?"),
    ("A7", "total admission fee NRI base", "What is the base admission fee (before special fee) for an NRI candidate?",
     "एनआरआई उम्मीदवार के लिए विशेष शुल्क से पहले का मूल प्रवेश शुल्क कितना है?",
     "एनआरआय उमेदवारासाठी विशेष फी वगळून मूळ प्रवेश शुल्क किती आहे?"),
    ("B1", "hostel maintenance Nagpur 1yr", "What is the hostel maintenance fee at Nagpur for the first year?",
     "नागपुर में पहले वर्ष के लिए छात्रावास रखरखाव शुल्क कितना है?",
     "नागपूरमध्ये पहिल्या वर्षासाठी वसतिगृह देखभाल शुल्क किती आहे?"),
    ("B2", "hostel maintenance Mumbai 1yr", "What is the hostel maintenance fee at Mumbai for the first year?",
     "मुंबई में पहले वर्ष के लिए छात्रावास रखरखाव शुल्क कितना है?",
     "मुंबईमध्ये पहिल्या वर्षासाठी वसतिगृह देखभाल शुल्क किती आहे?"),
    ("B3", "total hostel Nagpur 1yr", "What is the total hostel fee at Nagpur for the first year, including all charges?",
     "नागपुर में पहले वर्ष के लिए सभी शुल्कों सहित कुल छात्रावास शुल्क कितना है?",
     "नागपूरमध्ये पहिल्या वर्षासाठी सर्व शुल्कांसह एकूण वसतिगृह शुल्क किती आहे?"),
    ("B4", "total hostel Shirwal 4yr", "What is the total hostel fee at Shirwal for the fourth year?",
     "शिरवल में चौथे वर्ष के लिए कुल छात्रावास शुल्क कितना है?",
     "शिरवळमध्ये चौथ्या वर्षासाठी एकूण वसतिगृह शुल्क किती आहे?"),
    ("C1", "NRI special fee yr1", "What is the special fee for NRI candidates in the first year?",
     "पहले वर्ष में एनआरआई उम्मीदवारों के लिए विशेष शुल्क क्या है?",
     "पहिल्या वर्षी एनआरआय उमेदवारांसाठी विशेष शुल्क काय आहे?"),
    ("C2", "NRI special fee yr4", "What is the special fee for NRI candidates in the fourth year?",
     "चौथे वर्ष में एनआरआई उम्मीदवारों के लिए विशेष शुल्क क्या है?",
     "चौथ्या वर्षी एनआरआय उमेदवारांसाठी विशेष शुल्क काय आहे?"),
    ("C3", "Goa special fee", "What is the special fee for Goa State candidates?",
     "गोवा राज्य के उम्मीदवारों के लिए विशेष शुल्क क्या है?",
     "गोवा राज्यातील उमेदवारांसाठी विशेष शुल्क काय आहे?"),
    ("D1", "min marks unreserved", "What is the minimum percentage of marks required for unreserved category candidates?",
     "अनारक्षित श्रेणी के उम्मीदवारों के लिए न्यूनतम कितने प्रतिशत अंक चाहिए?",
     "अनारक्षित प्रवर्गातील उमेदवारांसाठी किमान किती टक्के गुण आवश्यक आहेत?"),
    ("D2", "min marks reserved", "What is the minimum percentage of marks required for reserved category candidates?",
     "आरक्षित श्रेणी के उम्मीदवारों के लिए न्यूनतम कितने प्रतिशत अंक चाहिए?",
     "आरक्षित प्रवर्गातील उमेदवारांसाठी किमान किती टक्के गुण आवश्यक आहेत?"),
    ("D3", "min age", "What is the minimum age required for admission?",
     "प्रवेश के लिए न्यूनतम आयु कितनी आवश्यक है?", "प्रवेशासाठी किमान वय किती आवश्यक आहे?"),
    ("E1", "application fee unreserved", "What is the application fee for unreserved category candidates?",
     "अनारक्षित श्रेणी के उम्मीदवारों के लिए आवेदन शुल्क कितना है?",
     "अनारक्षित प्रवर्गातील उमेदवारांसाठी अर्ज शुल्क किती आहे?"),
    ("E2", "grievance fee", "What is the fee for submitting a grievance application?",
     "शिकायत आवेदन जमा करने का शुल्क कितना है?", "तक्रार अर्ज सादर करण्यासाठी शुल्क किती आहे?"),
    ("F1", "OBC reservation pct", "What percentage of seats are reserved for the OBC category?",
     "ओबीसी श्रेणी के लिए कितने प्रतिशत सीटें आरक्षित हैं?",
     "ओबीसी प्रवर्गासाठी किती टक्के जागा राखीव आहेत?"),
    ("F2", "EWS reservation pct", "What percentage of seats are reserved for the EWS category?",
     "ईडब्ल्यूएस श्रेणी के लिए कितने प्रतिशत सीटें आरक्षित हैं?",
     "ईडब्ल्यूएस प्रवर्गासाठी किती टक्के जागा राखीव आहेत?"),
    ("F3", "PH reservation pct", "What percentage of seats are reserved for physically handicapped candidates?",
     "शारीरिक रूप से विकलांग उम्मीदवारों के लिए कितने प्रतिशत सीटें आरक्षित हैं?",
     "शारीरिकदृष्ट्या अपंग उमेदवारांसाठी किती टक्के जागा राखीव आहेत?"),
    ("G1", "admission rounds", "How many rounds are there in the admission process, and what happens in each one?",
     "प्रवेश प्रक्रिया में कितने राउंड होते हैं, और हर राउंड में क्या होता है?",
     "प्रवेश प्रक्रियेत किती फेऱ्या असतात, आणि प्रत्येक फेरीत काय होते?"),
    ("H1", "salary honesty", "What is the average starting salary after graduating from this course?",
     "इस कोर्स से स्नातक होने के बाद औसत शुरुआती वेतन क्या है?",
     "या अभ्यासक्रमातून पदवी घेतल्यानंतर सरासरी सुरुवातीचा पगार किती आहे?"),
    ("H2", "recruiters honesty", "Which private companies come for campus recruitment at this college?",
     "इस कॉलेज में कैंपस भर्ती के लिए कौन सी निजी कंपनियां आती हैं?",
     "या महाविद्यालयात कॅम्पस भरतीसाठी कोणत्या खाजगी कंपन्या येतात?"),
    ("H3", "sports scholarship honesty", "Is there a scholarship specifically for sports quota students?",
     "क्या स्पोर्ट्स कोटा छात्रों के लिए विशेष रूप से कोई छात्रवृत्ति है?",
     "स्पोर्ट्स कोटा विद्यार्थ्यांसाठी विशेष शिष्यवृत्ती आहे का?"),
]

LANGS = [("en", None), ("hi", "hi"), ("mr", "mr")]

for qid, cat, en, hi, mr in QUESTIONS:
    texts = {"en": en, "hi": hi, "mr": mr}
    for lang, ui_lang in LANGS:
        question = texts[lang]
        t0 = time.time()
        try:
            result = rag.answer("default", question, script_pref="auto", ui_language=ui_lang)
            dt = time.time() - t0
            print(f"### {qid} [{lang}] ({cat}) ###", flush=True)
            print(f"Q: {question}", flush=True)
            print(f"time={dt:.1f}s model={result['model']} pages={result['pages']}", flush=True)
            print(f"A: {result['answer']}", flush=True)
            print(flush=True)
        except Exception as e:
            print(f"### {qid} [{lang}] ({cat}) ### EXCEPTION: {e!r}", flush=True)
            print(flush=True)

print("ALL DONE", flush=True)
