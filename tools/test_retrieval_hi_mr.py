"""Quota-free accuracy harness for the Hindi/Marathi retrieval layer.

test_trust_hi_mr.py measures the finished answer, which costs one Sarvam call per
probe and so is capped at ~150 probes/day. This measures the two deterministic
stages that decide whether a correct answer is even POSSIBLE:

  RETRIEVAL  did the chunk containing the answer reach the top-K?
             If not, the model is being asked to answer from excerpts that do
             not contain the fact, and the honest outcome is a false "the
             prospectus doesn't specify" - the single most common failure in the
             scored runs.
  LOOKUP     for table facts, did tablelookup resolve the exact cell, and does
             the resolved descriptor survive the cross-language veto?

Neither stage calls the cloud model, so this runs unlimited times for free
(translation uses the local gemma2 via Ollama). That makes it the right loop for
iterating on retrieval: get this to ~100%, and the remaining end-to-end gap is
attributable to generation rather than plumbing.

Gold pages are taken from the ingested MAFSU B.V.Sc. & A.H. 2025-26 prospectus:
Annexure III-A/B/C for fees (p.39-41), Annexure XIV for the schedule (p.53),
sections 4/6 for eligibility and reservation, section 4 of Part II for
attendance and internship.

Usage:
  python tools/test_retrieval_hi_mr.py
  python tools/test_retrieval_hi_mr.py --lang mr
  python tools/test_retrieval_hi_mr.py --show-misses
"""

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, ".")
from backend import embeddings, faq, llm, projects, tablelookup, vectorstore  # noqa: E402
from backend import config  # noqa: E402

