"""Seed the FAQ cache with the highest-stakes facts, in all three languages.

These are the questions a real admission rush asks most - fees, dates,
eligibility, reservation percentages - and a seeded answer has three properties
a fresh generation does not:

  DETERMINISTIC   the text is written here, not generated, so there is no
                  temperature/seed/translation path that could introduce drift
  PERMANENT       seeded entries are exempt from faq.py's pruning, so they
                  never age out the way an auto-cached answer can
  FREE            a cache hit skips the Sarvam call entirely - this also means
                  the daily 150-call cap is no longer spent on repeats of the
                  same ~20 facts

Every value below was cross-checked against the ingested prospectus via
backend.tablelookup (the same deterministic table-cell resolver rag.py uses) or
direct extraction from the Annexure text, NOT taken on the model's word - see
tools/test_retrieval_hi_mr.py, which verifies retrieval finds the right page for
each of these. The answer TEXT is hand-written to match SYSTEM_PROMPT_BASE's
style (lead with the fact, plain spoken prose, no markdown, no page citations in
the sentence - pages are attached separately) rather than generated, so seeding
never depends on the model getting the number right on the day it's run.

One entry per fact per language is enough - the cache matches on embedding
similarity (>=0.88 cosine) plus the discriminator check in faq.py, not exact
text, so a differently-phrased real question still hits a seeded entry as long
as it means the same thing (see faq.compatible_questions).

Usage:
  python tools/seed_faq.py               # seed against the running backend
  python tools/seed_faq.py --dry-run     # print the payload, seed nothing
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.environ.get("BACKEND_URL", "http://localhost:5050")
# Read from the environment like tools/test_matrix.py does. Hardcoding the
# default meant this script 401'd on any machine whose ADMIN_TOKEN had been
# changed in .env - and the failure comes after it prints "80 entries", so it
# reads like the seeding worked.
ADMIN = os.environ.get("ADMIN_TOKEN", "poc-admin-dev-token")
PROJECT = "default"

# Each row: (fact_id, pages, {"en": (question, answer), "hi": (...), "mr": (...)})
FACTS = [
    ("tuition_1y", [39], {
        "en": ("What is the tuition fee for the first year?",
               "The tuition fee for the first year is Rs. 27,500. It stays the "
               "same for the second and third years, then rises to Rs. 41,250 "
               "in the fourth year."),
        "hi": ("पहले वर्ष की ट्यूशन फीस कितनी है?",
               "पहले वर्ष की ट्यूशन फीस 27,500 रुपये है। यह दूसरे और तीसरे वर्ष में भी "
               "इतनी ही रहती है, और चौथे वर्ष में बढ़कर 41,250 रुपये हो जाती है।"),
        "mr": ("पहिल्या वर्षाची ट्यूशन फी किती आहे?",
               "पहिल्या वर्षाची ट्यूशन फी 27,500 रुपये आहे. ती दुसऱ्या आणि तिसऱ्या "
               "वर्षीही तेवढीच राहते, आणि चौथ्या वर्षी वाढून 41,250 रुपये होते."),
    }),
    ("registration_1y", [39], {
        "en": ("What is the registration fee for the first year?",
               "The registration fee for the first year is Rs. 1,500. It stays "
               "the same through the third year, then rises to Rs. 2,200 in "
               "the fourth year."),
        "hi": ("पहले वर्ष का पंजीकरण शुल्क कितना है?",
               "पहले वर्ष का पंजीकरण शुल्क 1,500 रुपये है। यह तीसरे वर्ष तक इतना ही "
               "रहता है, और चौथे वर्ष में बढ़कर 2,200 रुपये हो जाता है।"),
        "mr": ("पहिल्या वर्षाची नोंदणी फी किती आहे?",
               "पहिल्या वर्षाची नोंदणी फी 1,500 रुपये आहे. ती तिसऱ्या वर्षापर्यंत "
               "तेवढीच राहते, आणि चौथ्या वर्षी वाढून 2,200 रुपये होते."),
    }),
    ("exam_1y", [39], {
        "en": ("What is the examination fee for the first year?",
               "The examination fee for the first year is Rs. 6,000. It stays "
               "the same through the third year, rises to Rs. 9,000 in the "
               "fourth year, and is Rs. 6,000 again during the internship year."),
        "hi": ("पहले वर्ष की परीक्षा शुल्क कितनी है?",
               "पहले वर्ष की परीक्षा शुल्क 6,000 रुपये है। यह तीसरे वर्ष तक इतनी ही "
               "रहती है, चौथे वर्ष में बढ़कर 9,000 रुपये हो जाती है, और इंटर्नशिप वर्ष "
               "में फिर से 6,000 रुपये होती है।"),
        "mr": ("पहिल्या वर्षाची परीक्षा फी किती आहे?",
               "पहिल्या वर्षाची परीक्षा फी 6,000 रुपये आहे. ती तिसऱ्या वर्षापर्यंत "
               "तेवढीच राहते, चौथ्या वर्षी वाढून 9,000 रुपये होते, आणि इंटर्नशिप "
               "वर्षात पुन्हा 6,000 रुपये होते."),
    }),
    ("internship_fee", [39], {
        "en": ("What is the internship fee?",
               "The internship fee is Rs. 24,000, charged only during the "
               "internship year and not in any of the four academic years."),
        "hi": ("इंटर्नशिप शुल्क कितना है?",
               "इंटर्नशिप शुल्क 24,000 रुपये है, जो केवल इंटर्नशिप वर्ष में लिया जाता है, "
               "चारों शैक्षणिक वर्षों में नहीं।"),
        "mr": ("इंटर्नशिप फी किती आहे?",
               "इंटर्नशिप फी 24,000 रुपये आहे, जी फक्त इंटर्नशिपच्या वर्षात आकारली जाते, "
               "चारही शैक्षणिक वर्षांमध्ये नाही."),
    }),
    ("admission_unreserved", [40], {
        "en": ("What is the total admission fee for an unreserved category candidate?",
               "The total admission fee for an unreserved category candidate is "
               "Rs. 62,635. For a reserved category candidate it is lower, Rs. "
               "26,135, provided tuition, examination and library fees are "
               "received from the government."),
        "hi": ("अनारक्षित वर्ग के लिए कुल प्रवेश शुल्क कितना है?",
               "अनारक्षित वर्ग के उम्मीदवार के लिए कुल प्रवेश शुल्क 62,635 रुपये है। "
               "आरक्षित वर्ग के उम्मीदवारों के लिए यह कम, यानी 26,135 रुपये है, बशर्ते "
               "ट्यूशन, परीक्षा और लाइब्रेरी शुल्क सरकार द्वारा वहन किया जाए।"),
        "mr": ("खुल्या प्रवर्गासाठी एकूण प्रवेश शुल्क किती आहे?",
               "खुल्या प्रवर्गातील उमेदवारासाठी एकूण प्रवेश शुल्क 62,635 रुपये आहे. "
               "आरक्षित प्रवर्गातील उमेदवारांसाठी ते कमी, म्हणजे 26,135 रुपये आहे, अट "
               "अशी की ट्यूशन, परीक्षा आणि ग्रंथालय शुल्क सरकारकडून मिळत असेल."),
    }),
    ("admission_reserved", [40], {
        "en": ("What is the admission fee for a reserved category candidate?",
               "The admission fee for a reserved category candidate is Rs. "
               "26,135, lower than the unreserved fee of Rs. 62,635, provided "
               "tuition, examination and library fees are received from the "
               "government."),
        "hi": ("आरक्षित वर्ग के लिए प्रवेश शुल्क कितना है?",
               "आरक्षित वर्ग के उम्मीदवार के लिए प्रवेश शुल्क 26,135 रुपये है, जो "
               "अनारक्षित वर्ग के 62,635 रुपये से कम है, बशर्ते ट्यूशन, परीक्षा और "
               "लाइब्रेरी शुल्क सरकार द्वारा वहन किया जाए।"),
        "mr": ("आरक्षित प्रवर्गासाठी प्रवेश शुल्क किती आहे?",
               "आरक्षित प्रवर्गातील उमेदवारासाठी प्रवेश शुल्क 26,135 रुपये आहे, जे "
               "खुल्या प्रवर्गाच्या 62,635 रुपयांपेक्षा कमी आहे, अट अशी की ट्यूशन, "
               "परीक्षा आणि ग्रंथालय शुल्क सरकारकडून मिळत असेल."),
    }),
    ("hostel_nagpur_1y", [40], {
        "en": ("What is the total hostel fee for the first year at Nagpur?",
               "The total hostel fee for the first year at Nagpur is Rs. "
               "27,300, covering hostel charges plus maintenance, water and "
               "electricity together."),
        "hi": ("नागपुर में पहले वर्ष का कुल हॉस्टल शुल्क कितना है?",
               "नागपुर में पहले वर्ष का कुल हॉस्टल शुल्क 27,300 रुपये है, जिसमें "
               "हॉस्टल चार्ज तथा रखरखाव, पानी और बिजली शामिल हैं।"),
        "mr": ("नागपुरात पहिल्या वर्षाचे एकूण वसतिगृह शुल्क किती आहे?",
               "नागपूरमध्ये पहिल्या वर्षाचे एकूण वसतिगृह शुल्क 27,300 रुपये आहे, "
               "ज्यात वसतिगृह शुल्क तसेच देखभाल, पाणी आणि वीज यांचा समावेश आहे."),
    }),
    ("hostel_mumbai_1y", [40], {
        "en": ("What is the total hostel fee for the first year at Mumbai?",
               "The total hostel fee for the first year at Mumbai is Rs. "
               "32,250, higher than Nagpur's Rs. 27,300 because Mumbai's "
               "hostel charges are higher across the board."),
        "hi": ("मुंबई में पहले वर्ष का कुल हॉस्टल शुल्क कितना है?",
               "मुंबई में पहले वर्ष का कुल हॉस्टल शुल्क 32,250 रुपये है, जो नागपुर के "
               "27,300 रुपये से अधिक है क्योंकि मुंबई में हॉस्टल शुल्क समग्र रूप से "
               "अधिक हैं।"),
        "mr": ("मुंबईत पहिल्या वर्षाचे एकूण वसतिगृह शुल्क किती आहे?",
               "मुंबईत पहिल्या वर्षाचे एकूण वसतिगृह शुल्क 32,250 रुपये आहे, जे "
               "नागपूरच्या 27,300 रुपयांपेक्षा जास्त आहे कारण मुंबईतील वसतिगृह शुल्क "
               "एकूणच जास्त आहेत."),
    }),
    ("min_marks", [9], {
        "en": ("What is the minimum eligibility requirement in 12th standard?",
               "The minimum eligibility requirement is 50% marks in Physics, "
               "Chemistry, Biology or Biotechnology, and English combined, at "
               "the 12th standard or an equivalent qualifying examination."),
        "hi": ("पात्रता के लिए बारहवीं में कम से कम कितने प्रतिशत अंक चाहिए?",
               "पात्रता के लिए न्यूनतम आवश्यकता बारहवीं या समकक्ष परीक्षा में फिजिक्स, "
               "केमिस्ट्री, बायोलॉजी या बायोटेक्नोलॉजी, और इंग्लिश को मिलाकर कुल 50 "
               "प्रतिशत अंक है।"),
        "mr": ("पात्रतेसाठी बारावीत किमान किती टक्के गुण आवश्यक आहेत?",
               "पात्रतेसाठी किमान आवश्यकता म्हणजे बारावी किंवा समकक्ष परीक्षेत फिजिक्स, "
               "केमिस्ट्री, बायोलॉजी किंवा बायोटेक्नॉलॉजी, आणि इंग्रजी मिळून एकूण 50 "
               "टक्के गुण."),
    }),
    ("entrance_exam", [9, 21, 27], {
        "en": ("Which entrance exam is required for admission?",
               "NEET-UG-2025, the National Eligibility cum Entrance Test "
               "conducted by the National Testing Agency, is required for "
               "admission, and the final merit list is based on your "
               "qualifying score in it."),
        "hi": ("प्रवेश के लिए कौन सी प्रवेश परीक्षा आवश्यक है?",
               "प्रवेश के लिए NEET-UG-2025 यानी नेशनल टेस्टिंग एजेंसी द्वारा आयोजित "
               "नेशनल एलिजिबिलिटी कम एंट्रेंस टेस्ट आवश्यक है, और अंतिम मेरिट सूची इसी "
               "में आपके स्कोर के आधार पर बनती है।"),
        "mr": ("प्रवेशासाठी कोणती प्रवेश परीक्षा आवश्यक आहे?",
               "प्रवेशासाठी NEET-UG-2025, म्हणजे नॅशनल टेस्टिंग एजन्सीने घेतलेली "
               "नॅशनल एलिजिबिलिटी कम एंट्रन्स टेस्ट आवश्यक आहे, आणि अंतिम गुणवत्ता यादी "
               "याच परीक्षेतील तुमच्या गुणांवर आधारित तयार होते."),
    }),
    ("attendance", [32], {
        "en": ("What is the minimum attendance required in classes?",
               "A minimum of 75% attendance is mandatory in both theory and "
               "practical classes, tracked separately for each."),
        "hi": ("कक्षाओं में न्यूनतम कितनी उपस्थिति अनिवार्य है?",
               "सिद्धांत और व्यावहारिक दोनों कक्षाओं में अलग-अलग न्यूनतम 75 प्रतिशत "
               "उपस्थिति अनिवार्य है।"),
        "mr": ("वर्गांमध्ये किमान किती उपस्थिती आवश्यक आहे?",
               "सिद्धांत आणि प्रात्यक्षिक या दोन्ही वर्गांमध्ये स्वतंत्रपणे किमान 75 "
               "टक्के उपस्थिती अनिवार्य आहे."),
    }),
    ("medium", [24], {
        "en": ("What is the medium of instruction?",
               "The medium of instruction for the course is English."),
        "hi": ("शिक्षा का माध्यम कौन सा है?",
               "इस कोर्स के शिक्षण का माध्यम अंग्रेजी है।"),
        "mr": ("शिक्षणाचे माध्यम कोणते आहे?",
               "या अभ्यासक्रमाचे शिक्षणाचे माध्यम इंग्रजी आहे."),
    }),
    ("ews_pct", [18], {
        "en": ("What percentage of seats are reserved for the EWS category?",
               "Ten percent of seats are reserved for the Economically Weaker "
               "Section (EWS) category."),
        "hi": ("आर्थिक रूप से कमजोर वर्ग के लिए कितने प्रतिशत सीटें आरक्षित हैं?",
               "आर्थिक रूप से कमजोर वर्ग (EWS) के लिए 10 प्रतिशत सीटें आरक्षित हैं।"),
        "mr": ("आर्थिक दुर्बल घटकासाठी किती टक्के जागा राखीव आहेत?",
               "आर्थिक दुर्बल घटकासाठी (EWS) 10 टक्के जागा राखीव आहेत."),
    }),
    ("agri_pct", [15], {
        "en": ("What percentage of seats are reserved for the Agriculturist category?",
               "Six percent of seats are reserved under the Agriculturist "
               "category, part of the 14% total horizontal reservation that "
               "also covers freedom fighters, project-affected persons and "
               "defence personnel."),
        "hi": ("कृषक वर्ग के लिए कितने प्रतिशत सीटें आरक्षित हैं?",
               "कृषक (Agriculturist) वर्ग के लिए 6 प्रतिशत सीटें आरक्षित हैं, जो कुल "
               "14 प्रतिशत क्षैतिज आरक्षण का हिस्सा है, जिसमें स्वतंत्रता सेनानी, "
               "परियोजना प्रभावित व्यक्ति और रक्षा कर्मी भी शामिल हैं।"),
        "mr": ("शेतकरी प्रवर्गासाठी किती टक्के जागा राखीव आहेत?",
               "शेतकरी (Agriculturist) प्रवर्गासाठी 6 टक्के जागा राखीव आहेत, जो एकूण "
               "14 टक्के क्षैतिज आरक्षणाचा भाग आहे, ज्यात स्वातंत्र्यसैनिक, प्रकल्पग्रस्त "
               "व्यक्ती आणि संरक्षण कर्मचारीही समाविष्ट आहेत."),
    }),
    ("last_date_app", [53], {
        "en": ("What is the last date to submit the online application form?",
               "The last date to submit the online application form is 12th "
               "July 2025, though the form itself has been available online "
               "since 2nd July 2025."),
        "hi": ("ऑनलाइन आवेदन पत्र जमा करने की अंतिम तिथि क्या है?",
               "ऑनलाइन आवेदन पत्र जमा करने की अंतिम तिथि 12 जुलाई 2025 है, हालांकि "
               "ऑनलाइन फॉर्म 2 जुलाई 2025 से ही उपलब्ध है।"),
        "mr": ("ऑनलाइन अर्ज सादर करण्याची अंतिम तारीख काय आहे?",
               "ऑनलाइन अर्ज सादर करण्याची अंतिम तारीख 12 जुलै 2025 आहे, जरी ऑनलाइन "
               "फॉर्म 2 जुलै 2025 पासूनच उपलब्ध आहे."),
    }),
    ("prov_merit", [53], {
        "en": ("When will the provisional merit list be displayed?",
               "The provisional merit list will be displayed on 23rd July "
               "2025, and any grievance against it must be submitted by 25th "
               "July 2025."),
        "hi": ("अस्थायी मेरिट सूची कब प्रदर्शित होगी?",
               "अस्थायी मेरिट सूची 23 जुलाई 2025 को प्रदर्शित की जाएगी, और इसके "
               "खिलाफ शिकायत 25 जुलाई 2025 तक जमा करनी होगी।"),
        "mr": ("तात्पुरती गुणवत्ता यादी कधी जाहीर होणार आहे?",
               "तात्पुरती गुणवत्ता यादी 23 जुलै 2025 रोजी जाहीर केली जाईल, आणि "
               "याविरुद्ध तक्रार 25 जुलै 2025 पर्यंत सादर करावी लागेल."),
    }),
    ("final_merit", [53], {
        "en": ("When will the final merit list be displayed?",
               "The final merit list will be displayed on 31st July 2025, "
               "prepared after considering any grievances against the "
               "provisional list."),
        "hi": ("अंतिम मेरिट सूची कब प्रदर्शित होगी?",
               "अंतिम मेरिट सूची 31 जुलाई 2025 को प्रदर्शित की जाएगी, जो अस्थायी "
               "सूची के खिलाफ शिकायतों पर विचार करने के बाद तैयार की जाती है।"),
        "mr": ("अंतिम गुणवत्ता यादी कधी जाहीर होईल?",
               "अंतिम गुणवत्ता यादी 31 जुलै 2025 रोजी जाहीर केली जाईल, जी तात्पुरत्या "
               "यादीविरुद्धच्या तक्रारींचा विचार केल्यानंतर तयार केली जाते."),
    }),
    ("grievance_last", [53], {
        "en": ("What is the last date to submit a grievance application?",
               "The last date to submit a grievance application against the "
               "provisional merit list is 25th July 2025."),
        "hi": ("शिकायत आवेदन की अंतिम तिथि क्या है?",
               "अस्थायी मेरिट सूची के खिलाफ शिकायत आवेदन जमा करने की अंतिम तिथि 25 "
               "जुलाई 2025 है।"),
        "mr": ("तक्रार अर्जाची शेवटची तारीख काय आहे?",
               "तात्पुरत्या गुणवत्ता यादीविरुद्ध तक्रार अर्ज सादर करण्याची अंतिम "
               "तारीख 25 जुलै 2025 आहे."),
    }),
    ("cvc_deadline", [14, 22], {
        "en": ("What is the last date to submit the Caste Validity Certificate?",
               "Candidates claiming a reserved category benefit must submit "
               "their Caste Validity Certificate by 13th August 2025, or the "
               "provisional admission under that category will be cancelled."),
        "hi": ("जाति वैधता प्रमाणपत्र कब तक जमा करना है?",
               "आरक्षित वर्ग का लाभ लेने वाले उम्मीदवारों को जाति वैधता प्रमाणपत्र 13 "
               "अगस्त 2025 तक जमा करना होगा, अन्यथा उस वर्ग के तहत अस्थायी प्रवेश रद्द "
               "कर दिया जाएगा।"),
        "mr": ("जात वैधता प्रमाणपत्र सादर करण्याची शेवटची तारीख काय आहे?",
               "आरक्षित प्रवर्गाचा लाभ घेणाऱ्या उमेदवारांनी जात वैधता प्रमाणपत्र 13 "
               "ऑगस्ट 2025 पर्यंत सादर करणे आवश्यक आहे, अन्यथा त्या प्रवर्गांतर्गत "
               "तात्पुरता प्रवेश रद्द केला जाईल."),
    }),
    ("refund_100", [30], {
        "en": ("When do I get a 100% fee refund if I cancel my admission?",
               "You get a 100% refund of fees if you cancel your admission 15 "
               "days or more before the formally notified last date of "
               "admission. Cancelling less than 15 days before gets 90%, and "
               "up to 15 days after gets 80%."),
        "hi": ("प्रवेश रद्द करने पर 100% शुल्क वापसी कब मिलती है?",
               "यदि आप प्रवेश की औपचारिक रूप से घोषित अंतिम तिथि से 15 दिन या उससे "
               "अधिक पहले प्रवेश रद्द करते हैं, तो आपको 100 प्रतिशत शुल्क वापसी "
               "मिलती है। 15 दिन से कम पहले रद्द करने पर 90 प्रतिशत, और अंतिम तिथि के "
               "15 दिन बाद तक रद्द करने पर 80 प्रतिशत वापसी मिलती है।"),
        "mr": ("प्रवेश रद्द केल्यास १००% फी परतावा कधी मिळतो?",
               "प्रवेशाच्या औपचारिकपणे जाहीर केलेल्या शेवटच्या तारखेच्या 15 दिवस किंवा "
               "त्याहून आधी प्रवेश रद्द केल्यास तुम्हाला 100 टक्के फी परतावा मिळतो. 15 "
               "दिवसांपेक्षा कमी आधी रद्द केल्यास 90 टक्के, आणि शेवटच्या तारखेनंतर 15 "
               "दिवसांपर्यंत रद्द केल्यास 80 टक्के परतावा मिळतो."),
    }),
]


# Romanized (Hinglish/Marathinglish) phrasings of the highest-traffic facts.
# Discovered necessary by direct measurement, not assumption: a romanized
# paraphrase of a seeded fact NEVER hit the native-script entry above - cosine
# similarity between "mera pehle saal ka tuition fees kitna hai" and the seeded
# Devanagari question for the same fact measured 0.52, far under the 0.88 cache
# threshold, because the embedding model does not align Latin and Devanagari
# script closely enough (the same limitation retrieval already works around
# with a translation step - see rag.py). Mechanical transliteration of the
# Devanagari question was tried as a shortcut and rejected: it scored only 0.60
# against natural phrasing and garbled loanwords ("tuition fees" ->
# "tyuzana phisa"), so these are hand-written the same way the native versions
# are, not generated.
#
# Two independently-phrased romanized questions about the same fact DO cluster
# tightly (measured 0.934), so seeding one representative phrasing per fact is
# enough to catch real paraphrases - same reasoning as the native-script set.
#
# Reuses each fact's existing (answer, pages) - only the question form is new,
# so there is no new fact to verify, just a second way of asking for it.
ROMANIZED_VARIANTS = [
    ("tuition_1y", "hi", "pehle saal ki tuition fees kitni hai"),
    ("tuition_1y", "mr", "pahilya varshachi tuition fee kiti ahe"),
    ("admission_unreserved", "hi", "general category ke liye admission fee kitni hai"),
    ("admission_unreserved", "mr", "khulya prawargasathi admission fee kiti aste"),
    ("admission_reserved", "hi", "reserved category ke liye admission fee kitni hai"),
    ("admission_reserved", "mr", "reserved prawargasathi admission fee kiti aste"),
    ("min_marks", "hi", "12th mein kitne percent marks chahiye admission ke liye"),
    ("min_marks", "mr", "baravit kiti percent marks pahije admission sathi"),
    ("attendance", "hi", "class mein kitni attendance chahiye hoti hai"),
    ("attendance", "mr", "vargat kiti attendance lagto"),
    ("last_date_app", "hi", "online form bharne ki last date kya hai"),
    ("last_date_app", "mr", "online arj karaychi last date kadhi ahe"),
    ("entrance_exam", "hi", "is course ke liye kaunsi entrance exam deni padti hai"),
    ("entrance_exam", "mr", "ya course sathi konti entrance exam dyavi lagte"),
    ("cvc_deadline", "hi", "caste validity certificate kab tak submit karna hai"),
    ("cvc_deadline", "mr", "caste validity certificate kadhi paryant submit karaycha ahe"),
    ("refund_100", "hi", "admission cancel karne par 100 percent refund kab milta hai"),
    ("refund_100", "mr", "admission cancel kelyaver 100 percent refund kadhi milto"),
    ("hostel_nagpur_1y", "hi", "nagpur hostel ka pehle saal ka total kharcha kitna hai"),
    ("agri_pct", "mr", "shetkari quota madhe kiti percent seats aahet"),
]


def build_items():
    items = []
    by_fact = {fact_id: (pages, langs) for fact_id, pages, langs in FACTS}

    for fact_id, pages, langs in FACTS:
        for lang, (question, answer) in langs.items():
            items.append({
                "question": question,
                "answer": answer,
                "pages": pages,
                # Matches the tag shape rag.py stores on fresh entries
                # (cache_tags = {"ui_language": ui_language, ...}) so seeded
                # entries interoperate with the same cross-language collision
                # guard real traffic gets - a Hindi and Marathi entry for the
                # same fact never satisfy each other's lookup.
                "tags": {"ui_language": lang},
            })

    for fact_id, lang, romanized_question in ROMANIZED_VARIANTS:
        pages, langs = by_fact[fact_id]
        _, answer = langs[lang]
        items.append({
            "question": romanized_question,
            "answer": answer,
            "pages": pages,
            "tags": {"ui_language": lang},
        })
    return items


def req(method, path, headers=None, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    items = build_items()
    print(f"{len(FACTS)} facts x up to 3 languages = {len(items)} entries")

    if args.dry_run:
        print(json.dumps(items[:2], ensure_ascii=False, indent=2))
        return 0

    status, result = req("POST", f"/admin/projects/{PROJECT}/cache/seed",
                         {"X-Admin-Token": ADMIN}, {"items": items})
    if status != 200:
        print(f"FAILED: status={status} {result}")
        return 1
    print(f"Seeded {result.get('seeded')} entries into project {PROJECT!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
