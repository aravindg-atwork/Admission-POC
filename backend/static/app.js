// React, ReactDOM and htm are provided as globals by the vendored UMD scripts
// (see index.html). No bundler, no ESM/CDN - works offline and in locked-down envs.
const { useState, useRef, useEffect, useCallback } = React;
const createRoot = ReactDOM.createRoot;
const html = htm.bind(React.createElement);

// The admission site's own widget key is injected by the server; fall back to a
// meta tag or empty (the console's "Try It" sets its own).
const DEFAULT_API_KEY = window.ADMISSION_API_KEY ||
  (document.querySelector('meta[name="api-key"]') || {}).content || "";

// Every degree program's own widget key (see server.py's _serve_index) - used
// when the student resolves a program-clarification prompt by clicking an
// option, so the rest of the session switches to that program's own project
// instead of continuing to ask the default (B.V.Sc.) project about it. Empty
// on any page that doesn't inject it (e.g. the admin console's "Try It" tester).
const PROGRAMS = window.MAFSU_PROGRAMS || [];

// Start-screen language picker. English has no script step (Latin is its only
// script); Hindi/Marathi/Tamil each show a short example so the student can see
// what "native script" vs "Latin/romanized" actually looks like before picking,
// rather than guessing what the words mean.
const LANGUAGE_OPTIONS = [
  { code: "en", label: "English", sub: "English" },
  { code: "hi", label: "हिंदी", sub: "Hindi" },
  { code: "mr", label: "मराठी", sub: "Marathi" },
  { code: "ta", label: "தமிழ்", sub: "Tamil" },
];
const SCRIPT_EXAMPLES = {
  hi: { native: "प्रवेश की फ़ीस कितनी है?", latin: "Pravesh ki fees kitni hai?" },
  mr: { native: "प्रवेशासाठी फी किती आहे?", latin: "Praveshasathi fee kiti ahe?" },
  ta: { native: "சேர்க்கைக் கட்டணம் எவ்வளவு?", latin: "Serkkai kattanam evvalavu?" },
};
const LANG_TO_CODE = { en: "en-IN", hi: "hi-IN", mr: "mr-IN", ta: "ta-IN" };
const LANG_PREF_KEY = "admission-lang-pref";

function loadLangPref() {
  try {
    const raw = JSON.parse(localStorage.getItem(LANG_PREF_KEY));
    if (raw && LANG_TO_CODE[raw.lang] && (raw.lang === "en" || raw.script === "native" || raw.script === "latin")) {
      return raw;
    }
  } catch {}
  return null;
}
function saveLangPref(pref) {
  try { localStorage.setItem(LANG_PREF_KEY, JSON.stringify(pref)); } catch {}
}

// Empty-state introduction, in the language currently selected. This is the
// first thing a prospective student sees, and it's the only place the assistant
// gets to say what it actually is before being asked something. Keeping it in
// English while the selector says मराठी asks the student to take the language
// support on trust; showing the invitation, the explanation and the starter
// questions in their own script demonstrates it instead.
//
// The three starters double as the opening move in a walkthrough - each one is
// answerable from the prospectus and shows a different shape of answer (a
// criteria list, a single date, a document list).
const WELCOME = {
  en: {
    title: "Ask anything about admissions",
    body: "I'm an AI assistant for B.V.Sc. & A.H. admissions. I answer from the official prospectus - in English, Hindi, Marathi or Tamil - and show the page each answer came from.",
    chips: [
      "What are the eligibility criteria for admission?",
      "When is the last date to apply?",
      "What documents are required at admission?",
    ],
    placeholder: "Ask about admissions…",
  },
  hi: {
    title: "प्रवेश से जुड़ा कुछ भी पूछिए",
    body: "मैं B.V.Sc. & A.H. प्रवेश के लिए एक AI सहायक हूँ। मैं आधिकारिक प्रॉस्पेक्टस से जवाब देता हूँ - हिंदी, मराठी, तमिल या अंग्रेज़ी में - और हर जवाब के साथ प्रॉस्पेक्टस का पेज नंबर भी दिखाता हूँ।",
    chips: [
      "प्रवेश के लिए पात्रता मानदंड क्या हैं?",
      "आवेदन की अंतिम तिथि क्या है?",
      "प्रवेश के समय कौन से दस्तावेज़ चाहिए?",
    ],
    placeholder: "प्रवेश के बारे में पूछिए…",
  },
  mr: {
    title: "प्रवेशाबद्दल काहीही विचारा",
    body: "मी B.V.Sc. & A.H. प्रवेशासाठी एक AI सहाय्यक आहे. मी अधिकृत प्रॉस्पेक्टसमधून उत्तरे देतो - मराठी, हिंदी, तमिळ किंवा इंग्रजीत - आणि प्रत्येक उत्तरासोबत प्रॉस्पेक्टसचा पान क्रमांक दाखवतो.",
    chips: [
      "प्रवेशासाठी पात्रता निकष काय आहेत?",
      "अर्ज करण्याची शेवटची तारीख कधी आहे?",
      "प्रवेशासाठी कोणती कागदपत्रे लागतात?",
    ],
    placeholder: "प्रवेशाबद्दल विचारा…",
  },
  ta: {
    title: "சேர்க்கை குறித்து எதையும் கேளுங்கள்",
    body: "நான் B.V.Sc. & A.H. சேர்க்கைக்கான AI உதவியாளர். அதிகாரப்பூர்வ ப்ராஸ்பெக்டஸிலிருந்து - தமிழ், ஹிந்தி, மராத்தி அல்லது ஆங்கிலத்தில் - பதிலளிக்கிறேன், ஒவ்வொரு பதிலுக்கும் பக்க எண்ணையும் காட்டுகிறேன்.",
    chips: [
      "சேர்க்கைக்கான தகுதி நிபந்தனைகள் என்ன?",
      "விண்ணப்பிக்க கடைசி தேதி எப்போது?",
      "சேர்க்கைக்கு என்ன ஆவணங்கள் தேவை?",
    ],
    placeholder: "சேர்க்கை பற்றி கேளுங்கள்…",
  }
};