# (id, lang, question, gold_pages, expected_value_or_None)
#
# `expected` is set only for figures that SHOULD be resolvable from a linearized
# table. A probe with expected=None is a retrieval-only check - the fact is prose
# (eligibility wording, medium of instruction) and there is no cell to resolve.
PROBES = [
    # ---- fees: college table (Annexure III-A, p.39) ----
    ("tuition_1y", "hi", "पहले वर्ष की ट्यूशन फीस कितनी है?", {39}, "27500"),
    ("tuition_1y", "mr", "पहिल्या वर्षाची ट्यूशन फी किती आहे?", {39}, "27500"),
    ("tuition_4y", "hi", "चौथे वर्ष की ट्यूशन फीस कितनी है?", {39}, "41250"),
    ("tuition_4y", "mr", "चौथ्या वर्षाची ट्यूशन फी किती आहे?", {39}, "41250"),
    ("reg_1y", "hi", "पहले वर्ष का पंजीकरण शुल्क कितना है?", {39}, "1500"),
    ("reg_1y", "mr", "पहिल्या वर्षाची नोंदणी फी किती आहे?", {39}, "1500"),
    ("reg_4y", "hi", "चौथे वर्ष का पंजीकरण शुल्क कितना है?", {39}, "2200"),
    ("exam_1y", "hi", "पहले वर्ष की परीक्षा शुल्क कितनी है?", {39}, "6000"),
    ("exam_1y", "mr", "पहिल्या वर्षाची परीक्षा फी किती आहे?", {39}, "6000"),
    ("exam_4y", "mr", "चौथ्या वर्षाची परीक्षा फी किती आहे?", {39}, "9000"),
    ("internship_fee", "hi", "इंटर्नशिप शुल्क कितना है?", {39}, "24000"),
    ("internship_fee", "mr", "इंटर्नशिप फी किती आहे?", {39}, "24000"),
    ("caution_money", "hi", "कॉलेज कॉशन मनी कितनी है?", {39}, "3000"),
    ("grade_card", "mr", "ग्रेड कार्डसाठी किती फी आहे?", {39}, "250"),

    # ---- fees: totals and hostel (p.40) ----
    ("admission_open", "hi", "अनारक्षित वर्ग के लिए कुल प्रवेश शुल्क कितना है?", {40}, None),
    ("admission_open", "mr", "खुल्या प्रवर्गासाठी एकूण प्रवेश शुल्क किती आहे?", {40}, None),
    ("admission_reserved", "hi", "आरक्षित वर्ग के लिए प्रवेश शुल्क कितना है?", {40}, None),
    ("admission_reserved", "mr", "आरक्षित प्रवर्गासाठी प्रवेश शुल्क किती आहे?", {40}, None),
    ("hostel_nagpur_1y", "hi", "नागपुर में पहले वर्ष का कुल हॉस्टेल शुल्क कितना है?", {40}, "27300"),
    ("hostel_mumbai_1y", "mr", "मुंबईत पहिल्या वर्षाचे एकूण वसतिगृह शुल्क किती आहे?", {40}, "32250"),
    ("hostel_nagpur_4y", "hi", "नागपुर में चौथे वर्ष का कुल हॉस्टेल शुल्क कितना है?", {40}, "29700"),

    # ---- fees: NRI table (p.41) ----
    ("nri_special", "hi", "एनआरआई उम्मीदवारों के लिए विशेष शुल्क कितना है?", {25, 41}, None),
    ("nri_special", "mr", "एनआरआय उमेदवारांसाठी विशेष शुल्क किती आहे?", {25, 41}, None),
    ("nepal_aid", "hi", "नेपाल एड फंड के तहत कितना शुल्क देना होता है?", {25, 41}, None),

    # ---- eligibility (p.9, p.21) ----
    ("min_marks", "hi", "पात्रता के लिए बारहवीं में कम से कम कितने प्रतिशत अंक चाहिए?", {9}, None),
    ("min_marks", "mr", "पात्रतेसाठी बारावीत किमान किती टक्के गुण आवश्यक आहेत?", {9}, None),
    ("subjects", "hi", "बारहवीं में कौन से विषय अनिवार्य हैं?", {9}, None),
    ("subjects", "mr", "बारावीत कोणते विषय अनिवार्य आहेत?", {9}, None),
    ("entrance", "hi", "प्रवेश के लिए कौन सी प्रवेश परीक्षा आवश्यक है?", {9, 21}, None),
    ("entrance", "mr", "प्रवेशासाठी कोणती प्रवेश परीक्षा आवश्यक आहे?", {9, 21}, None),
    ("merit_basis", "mr", "अंतिम गुणवत्ता यादी कशाच्या आधारे तयार केली जाते?", {21, 27}, None),
    ("tie_break", "hi", "NEET में समान अंक होने पर मेरिट कैसे तय होती है?", {27}, None),

    # ---- reservation (p.15, p.18) ----
    ("agri_pct", "hi", "कृषक (Agriculturist) वर्ग के लिए कितने प्रतिशत सीटें आरक्षित हैं?", {15}, None),
    ("agri_pct", "mr", "शेतकरी प्रवर्गासाठी किती टक्के जागा राखीव आहेत?", {15}, None),
    ("ews_pct", "hi", "आर्थिक रूप से कमजोर वर्ग के लिए कितने प्रतिशत सीटें आरक्षित हैं?", {18}, None),
    ("ews_pct", "mr", "आर्थिक दुर्बल घटकासाठी किती टक्के जागा राखीव आहेत?", {18}, None),
    ("orphan_pct", "hi", "अनाथ उम्मीदवारों के लिए कितने प्रतिशत सीटें आरक्षित हैं?", {18}, None),
    ("orphan_pct", "mr", "अनाथ उमेदवारांसाठी किती टक्के जागा राखीव आहेत?", {18}, None),
    ("pap_pct", "mr", "प्रकल्पग्रस्त व्यक्तींसाठी किती टक्के जागा राखीव आहेत?", {15}, None),
    ("defence_pct", "hi", "रक्षा कर्मियों के लिए कितने प्रतिशत सीटें आरक्षित हैं?", {15}, None),

    # ---- schedule (Annexure XIV, p.53) ----
    ("form_available", "hi", "ऑनलाइन आवेदन पत्र कब से उपलब्ध होगा?", {53}, None),
    ("last_date_app", "hi", "ऑनलाइन आवेदन पत्र जमा करने की अंतिम तिथि क्या है?", {53}, None),
    ("last_date_app", "mr", "ऑनलाइन अर्ज सादर करण्याची अंतिम तारीख काय आहे?", {53}, None),
    ("prov_merit", "hi", "अस्थायी मेरिट सूची कब प्रदर्शित होगी?", {53}, None),
    ("prov_merit", "mr", "तात्पुरती गुणवत्ता यादी कधी जाहीर होणार आहे?", {53}, None),
    ("final_merit", "hi", "अंतिम मेरिट सूची कब प्रदर्शित होगी?", {53}, None),
    ("final_merit", "mr", "अंतिम गुणवत्ता यादी कधी जाहीर होईल?", {53}, None),
    ("grievance_last", "hi", "शिकायत आवेदन की अंतिम तिथि क्या है?", {53}, None),
    ("grievance_last", "mr", "तक्रार अर्जाची शेवटची तारीख काय आहे?", {53}, None),
    ("first_round", "mr", "पहिल्या फेरीची जागावाटप यादी कधी जाहीर होते?", {53}, None),

    # ---- documents (p.21-23, p.55) ----
    ("documents", "hi", "आवेदन के साथ कौन से दस्तावेज अपलोड करने होंगे?", {21, 22, 55}, None),
    ("documents", "mr", "अर्जासोबत कोणती कागदपत्रे अपलोड करावी लागतात?", {21, 22, 55}, None),
    ("cvc_deadline", "hi", "जाति वैधता प्रमाणपत्र कब तक जमा करना है?", {14, 22}, None),
    ("cvc_deadline", "mr", "जात वैधता प्रमाणपत्र सादर करण्याची शेवटची तारीख काय आहे?", {14, 22}, None),
    ("rejection", "mr", "अर्ज कोणत्या कारणांमुळे नाकारला जातो?", {23}, None),
    ("domicile", "hi", "अधिवास प्रमाणपत्र के लिए कितने साल का निवास आवश्यक है?", {55}, None),

    # ---- academics (p.30, p.32, p.34) ----
    ("attendance", "hi", "कक्षाओं में न्यूनतम कितनी उपस्थिति अनिवार्य है?", {32}, None),
    ("attendance", "mr", "वर्गांमध्ये किमान किती उपस्थिती आवश्यक आहे?", {32}, None),
    ("internship_dur", "hi", "इंटर्नशिप कितने महीने की होती है?", {32}, None),
    ("internship_dur", "mr", "इंटर्नशिप किती महिन्यांची असते?", {32}, None),
    ("refund_100", "hi", "प्रवेश रद्द करने पर 100% शुल्क वापसी कब मिलती है?", {30}, None),
    ("refund_100", "mr", "प्रवेश रद्द केल्यास १००% फी परतावा कधी मिळतो?", {30}, None),
    ("transfer_pct", "mr", "आंतरमहाविद्यालयीन बदलीची मर्यादा किती टक्के आहे?", {34}, None),
    ("medium", "hi", "शिक्षा का माध्यम कौन सा है?", {24}, None),
    ("medium", "mr", "शिक्षणाचे माध्यम कोणते आहे?", {24}, None),
    ("age_nri", "hi", "एनआरआई उम्मीदवारों के लिए न्यूनतम आयु क्या है?", {24}, None),
    ("goa_seats", "mr", "गोवा कोट्यातील किती जागा मुंबई महाविद्यालयात आहेत?", {12}, None),
    ("colleges", "hi", "इस विश्वविद्यालय के घटक कॉलेज कहाँ कहाँ हैं?", {9}, None),
]


