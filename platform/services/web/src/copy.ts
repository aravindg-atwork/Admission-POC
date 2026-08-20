// UI copy per language. Machine-drafted for this checkpoint, not verified
// by a native Hindi/Marathi speaker yet - reasonable, standard admissions
// phrasing, but flag this file for a real review pass before it's ever
// shown to a real student. Every string here is written from the
// student's side of the screen (what they're doing, not what the system
// is doing) and in active voice, matching this product's own established
// tone (see backend/prompts/canned.py for the existing, already-reviewed
// voice this should eventually match).
import type { Language } from "./types";

export interface CheatSheetCategory {
  label: string;
  questions: string[];
}

export interface Copy {
  wordmark: string;
  tagline: string;
  greeting: string;
  subtext: string;
  chips: string[];
  placeholder: string;
  send: string;
  thinking: string;
  notLive: string;
  languageLabel: string;
  clearChat: string;
  cheatSheet: string;
  cheatSheetHint: string;
  copied: string;
  cheatSheetCategories: CheatSheetCategory[];
}

export const COPY: Record<Language, Copy> = {
  en: {
    wordmark: "MAFSU Admissions",
    tagline: "Ask anything about admission.",
    greeting: "Ask anything about admission.",
    subtext:
      "Grounded in MAFSU's own prospectus — B.V.Sc. & A.H., B.F.Sc., and B.Tech. (Dairy Technology).",
    chips: [
      "What are the eligibility criteria?",
      "What is the admission fee?",
      "Am I eligible?",
    ],
    placeholder: "Type your question…",
    send: "Ask",
    thinking: "Finding your answer…",
    notLive:
      "The admissions engine isn't connected yet — you're previewing the interface only.",
    languageLabel: "English",
    clearChat: "Clear chat",
    cheatSheet: "Common questions",
    cheatSheetHint: "Click a question to copy it.",
    copied: "Copied",
    cheatSheetCategories: [
      {
        label: "Programmes",
        questions: [
          "What programmes do you offer?",
          "What is the difference between B.V.Sc. and B.F.Sc.?",
        ],
      },
      {
        label: "Eligibility",
        questions: [
          "What is the eligibility criteria for B.V.Sc. & A.H.?",
          "What percentage do reserved-category candidates need?",
          "Do I need to appear for NEET or MHT-CET?",
        ],
      },
      {
        label: "Fees",
        questions: [
          "What is the admission fee for the first year?",
          "What is the refund policy if I withdraw?",
        ],
      },
      {
        label: "Dates & documents",
        questions: [
          "What documents do I need at the time of admission?",
          "What is the last date to apply?",
        ],
      },
      {
        label: "Seats & reservation",
        questions: [
          "How many seats are available?",
          "What are the reservation categories?",
        ],
      },
    ],
  },
  hi: {
    wordmark: "MAFSU प्रवेश",
    tagline: "प्रवेश के बारे में कुछ भी पूछें।",
    greeting: "प्रवेश के बारे में कुछ भी पूछें।",
    subtext:
      "MAFSU के अपने प्रॉस्पेक्टस पर आधारित — बी.व्ही.एससी. एवं ए.एच., बी.एफ.एससी., और बी.टेक. (डेयरी टेक्नोलॉजी)।",
    chips: ["पात्रता मानदंड क्या हैं?", "प्रवेश शुल्क कितना है?", "क्या मैं पात्र हूँ?"],
    placeholder: "अपना प्रश्न लिखें…",
    send: "पूछें",
    thinking: "आपका उत्तर खोजा जा रहा है…",
    notLive: "प्रवेश सहायक अभी जुड़ा नहीं है — यह केवल इंटरफ़ेस का पूर्वावलोकन है।",
    languageLabel: "हिन्दी",
    clearChat: "बातचीत साफ़ करें",
    cheatSheet: "सामान्य प्रश्न",
    cheatSheetHint: "प्रश्न कॉपी करने के लिए उस पर क्लिक करें।",
    copied: "कॉपी हो गया",
    cheatSheetCategories: [
      {
        label: "कार्यक्रम",
        questions: [
          "आप कौन से कार्यक्रम प्रदान करते हैं?",
          "बी.व्ही.एससी. और बी.एफ.एससी. में क्या अंतर है?",
        ],
      },
      {
        label: "पात्रता",
        questions: [
          "बी.व्ही.एससी. एवं ए.एच. के लिए पात्रता मानदंड क्या हैं?",
          "आरक्षित श्रेणी के उम्मीदवारों को कितने प्रतिशत की आवश्यकता है?",
          "क्या मुझे NEET या MHT-CET देनी होगी?",
        ],
      },
      {
        label: "शुल्क",
        questions: [
          "पहले वर्ष का प्रवेश शुल्क कितना है?",
          "यदि मैं प्रवेश वापस लेता हूँ तो धनवापसी नीति क्या है?",
        ],
      },
      {
        label: "तिथियाँ और दस्तावेज़",
        questions: [
          "प्रवेश के समय मुझे कौन से दस्तावेज़ चाहिए?",
          "आवेदन करने की अंतिम तिथि क्या है?",
        ],
      },
      {
        label: "सीटें और आरक्षण",
        questions: ["कितनी सीटें उपलब्ध हैं?", "आरक्षण श्रेणियाँ क्या हैं?"],
      },
    ],
  },
  mr: {
    wordmark: "MAFSU प्रवेश",
    tagline: "प्रवेशाबद्दल काहीही विचारा.",
    greeting: "प्रवेशाबद्दल काहीही विचारा.",
    subtext:
      "MAFSU च्या स्वतःच्या प्रॉस्पेक्टसवर आधारित — बी.व्ही.एससी. व ए.एच., बी.एफ.एससी., आणि बी.टेक. (डेअरी टेक्नॉलॉजी).",
    chips: ["पात्रता निकष काय आहेत?", "प्रवेश शुल्क किती आहे?", "मी पात्र आहे का?"],
    placeholder: "तुमचा प्रश्न लिहा…",
    send: "विचारा",
    thinking: "तुमचे उत्तर शोधले जात आहे…",
    notLive: "प्रवेश सहाय्यक अद्याप जोडलेला नाही — हे फक्त इंटरफेसचे पूर्वावलोकन आहे.",
    languageLabel: "मराठी",
    clearChat: "संभाषण साफ करा",
    cheatSheet: "सामान्य प्रश्न",
    cheatSheetHint: "प्रश्न कॉपी करण्यासाठी त्यावर क्लिक करा.",
    copied: "कॉपी झाले",
    cheatSheetCategories: [
      {
        label: "अभ्यासक्रम",
        questions: [
          "तुम्ही कोणते अभ्यासक्रम देता?",
          "बी.व्ही.एससी. आणि बी.एफ.एससी. मध्ये काय फरक आहे?",
        ],
      },
      {
        label: "पात्रता",
        questions: [
          "बी.व्ही.एससी. व ए.एच. साठी पात्रता निकष काय आहेत?",
          "राखीव प्रवर्गातील उमेदवारांना किती टक्के आवश्यक आहेत?",
          "मला NEET किंवा MHT-CET द्यावी लागेल का?",
        ],
      },
      {
        label: "शुल्क",
        questions: [
          "पहिल्या वर्षाचे प्रवेश शुल्क किती आहे?",
          "प्रवेश रद्द केल्यास परतावा धोरण काय आहे?",
        ],
      },
      {
        label: "तारखा व कागदपत्रे",
        questions: [
          "प्रवेशाच्या वेळी मला कोणती कागदपत्रे लागतील?",
          "अर्ज करण्याची शेवटची तारीख कोणती आहे?",
        ],
      },
      {
        label: "जागा व आरक्षण",
        questions: ["किती जागा उपलब्ध आहेत?", "आरक्षण प्रवर्ग काय आहेत?"],
      },
    ],
  },
};