// Demo/copy-paste library for showing the assistant off - grouped so a demo can
// jump straight to "here's Hindi", "here's Hinglish", "here's a payment issue",
// etc. Not exhaustive coverage of the prospectus, just a broad, realistic spread.
const DEMO_QUESTIONS = [
  {
    label: "English",
    items: [
      "What are the eligibility criteria for admission?",
      "How many marks do I need in NEET-UG for admission?",
      "What documents are required for admission?",
      "When is the last date to apply?",
      "What is the application fee?",
      "What is the admission fee for the unreserved category?",
      "Is hostel accommodation available?",
      "What are the hostel fees?",
      "Where are the colleges located?",
      "When will the provisional merit list be released?",
      "How do I file a grievance about the merit list?",
      "Are there separate seats for NRI candidates?",
      "What is the refund policy if I cancel my admission?",
      "Can I transfer to another veterinary college later?",
    ],
  },
  {
    label: "हिंदी (Hindi, native script)",
    items: [
      "प्रवेश के लिए पात्रता मानदंड क्या हैं?",
      "NEET-UG में प्रवेश के लिए कितने अंक चाहिए?",
      "मुझे कौन से दस्तावेज़ चाहिए?",
      "आवेदन की अंतिम तिथि क्या है?",
      "आवेदन शुल्क कितना है?",
      "छात्रावास की सुविधा उपलब्ध है क्या?",
      "कॉलेज कहाँ स्थित हैं?",
      "मेरिट लिस्ट कब आएगी?",
      "शिकायत कैसे दर्ज करें?",
      "क्या NRI उम्मीदवारों के लिए अलग सीटें हैं?",
      "प्रवेश रद्द करने पर पैसे वापस मिलेंगे क्या?",
    ],
  },
  {
    label: "Hindi (Hinglish, romanized)",
    items: [
      "Eligibility criteria kya hai admission ke liye?",
      "NEET mein kitne marks chahiye?",
      "Mera pass kya kya documents hona chahiye?",
      "Apply karne ki last date kab hai?",
      "Application fees kitni hai?",
      "Hostel milega kya?",
      "College kahan hai bata do",
      "Merit list kab aayegi?",
      "Complaint kaise karu grievance ke liye?",
      "NRI candidates ke liye alag seats hai kya?",
      "Admission cancel karne par refund milega kya?",
    ],
  },
  {
    label: "मराठी (Marathi, native script)",
    items: [
      "प्रवेशासाठी पात्रता निकष काय आहेत?",
      "NEET मध्ये प्रवेशासाठी किती गुण लागतात?",
      "मला कोणती कागदपत्रे लागतील?",
      "अर्ज करण्याची शेवटची तारीख कधी आहे?",
      "अर्ज शुल्क किती आहे?",
      "वसतिगृहाची सोय उपलब्ध आहे का?",
      "महाविद्यालये कुठे आहेत?",
      "गुणवत्ता यादी कधी जाहीर होईल?",
      "तक्रार कशी नोंदवायची?",
      "NRI उमेदवारांसाठी वेगळ्या जागा आहेत का?",
    ],
  },
  {
    label: "Marathi (Marathinglish, romanized)",
    items: [
      "Praveshasathi patrata nikash kay ahet?",
      "NEET madhe kiti marks lagtat?",
      "Mala konti kagadpatra lagtil?",
      "Arj karaychi last date kadhi ahe?",
      "Fee kiti ahe?",
      "Hostel ahe ka?",
      "College kuthe ahe?",
      "Merit list kadhi yeil?",
      "Takrar kashi karaychi?",
      "NRI umedwaransathi vegli seat ahe ka?",
    ],
  },
  {
    label: "Payment issues (all languages)",
    items: [
      "I paid the application fee but the payment shows failed. What should I do?",
      "Amount was deducted twice for the application fee, how do I get a refund?",
      "Payment gateway showed an error but my bank shows the amount debited.",
      "Mera payment fail ho gaya aur paise kat gaye, ab kya karu?",
      "Fee payment ke baad bhi application status update nahi hua",
      "पैसे कट गए लेकिन कन्फर्मेशन नहीं मिला, क्या करूं?",
      "मी पेमेंट केले पण अर्जावर दिसत नाहीये, मी काय करू?",
      "Payment successful zaala pan receipt nahi ali",
    ],
  },
];