def evaluate(probes, show_misses=False):
    store = vectorstore.load(projects.store_path(config.DEFAULT_PROJECT_ID))
    if not store:
        print("FATAL: no vector store for the default project - ingest a prospectus first.")
        return 1

    stats = {}
    misses = []
    lookup_ok = lookup_attempted = lookup_wrong = 0

    for probe_id, lang, question, gold, expected in probes:
        english = llm.translate_to_english(question, lang)
        vector = embeddings.embed([english])[0]
        top = vectorstore.search(store, vector, config.TOP_K, english)
        pages = {e["page"] for e in top}
        hit = bool(gold & pages)

        s = stats.setdefault(lang, {"hit": 0, "n": 0})
        s["hit"] += hit
        s["n"] += 1
        if not hit:
            misses.append((probe_id, lang, question, english, sorted(gold), sorted(pages)))

        if expected:
            lookup_attempted += 1
            resolved = tablelookup.lookup(english, top)
            # Mirror rag.py exactly: a descriptor contradicting the original
            # question is dropped rather than stated as verified.
            if resolved and not faq.compatible_questions(question, resolved["descriptor"]):
                resolved = None
            if resolved:
                if expected in str(resolved["value"]).replace(",", ""):
                    lookup_ok += 1
                else:
                    lookup_wrong += 1
                    misses.append((probe_id + " [LOOKUP]", lang, question, english,
                                   [expected], [resolved["value"], resolved["descriptor"]]))

    print("=" * 68)
    print("RETRIEVAL: gold page reached top-K")
    print("=" * 68)
    total_hit = total_n = 0
    for lang in ("hi", "mr"):
        if lang not in stats:
            continue
        s = stats[lang]
        total_hit += s["hit"]
        total_n += s["n"]
        print(f"  {lang}:  {s['hit']:3d}/{s['n']:3d} = {100*s['hit']/s['n']:5.1f}%")
    if total_n:
        print(f"  ALL: {total_hit:3d}/{total_n:3d} = {100*total_hit/total_n:5.1f}%")

    print()
    print("=" * 68)
    print("TABLE LOOKUP: exact cell resolved (and survived the veto)")
    print("=" * 68)
    if lookup_attempted:
        print(f"  resolved correctly : {lookup_ok:3d}/{lookup_attempted:3d} = "
              f"{100*lookup_ok/lookup_attempted:5.1f}%")
        print(f"  CONFIDENTLY WRONG  : {lookup_wrong:3d}   (must stay 0)")
        print(f"  vetoed/unresolved  : {lookup_attempted - lookup_ok - lookup_wrong:3d}"
              f"   (safe - falls back to normal RAG)")

    if misses:
        print()
        print("=" * 68)
        print(f"MISSES ({len(misses)})")
        print("=" * 68)
        for probe_id, lang, question, english, want, got in misses:
            print(f"  {probe_id} [{lang}]")
            print(f"     Q  : {question}")
            if show_misses:
                print(f"     EN : {english}")
            print(f"     want {want}   got {got}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["hi", "mr"], help="run only this language")
    ap.add_argument("--show-misses", action="store_true",
                    help="print the English translation for each miss (diagnoses "
                         "whether a miss is a translation fault or a ranking fault)")
    args = ap.parse_args()
    probes = [p for p in PROBES if not args.lang or p[1] == args.lang]
    print(f"{len(probes)} probes  |  TOP_K={config.TOP_K}  |  no cloud calls, unlimited reruns\n")
    return evaluate(probes, args.show_misses)


if __name__ == "__main__":
    sys.exit(main())