const Icon = {
  send: html`<svg viewBox="0 0 20 20" width="18" height="18" fill="none"><path d="M3 10L17 3L11.5 17L9.5 11L3 10Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`,
  mic: html`<svg viewBox="0 0 20 20" width="18" height="18" fill="none"><rect x="7.5" y="2.5" width="5" height="9" rx="2.5" fill="currentColor"/><path d="M5 9a5 5 0 0 0 10 0M10 14v3M7.5 17h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  speaker: html`<svg viewBox="0 0 20 20" width="17" height="17" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6M16 5c2 2 2 8 0 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`,
  play: html`<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>`,
  clear: html`<svg viewBox="0 0 20 20" width="17" height="17" fill="none"><path d="M4 6h12M8 6V4.5a1 1 0 011-1h2a1 1 0 011 1V6m-7 0 .6 9.4a1 1 0 001 .94h5.8a1 1 0 001-.94L14.5 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  list: html`<svg viewBox="0 0 20 20" width="17" height="17" fill="none"><path d="M7 5h9M7 10h9M7 15h9M3.5 5h.01M3.5 10h.01M3.5 15h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
  copy: html`<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><rect x="7" y="7" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.4"/><path d="M13 7V5.5A1.5 1.5 0 0011.5 4h-7A1.5 1.5 0 003 5.5v7A1.5 1.5 0 004.5 14H6" stroke="currentColor" stroke-width="1.4"/></svg>`,
  check: html`<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M4 10.5l4 4 8-9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  close: html`<svg viewBox="0 0 20 20" width="16" height="16" fill="none"><path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>`,
  thumbUp: html`<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M7 8.5V16h7.2c.7 0 1.3-.5 1.4-1.2l.9-5A1.5 1.5 0 0015 8H11.5l.6-3.2c.15-.8-.5-1.5-1.3-1.5-.4 0-.8.25-1 .6L7 8.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M4 8.5h3V16H4z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>`,
  thumbDown: html`<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M13 11.5V4H5.8c-.7 0-1.3.5-1.4 1.2l-.9 5A1.5 1.5 0 005 12h3.5l-.6 3.2c-.15.8.5 1.5 1.3 1.5.4 0 .8-.25 1-.6L13 11.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M16 11.5h-3V4h3z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>`,
};

// Voice input records audio and sends it to /api/stt (Mistral Voxtral)
// rather than relying on the browser's own recogniser. webkitSpeechRecognition
// is Chrome-only, silently missing in Firefox and most in-app webviews, and
// ships the student's audio to Google instead of to us - so a large share of
// students simply had no mic at all. MediaRecorder is available essentially
// everywhere.
//
// The browser recogniser is kept as a fallback for when MediaRecorder or the
// microphone is unavailable, so nobody who has voice input today loses it.
function useSpeech() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recRef = useRef(null);
  const mediaRef = useRef(null);
  useEffect(() => {
    if (!SR) return;
    const r = new SR();
    r.interimResults = false;
    r.maxAlternatives = 1;
    recRef.current = r;
  }, []);
  const canRecord = !!(navigator.mediaDevices && window.MediaRecorder);
  return { supported: canRecord || !!SR, rec: recRef, media: mediaRef, canRecord };
}

// Records until stop() is called, then posts the blob to /api/stt. Resolves
// with the transcript, or null on any failure - a failed transcription must
// leave the student able to type, never surface as a broken page.
async function recordAndTranscribe(mediaRef, apiKey, language, onStart) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const chunks = [];
  const mr = new MediaRecorder(stream);
  mediaRef.current = mr;
  mr.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
  const done = new Promise((resolve) => { mr.onstop = resolve; });
  mr.start();
  onStart && onStart();
  await done;
  stream.getTracks().forEach((t) => t.stop());
  mediaRef.current = null;
  if (!chunks.length) return null;
  const blob = new Blob(chunks, { type: chunks[0].type || "audio/webm" });
  try {
    const res = await fetch("/api/stt", {
      method: "POST",
      headers: {
        "Content-Type": blob.type,
        "X-Audio-Language": language || "en",
        ...(apiKey ? { "X-API-Key": apiKey } : {}),
      },
      body: blob,
    });
    if (!res.ok) return null;
    return (await res.json()).text || null;
  } catch {
    return null;
  }
}

// Indic languages get the self-hosted AI4Bharat voice (natural, not robotic).
// English stays on the instant browser voice - no reason to wait on a model for it.
//
// The Indic voice takes 20-50s+ to generate (CPU inference for a 0.9B model), and
// browsers block audio.play() once too much time has passed since the user's last
// interaction ("user activation" expires) - so autoplaying it after that delay is
// unreliable even for real users, not just automated testing. The fix: generate the
// audio in the background as soon as the answer arrives, but never call .play()
// until the user taps the button themselves - a fresh click always satisfies the
// browser's autoplay policy.
const TTS_LANG_MAP = { "hi-IN": "hi", "mr-IN": "mr", "ta-IN": "ta", "en-IN": "en" };
let currentAudio = null;
let msgIdSeq = 0;
const nextId = () => ++msgIdSeq;

function stopSpeaking() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

// Safety net matching backend/textclean.py: strips markdown noise (asterisks,
// bullet dashes, stray blank lines) so the browser voice doesn't read out symbols.
function cleanForSpeech(text) {
  return text
    .replace(/[*_`#]+/g, "")
    .replace(/^\s*[-•]\s+/gm, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\n/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function speakBrowserNow(rawText, lang) {
  stopSpeaking();
  if (!window.speechSynthesis) return;
  const text = cleanForSpeech(rawText);
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang;
  // Browsers don't expose a real gender field, only naming hints - prefer one
  // that says "female" for consistency with the Indic voices, fall back to any
  // voice for the language.
  const voices = window.speechSynthesis.getVoices().filter((x) => x.lang === lang);
  const v = voices.find((x) => /female/i.test(x.name)) || voices[0];
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}

function playUrl(url) {
  stopSpeaking();
  currentAudio = new Audio(url);
  currentAudio.play().catch(() => {});
}

async function fetchIndicAudio(text, shortLang, apiKey) {
  const res = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}) },
    body: JSON.stringify({ text, language: shortLang }),
  });
  if (!res.ok) throw new Error(String(res.status));
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

// Display-only formatting - never touches the underlying answer text used
// for TTS (onReplayBrowser/fetchIndicAudio both read m.text directly,
// unaffected by anything here). The backend prompt (rag.py's
// SYSTEM_PROMPT_BASE) deliberately still bans markdown SYNTAX in the
// model's own output - asterisks, bullet markers, numbered markers -
// because those read as literal noise to TTS ("star star", "dash"). What
// changed 2026-08-12 is the model is now allowed to put genuinely
// multi-item content on separate lines (a plain line break, TTS-safe -
// clean_for_speech already converts it to a natural pause, not a spoken
// word) instead of forcing everything into one run-on sentence - this
// formatter is what turns that line structure into properly spaced
// paragraphs, and adds bold emphasis on currency/percentage figures via a
// DISPLAY-only regex pass that never modifies m.text itself.
// Currency (Rs./₹ prefixed), percentages, and bare large numbers (4+
// digits, or any comma-grouped number) - the last branch matters because
// the deterministic verified-fact path (rag.py's tablelookup) often states
// a raw figure with no "Rs." prefix at all ("The first year tuition fee is
// 27500"), which the first two branches alone would miss entirely.
const _KEY_FIGURE_RE = /((?:Rs\.?|₹)\s?[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?\s?%|\b\d{1,3}(?:,\d{2,3})+\b|\b\d{4,}\b)/g;

function _boldKeyFigures(text, keyPrefix) {
  const parts = text.split(_KEY_FIGURE_RE);
  if (parts.length === 1) return text;
  return parts.map((part, i) => (i % 2 === 1
    ? html`<strong key=${`${keyPrefix}-${i}`}>${part}</strong>`
    : part));
}

function formatAnswer(text) {
  const paragraphs = (text || "").split(/\n+/).map((p) => p.trim()).filter(Boolean);
  if (paragraphs.length <= 1) return _boldKeyFigures(text || "", "kf");
  return paragraphs.map((para, i) => html`
    <p key=${i} class="answer-para">${_boldKeyFigures(para, `p${i}`)}</p>`);
}

// The stages a student is shown, in pipeline order. Deliberately a FIXED
// list rather than one row per event received: a stage that has not happened
// yet is shown as pending, which is a promise about the pipeline's shape (it
// always runs in this order), not a claim that any work has been done.
//
// Progress is monotonic - an event for stage N marks every earlier stage
// complete too. That is what keeps the display truthful when a step emits
// nothing: "routing" only records an event when there is a routing DECISION
// to record, so waiting for it individually would leave the first row
// spinning forever on the many questions that never need one. Retrieval
// starting is itself proof that understanding finished.
// Longest the question will wait for the progress stream to confirm it is
// subscribed. Local, so it normally resolves in single-digit milliseconds;
// this only bounds the case where /api/progress is slow or unreachable, and
// expiring it costs the student nothing but the animation.
const PROGRESS_READY_MS = 1200;

const PROGRESS_STAGES = [
  { step: "routing", label: "Understanding your question" },
  { step: "retrieval", label: "Searching the prospectus" },
  { step: "table_lookup", label: "Checking the tables" },
  { step: "generation", label: "Writing your answer" },
  { step: "validation", label: "Double-checking the details" },
];

function newTraceId() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "");
  const b = new Uint8Array(16);
  (window.crypto || {}).getRandomValues?.(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}

// Reads /api/progress with fetch + a stream reader rather than EventSource,
// because EventSource cannot send headers - it would have forced the API key
// into the URL query string, and from there into access logs and browser
// history. Resolves `ready` once the server confirms it is subscribed, so the
// caller can hold the question back until the stream cannot miss its start.
async function openProgress(traceId, apiKey, onStep) {
  const res = await fetch(`/api/progress?traceId=${traceId}`, {
    headers: { ...(apiKey ? { "X-API-Key": apiKey } : {}) },
  });
  if (!res.ok || !res.body) throw new Error(`progress ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let markReady;
  const ready = new Promise((resolve) => { markReady = resolve; });
  (async () => {
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          const line = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;                       // heartbeat comment
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }
          if (event.step === "ready") markReady();
          else onStep(event);
        }
      }
    } catch {
      // A dropped progress stream must never surface as a failed question.
    } finally {
      markReady();
    }
  })();
  return { ready, cancel: () => reader.cancel().catch(() => {}) };
}

function StageBadge({ state, index }) {
  if (state === "done")
    return html`<span class="stage-badge done"><svg viewBox="0 0 24 24" width="13" height="13"
      fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"
      stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg></span>`;
  if (state === "active")
    return html`<span class="stage-badge active"><span class="stage-ring"></span>${index + 1}</span>`;
  return html`<span class="stage-badge pending">${index + 1}</span>`;
}

function ProgressRows({ reached, details }) {
  return html`<div class="stage-list">
    ${PROGRESS_STAGES.map((stage, i) => {
      const state = i <= reached ? "done" : i === reached + 1 ? "active" : "pending";
      const detail = details[stage.step];
      return html`<div key=${stage.step} class="stage-row ${state}"
                       style=${{ animationDelay: `${i * 70}ms` }}>
        <${StageBadge} state=${state} index=${i} />
        <span class="stage-label">${stage.label}</span>
        ${detail ? html`<span class="stage-detail">${detail}</span>` : null}
      </div>`;
    })}
  </div>`;
}

function Message({ m, lang, onReplayBrowser, onPickProgram, onPickScope, onFeedback }) {
  if (m.role === "user")
    return html`<div class="row user"><div class="bubble">${m.text}</div></div>`;
  if (m.role === "thinking")
    return html`<div class="row bot"><div class="bubble ${m.reached >= 0 ? "thinking-wide" : ""}">
      ${m.reached >= 0
        ? html`<${ProgressRows} reached=${m.reached} details=${m.details || {}} />`
        : html`<span class="dots"><i></i><i></i><i></i></span>`}
    </div></div>`;
  if (m.role === "error")
    return html`<div class="row bot err"><div class="bubble">${m.text}</div></div>`;

  // Program-clarification prompt: no audio/source controls, just the
  // question and one chip per program - clicking resubmits the original
  // question (see App.send's keyOverride) under that program's own key.
  if (m.clarifyOptions) {
    return html`
      <div class="row bot">
        <div>
          <div class="bubble">${m.text}</div>
          <div class="chips">
            ${m.clarifyOptions.map((o) => html`
              <button class="chip" key=${o.projectId}
                      onClick=${() => onPickProgram(o.projectId, m.originalQuestion)}>
                ${o.label}
              </button>`)}
          </div>
        </div>
      </div>`;
  }

  // Percentage-scope clarification: two quick-pick chips next to the SAME
  // always-on textarea (see the composer in App below - never disabled by a
  // clarification), so clicking is a shortcut rather than the only way to
  // answer. Clicking sends the exact fixed text a typed answer would use
  // (o.value), so both paths resolve through the identical server-side
  // is_bare_scope_reply check - see chat_routes.py's pendingClarification
  // handling and core/eligibility.py's docstrings for why.
  if (m.scopeOptions) {
    return html`
      <div class="row bot">
        <div>
          <div class="bubble">${m.text}</div>
          <div class="chips">
            ${m.scopeOptions.map((o) => html`
              <button class="chip" key=${o.value}
                      onClick=${() => onPickScope(o.value, m.carryQuestion)}>
                ${o.label}
              </button>`)}
          </div>
        </div>
      </div>`;
  }

  const srcPill = m.source === "faq-cache"
    ? html`<span class="pill cache" title="Answered instantly from cache">⚡ instant</span>`
    : m.model ? html`<span class="pill src">${m.model.replace("sarvam:", "")}</span>` : null;
  // Set only when the default (B.V.Sc.) widget answered by redirecting to
  // another program's own data because the question named it explicitly
  // (see rag.py's needs_program_clarification path) - a small label so it's
  // clear which program the answer actually came from, since the widget
  // itself didn't switch context the way a clicked clarification chip does.
  const programPill = m.answeredForProgram
    ? html`<span class="pill program" title="Answered from this program's own prospectus">${m.answeredForProgram.label}</span>`
    : null;
  // A comparison answer pulled from several programs at once (see rag.py's
  // needs_comparison path) - one pill per program so it's clear which ones
  // were actually consulted, same reasoning as programPill above.
  const comparisonPills = m.comparedPrograms && m.comparedPrograms.length
    ? m.comparedPrograms.map((p) => html`<span class="pill program" key=${p.projectId} title="Included in this comparison">${p.label}</span>`)
    : null;

  const state = m.audioState;
  const title = state === "generating" ? "Generating natural voice…"
    : state === "ready" ? "Play natural voice"
    : state === "error" ? "Natural voice unavailable — tap for device voice"
    : state === "unspeakable" ? "Voice unavailable for romanized text — switch to native script for audio"
    : "Read aloud";

  const handleClick = () => {
    if (state === "unspeakable") return;
    if (state === "ready" && m.audioUrl) playUrl(m.audioUrl);
    else if (state !== "generating") onReplayBrowser(m.text);
  };

  return html`
    <div class="row bot">
      <div>
        <div class="bubble">${formatAnswer(m.text)}</div>
        <div class="meta">
          ${programPill}
          ${comparisonPills}
          ${/* Page pills removed 2026-08-13: a row of "p. 5 p. 9 p. 13..."
                under every answer read as homework - the student is here
                because reading the PDF didn't work. Pages are still returned
                by the API and still carried on the message, and the exact
                page AND line get quoted when a student challenges an answer
                (see the backend's cite-source path), which is where a
                citation actually earns its place. */ ""}
          ${srcPill}
          <button class=${"mini-btn" + (state === "ready" ? " on" : "")} title=${title}
                  disabled=${state === "generating" || state === "unspeakable"} onClick=${handleClick}>
            ${state === "generating" ? html`<span class="dots" style=${{ padding: 0 }}><i></i><i></i><i></i></span>` : Icon.play}
          </button>
          ${m.faqId && html`
            <span class="feedback-group">
              <button class=${"mini-btn" + (m.feedback === "liked" ? " on" : "")} title="This answer was correct and helpful"
                      disabled=${!!m.feedback} onClick=${() => onFeedback(m.id, m.faqId, m.feedbackKey, true)}>
                ${Icon.thumbUp}
              </button>
              <button class=${"mini-btn warn" + (m.feedback === "disliked" ? " on" : "")} title="This answer was wrong or unhelpful"
                      disabled=${!!m.feedback} onClick=${() => onFeedback(m.id, m.faqId, m.feedbackKey, false)}>
                ${Icon.thumbDown}
              </button>
            </span>`}
        </div>
      </div>
    </div>`;
}

function DemoLibrary({ onClose }) {
  const [copiedKey, setCopiedKey] = useState(null);

  const copy = (key, text) => {
    const markCopied = () => {
      setCopiedKey(key);
      setTimeout(() => setCopiedKey((k) => (k === key ? null : k)), 1400);
    };
    // Fallback for when the async Clipboard API is unavailable or denied
    // (permissions, non-HTTPS, unfocused document) - never leave the click
    // silently doing nothing, and never leave an unhandled rejection either.
    const fallbackCopy = () => {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); markCopied(); } catch {}
      document.body.removeChild(ta);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(markCopied).catch(fallbackCopy);
    } else {
      fallbackCopy();
    }
  };

  return html`
    <div class="modal-backdrop" onClick=${onClose}>
      <div class="modal" onClick=${(e) => e.stopPropagation()}>
        <div class="modal-header">
          <div>
            <h2>Demo question library</h2>
            <p>Click any question to copy it - English, Hindi, Marathi, native script and romanized, plus payment-issue examples.</p>
          </div>
          <button class="icon-btn" title="Close" onClick=${onClose}>${Icon.close}</button>
        </div>
        <div class="modal-body">
          ${DEMO_QUESTIONS.map((group, gi) => html`
            <div class="demo-group" key=${gi}>
              <h3>${group.label}</h3>
              <div class="demo-list">
                ${group.items.map((q, qi) => {
                  const key = `${gi}-${qi}`;
                  const copied = copiedKey === key;
                  return html`
                    <button class=${"demo-item" + (copied ? " copied" : "")} key=${key} onClick=${() => copy(key, q)}>
                      <span>${q}</span>
                      ${copied ? Icon.check : Icon.copy}
                    </button>`;
                })}
              </div>
            </div>`)}
        </div>
      </div>
    </div>`;
}

// One-time (until changed) language + script picker. `mode="intro"` renders it
// full-screen as the very first thing a student sees, replacing the old header
// dropdown + toggle - picking is a single flow instead of two separate controls
// to find and click. `mode="modal"` renders the same steps over the chat so the
// choice can be revisited later from the header's language pill.
function LangPicker({ mode, initial, onDone, onCancel }) {
  const [step, setStep] = useState(1);
  const [lang, setLang] = useState((initial && initial.lang) || null);

  const pickLanguage = (code) => {
    if (code === "en") { onDone({ lang: "en", script: "latin" }); return; }
    setLang(code);
    setStep(2);
  };

  const langOpt = LANGUAGE_OPTIONS.find((o) => o.code === lang);

  const content = step === 1 ? html`
    <div class="lang-step">
      <h2 class="lang-title">${mode === "intro" ? "Pick your language" : "Change language"}</h2>
      <p class="lang-desc">You can still ask a question in any language, any time - this just sets the app's own text, mic and voice.</p>
      <div class="lang-grid">
        ${LANGUAGE_OPTIONS.map((o) => html`
          <button class=${"lang-card" + (initial && initial.lang === o.code ? " on" : "")}
                  key=${o.code} onClick=${() => pickLanguage(o.code)}>
            <span class="lang-card-main">${o.label}</span>
            <span class="lang-card-sub">${o.sub}</span>
          </button>`)}
      </div>
    </div>` : html`
    <div class="lang-step">
      <button class="lang-back" onClick=${() => setStep(1)}>&larr; Back</button>
      <h2 class="lang-title">Native script or Latin?</h2>
      <p class="lang-desc">How should ${langOpt.sub} answers be written back to you?</p>
      <div class="script-grid">
        <button class=${"script-card" + (initial && initial.lang === lang && initial.script === "native" ? " on" : "")}
                onClick=${() => onDone({ lang, script: "native" })}>
          <span class="script-card-label">Native script</span>
          <span class="script-card-example">${SCRIPT_EXAMPLES[lang].native}</span>
        </button>
        <button class=${"script-card" + (initial && initial.lang === lang && initial.script === "latin" ? " on" : "")}
                onClick=${() => onDone({ lang, script: "latin" })}>
          <span class="script-card-label">Latin / romanized</span>
          <span class="script-card-example">${SCRIPT_EXAMPLES[lang].latin}</span>
        </button>
      </div>
    </div>`;

  if (mode === "intro") return html`<div class="lang-intro">${content}</div>`;
  return html`
    <div class="modal-backdrop" onClick=${onCancel}>
      <div class="modal lang-modal" onClick=${(e) => e.stopPropagation()}>
        <button class="icon-btn lang-modal-close" title="Close" onClick=${onCancel}>${Icon.close}</button>
        <div class="modal-body">${content}</div>
      </div>
    </div>`;
}

function App() {
  // null until the student has picked a language once (see LANG_PREF_KEY) - the
  // absence of a saved pref is exactly what triggers the full-screen intro
  // picker below, before any chat UI renders at all.
  const [pref, setPref] = useState(loadLangPref);
  const [showLangPicker, setShowLangPicker] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [speakOn, setSpeakOn] = useState(true);
  const [recording, setRecording] = useState(false);
  const [hint, setHint] = useState("");
  const [showDemo, setShowDemo] = useState(false);

  const lang = LANG_TO_CODE[pref ? pref.lang : "en"];
  // "auto" mirrors whatever script the student typed in: type in Devanagari and
  // the reply comes back in Devanagari, type "fee kiti ahe" and it comes back
  // romanized (see rag._apply_script_pref). "native" forces native script, which
  // is what someone who picked native script wants even from romanized input -
  // and what makes the answer speakable, since the TTS voice can't pronounce
  // romanized text.
  const nativeScript = !!(pref && pref.script === "native");

  const welcome = WELCOME[TTS_LANG_MAP[lang]] || WELCOME.en;

  const applyPref = (p) => {
    saveLangPref(p);
    setPref(p);
    setShowLangPicker(false);
  };

  const patchMessage = (id, patch) =>
    setMessages((m) => m.map((msg) => (msg.id === id ? { ...msg, ...patch } : msg)));

  const threadRef = useRef(null);
  const taRef = useRef(null);
  const { supported: micSupported, rec, media, canRecord } = useSpeech();

  // Set only while the LAST answer was a program-clarification prompt, so a
  // student who types "btech" instead of clicking the chip still gets their
  // original question answered (the backend resolves this - see
  // http/chat_routes.py's pendingClarification handling). A ref, not state:
  // it must be readable inside send() without adding a dependency that would
  // rebuild the callback on every message, and it is consumed exactly once.
  const pendingClarifyRef = useRef(null);

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [messages]);

  // `keyOverride` (set only when resubmitting after a program-clarification
  // chip click - see pickProgram) applies to THIS request only and is never
  // persisted - removed 2026-08-12 after a real vague follow-up question got
  // silently answered from a program a student had switched to minutes
  // earlier and forgotten about, with no visible sign it was still "stuck"
  // there. Every message not resubmitting a specific clarified answer now
  // always starts fresh from DEFAULT_API_KEY, so the backend's own routing
  // (rag.py's detect_program/needs_comparison/needs_program_clarification)
  // decides each question independently rather than a stale client-side key
  // deciding it for them.
  const send = useCallback(async (text, keyOverride) => {
    const q = (text || "").trim();
    if (!q || sending) return;
    // Consumed once: whether or not it resolves anything, the next message
    // must not still look like an answer to a clarification two turns back.
    const pendingClarification = pendingClarifyRef.current;
    pendingClarifyRef.current = null;
    // pendingClarification.apiKey (set below, alongside originalQuestion) is
    // the one narrow exception to keyOverride-never-persists (see the
    // comment above this callback): a percentage-then-programme chain
    // resolves the programme via a chip's keyOverride on one hop, then asks
    // a THIRD question (the actual subject-combination number) that carries
    // no programme name in its text at all - only the api key from the hop
    // that resolved it still knows. Reproduced live 2026-08-17: without
    // this, "I have 58% in my subject combination" reset to the shared
    // widget's default project and lost B.Tech Dairy entirely. Still
    // single-hop and consumed-once exactly like originalQuestion above, not
    // the unbounded persistence the 2026-08-12 fix removed.
    const activeKey = keyOverride || pendingClarification?.apiKey || DEFAULT_API_KEY;
    setMessages((m) => [...m, { role: "user", text: q }, { role: "thinking" }]);
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    setSending(true);

    // Watch the real pipeline. Everything here is best-effort: the progress
    // stream is decoration, so any failure to open it, or any delay past
    // PROGRESS_READY_MS, falls through to the plain thinking dots rather than
    // holding up the student's actual question.
    const traceId = newTraceId();
    let progress = null;
    const onStep = (event) => setMessages((m) => {
      const last = m[m.length - 1];
      if (!last || last.role !== "thinking") return m;
      const index = PROGRESS_STAGES.findIndex((s) => s.step === event.step);
      // final_answer arrives on every request including instant cache hits.
      // Advancing on it when nothing else has arrived would flash a fully
      // ticked five-row panel for one frame on an answer that took 300ms, so
      // it only completes a panel already on screen.
      const reached = event.step === "final_answer"
        ? (last.reached >= 0 ? PROGRESS_STAGES.length - 1 : -1)
        : index;
      if (reached < 0) return m;
      const details = { ...(last.details || {}) };
      if (event.detail) details[event.step] = event.detail;
      return [...m.slice(0, -1),
              { ...last, reached: Math.max(last.reached ?? -1, reached), details }];
    });
    try {
      progress = await openProgress(traceId, activeKey, onStep);
      await Promise.race([progress.ready,
                          new Promise((r) => setTimeout(r, PROGRESS_READY_MS))]);
    } catch {
      progress = null;
    }

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(activeKey ? { "X-API-Key": activeKey } : {}) },
        body: JSON.stringify({
          question: q,
          traceId,
          scriptPreference: nativeScript ? "native" : "auto",
          uiLanguage: TTS_LANG_MAP[lang] || "en",
          // Prior turns, so a follow-up resolves against what was already
          // asked (see backend/rag/router.py). Real exchanged text only -
          // thinking/error placeholders carry no meaning.
          history: messages
            .filter((x) => (x.role === "user" || x.role === "bot") && x.text)
            .slice(-8)
            .map((x) => ({ role: x.role === "user" ? "user" : "assistant", text: x.text })),
          ...(pendingClarification ? { pendingClarification } : {}),
        }),
      });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      // Arm the follow-up resolution above for the NEXT message, carrying
      // the question that actually needs answering once the student
      // answers - the same text the clarification chips resubmit.
      // d.carryQuestion (server-known, see chat_routes.py) wins over the
      // client's own `q` whenever present: the moment two clarifications
      // chain (percentage, then still-unknown programme), `q` is just the
      // scope reply itself ("overall"), not the combined question the
      // NEXT clarification needs to carry forward. activeKey rides along
      // too (see send()'s pendingClarification.apiKey comment) - covers
      // _eligibility_guard's "overall_not_subject" reply as well, which
      // carries carryQuestion but no chips at all (asks for a number, not a
      // pick), and would otherwise lose a programme resolved via keyOverride
      // on an earlier hop the moment the student just types the figure.
      if (d.clarifyOptions) pendingClarifyRef.current = { kind: "program", originalQuestion: d.carryQuestion || q, apiKey: activeKey };
      else if (d.scopeOptions) pendingClarifyRef.current = { kind: "percentage", originalQuestion: d.carryQuestion || q, apiKey: activeKey };
      else if (d.carryQuestion) pendingClarifyRef.current = { kind: "percentage", originalQuestion: d.carryQuestion, apiKey: activeKey };
      const botId = nextId();
      setMessages((m) => [...m.slice(0, -1), {
        id: botId, role: "bot", text: d.answerText, pages: d.pageReferences || [],
        model: d.model, source: d.source, audioState: d.speakable ? "idle" : "unspeakable",
        clarifyOptions: d.clarifyOptions || null, scopeOptions: d.scopeOptions || null,
        answeredForProgram: d.answeredForProgram || null,
        comparedPrograms: d.comparedPrograms || null,
        originalQuestion: d.carryQuestion || q, carryQuestion: d.carryQuestion || q,
        faqId: d.faqId || null, feedback: null, feedbackKey: activeKey,
      }]);

      if (speakOn && d.speakable) {
        const short = TTS_LANG_MAP[lang] || "en";
        if (short === "en") {
          speakBrowserNow(d.answerText, lang);
        } else {
          // Generate now, in the background - the user taps the button to actually
          // hear it once it's ready, which is what keeps playback reliable.
          patchMessage(botId, { audioState: "generating" });
          fetchIndicAudio(d.answerText, short, activeKey)
            .then((url) => patchMessage(botId, { audioState: "ready", audioUrl: url }))
            .catch(() => patchMessage(botId, { audioState: "error" }));
        }
      }
    } catch (e) {
      const msg = e.message === "401"
        ? "This key is inactive or invalid. Check the console."
        : "Something went wrong reaching the assistant. Please try again.";
      setMessages((m) => [...m.slice(0, -1), { role: "error", text: msg }]);
    } finally {
      // The server closes the stream on final_answer, but a question that
      // failed or timed out never reaches that step - without this the reader
      // would sit open until the route's own 300s cap.
      progress?.cancel();
      setSending(false);
    }
    // `messages` is a real dependency now that history is sent - without it
    // send() would close over the thread as it looked when the callback was
    // last built and ship stale (or empty) history to the router.
  }, [sending, lang, speakOn, nativeScript, messages]);

  // Resolves a program-clarification prompt: look up that program's own
  // widget key and resubmit the original question under it, for this one
  // request only (see send's keyOverride) - the NEXT message a student
  // types is unaffected and goes through the default project's own routing
  // fresh, same as embedding that program's own dedicated widget would for
  // just this one answer, not for the rest of the conversation.
  const pickProgram = useCallback((projectId, originalQuestion) => {
    const program = PROGRAMS.find((p) => p.projectId === projectId);
    if (!program) return;
    send(originalQuestion, program.apiKey);
  }, [send]);

  // Unlike pickProgram above, a scope choice can't be resolved client-side -
  // splicing "overall" onto the original question's percentage correctly
  // (see core/eligibility.py's apply_percentage_scope, a tight-window cue
  // match) needs the server. So this arms pendingClarifyRef itself and sends
  // the chip's fixed value text, taking the exact same round trip a typed
  // "It's my overall percentage" reply would - see chat_routes.py's
  // pendingClarification handling for the kind:"percentage" branch that
  // does the actual splice.
  const pickScope = useCallback((value, originalQuestion) => {
    pendingClarifyRef.current = { kind: "percentage", originalQuestion };
    send(value);
  }, [send]);

  // Thumbs up/down on a specific served answer. Uses the key that ANSWERED
  // this particular message (m.feedbackKey), stored on the message itself at
  // send time - independent of whatever key answers the NEXT message, so
  // feedback always lands in the project that actually served it. Marks the
  // message locally right
  // away so the buttons disable and show the choice - no need to wait on a
  // response to feel responsive, and a failure just leaves it retryable.
  const sendFeedback = useCallback(async (messageId, faqId, feedbackKey, liked) => {
    patchMessage(messageId, { feedback: liked ? "liked" : "disliked" });
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(feedbackKey ? { "X-API-Key": feedbackKey } : {}) },
        body: JSON.stringify({ faqId, liked }),
      });
      if (!res.ok) throw new Error(String(res.status));
    } catch {
      // Don't silently claim success on a failed submit - let the student
      // see it didn't take and try again, rather than a false "recorded"
      // state with no actual effect server-side.
      patchMessage(messageId, { feedback: null });
    }
  }, []);

  const toggleMic = useCallback(() => {
    // Server-side transcription when the browser can record, which is nearly
    // everywhere. Falls through to the browser recogniser only when it
    // cannot, so no one who has voice input today loses it.
    if (canRecord) {
      if (recording) {
        if (media.current) media.current.stop();
        return;
      }
      setRecording(true);
      recordAndTranscribe(media, DEFAULT_API_KEY, TTS_LANG_MAP[lang] || "en",
                          () => setHint("Listening… tap again when you're done."))
        .then((text) => {
          setRecording(false);
          setHint("");
          if (text) send(text);
          else setHint("Couldn't catch that — try again or type it.");
        })
        .catch(() => {
          setRecording(false);
          setHint("Microphone unavailable — you can type instead.");
        });
      return;
    }
    const r = rec.current;
    if (!r) return;
    if (recording) { r.stop(); return; }
    r.lang = lang;
    r.onresult = (e) => { const t = e.results[0][0].transcript; setInput(t); };
    r.onend = () => {
      setRecording(false);
      setHint("");
      if (taRef.current && taRef.current.value.trim()) send(taRef.current.value);
    };
    r.onerror = () => { setRecording(false); setHint("Couldn't hear that — try again or type."); };
    try { r.start(); setRecording(true); setHint("Listening… speak now."); } catch {}
  }, [recording, lang, send, rec, canRecord, media]);

  const clearChat = () => {
    stopSpeaking();
    setMessages([]);
  };

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
  };
  const onInput = (e) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 150) + "px";
  };

  // First run: nothing picked yet, so the language/script choice IS the whole
  // screen - no chat, no header, no other controls to click through first.
  if (!pref) {
    return html`<${LangPicker} mode="intro" initial=${null} onDone=${applyPref} />`;
  }

  const currentLangLabel = LANGUAGE_OPTIONS.find((o) => o.code === pref.lang).label;

  return html`
    <div class="chat">
      <header class="chat-header">
        <div class="brand">
          <span class="brand-mark">A</span>
          <div>
            <div class="brand-name">Admission Assistant</div>
            <div class="brand-sub">Answers from the official prospectus</div>
          </div>
        </div>
        <div class="header-tools">
          <button class="icon-btn" title="Demo question library" onClick=${() => setShowDemo(true)}>
            ${Icon.list}
          </button>
          <button class="icon-btn lang-current" title="Change language" onClick=${() => setShowLangPicker(true)}>
            <span>${currentLangLabel}</span>
            ${pref.lang !== "en" && html`<span class="lang-current-script">${pref.script === "native" ? "· native" : "· Latin"}</span>`}
          </button>
          <button class=${"icon-btn" + (speakOn ? " on" : "")} title="Read answers aloud"
                  onClick=${() => { setSpeakOn(!speakOn); if (speakOn) stopSpeaking(); }}>
            ${Icon.speaker}
          </button>
          ${messages.length > 0 && html`
            <button class="icon-btn" title="Clear chat" onClick=${clearChat}>
              ${Icon.clear}
            </button>`}
        </div>
      </header>

      <main class="thread" ref=${threadRef}>
        ${messages.length === 0 && html`
          <div class="empty">
            <h1>${welcome.title}</h1>
            <p>${welcome.body}</p>
            <div class="chips">
              ${welcome.chips.map((s) => html`<button class="chip" key=${s} onClick=${() => send(s)}>${s}</button>`)}
            </div>
          </div>`}
        ${messages.map((m, i) => html`<${Message} key=${m.id || i} m=${m} lang=${lang} onReplayBrowser=${(t) => speakBrowserNow(t, lang)} onPickProgram=${pickProgram} onPickScope=${pickScope} onFeedback=${sendFeedback} />`)}
      </main>

      <footer class="composer">
        <div class="bar">
          ${micSupported && html`<button class=${"mic" + (recording ? " rec" : "")} title="Speak your question" onClick=${toggleMic}>${Icon.mic}</button>`}
          <textarea ref=${taRef} rows="1" placeholder=${welcome.placeholder} value=${input}
                    onInput=${onInput} onKeyDown=${onKey}></textarea>
          <button class="send" disabled=${sending} onClick=${() => send(input)} aria-label="Send">${Icon.send}</button>
        </div>
        <p class="hint">${hint}</p>
      </footer>

      ${showDemo && html`<${DemoLibrary} onClose=${() => setShowDemo(false)} />`}
      ${showLangPicker && html`<${LangPicker} mode="modal" initial=${pref} onDone=${applyPref} onCancel=${() => setShowLangPicker(false)} />`}
    </div>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
