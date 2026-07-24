// React, ReactDOM and htm are provided as globals by the vendored UMD scripts
// (see index.html). No bundler, no ESM/CDN - works offline and in locked-down envs.
const { useState, useRef, useEffect, useCallback } = React;
const createRoot = ReactDOM.createRoot;
const html = htm.bind(React.createElement);

// The admission site's own widget key is injected by the server; fall back to a
// meta tag or empty (the console's "Try It" sets its own).
const API_KEY = window.ADMISSION_API_KEY ||
  (document.querySelector('meta[name="api-key"]') || {}).content || "";

const LANGS = [
  { code: "en-IN", label: "English" },
  { code: "hi-IN", label: "हिंदी" },
  { code: "mr-IN", label: "मराठी" },
  { code: "ta-IN", label: "தமிழ்" },
];

const SUGGESTIONS = [
  "What are the eligibility criteria for admission?",
  "When is the last date to apply?",
  "What documents are required at admission?",
];

const Icon = {
  send: html`<svg viewBox="0 0 20 20" width="18" height="18" fill="none"><path d="M3 10L17 3L11.5 17L9.5 11L3 10Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`,
  mic: html`<svg viewBox="0 0 20 20" width="18" height="18" fill="none"><rect x="7.5" y="2.5" width="5" height="9" rx="2.5" fill="currentColor"/><path d="M5 9a5 5 0 0 0 10 0M10 14v3M7.5 17h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  speaker: html`<svg viewBox="0 0 20 20" width="17" height="17" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6M16 5c2 2 2 8 0 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`,
  play: html`<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>`,
};

function useSpeech() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recRef = useRef(null);
  useEffect(() => {
    if (!SR) return;
    const r = new SR();
    r.interimResults = false;
    r.maxAlternatives = 1;
    recRef.current = r;
  }, []);
  return { supported: !!SR, rec: recRef };
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

async function fetchIndicAudio(text, shortLang) {
  const res = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(API_KEY ? { "X-API-Key": API_KEY } : {}) },
    body: JSON.stringify({ text, language: shortLang }),
  });
  if (!res.ok) throw new Error(String(res.status));
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

function Message({ m, lang, onReplayBrowser }) {
  if (m.role === "user")
    return html`<div class="row user"><div class="bubble">${m.text}</div></div>`;
  if (m.role === "thinking")
    return html`<div class="row bot"><div class="bubble"><span class="dots"><i></i><i></i><i></i></span></div></div>`;
  if (m.role === "error")
    return html`<div class="row bot err"><div class="bubble">${m.text}</div></div>`;

  const srcPill = m.source === "faq-cache"
    ? html`<span class="pill cache" title="Answered instantly from cache">⚡ instant</span>`
    : m.model ? html`<span class="pill src">${m.model.replace("sarvam:", "")}</span>` : null;

  const state = m.audioState;
  const title = state === "generating" ? "Generating natural voice…"
    : state === "ready" ? "Play natural voice"
    : state === "error" ? "Natural voice unavailable — tap for device voice"
    : "Read aloud";

  const handleClick = () => {
    if (state === "ready" && m.audioUrl) playUrl(m.audioUrl);
    else if (state !== "generating") onReplayBrowser(m.text);
  };

  return html`
    <div class="row bot">
      <div>
        <div class="bubble">${m.text}</div>
        <div class="meta">
          ${(m.pages || []).map((p) => html`<span class="pill" key=${p}>p. ${p}</span>`)}
          ${srcPill}
          <button class=${"mini-btn" + (state === "ready" ? " on" : "")} title=${title}
                  disabled=${state === "generating"} onClick=${handleClick}>
            ${state === "generating" ? html`<span class="dots" style=${{ padding: 0 }}><i></i><i></i><i></i></span>` : Icon.play}
          </button>
        </div>
      </div>
    </div>`;
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [lang, setLang] = useState("en-IN");
  const [speakOn, setSpeakOn] = useState(true);
  const [recording, setRecording] = useState(false);
  const [hint, setHint] = useState("");

  const patchMessage = (id, patch) =>
    setMessages((m) => m.map((msg) => (msg.id === id ? { ...msg, ...patch } : msg)));

  const threadRef = useRef(null);
  const taRef = useRef(null);
  const { supported: micSupported, rec } = useSpeech();

  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
  }, [messages]);

  const send = useCallback(async (text) => {
    const q = (text || "").trim();
    if (!q || sending) return;
    setMessages((m) => [...m, { role: "user", text: q }, { role: "thinking" }]);
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    setSending(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(API_KEY ? { "X-API-Key": API_KEY } : {}) },
        body: JSON.stringify({ question: q }),
      });
      if (!res.ok) throw new Error(res.status);
      const d = await res.json();
      const botId = nextId();
      setMessages((m) => [...m.slice(0, -1), {
        id: botId, role: "bot", text: d.answerText, pages: d.pageReferences || [],
        model: d.model, source: d.source, audioState: "idle",
      }]);

      if (speakOn) {
        const short = TTS_LANG_MAP[lang] || "en";
        if (short === "en") {
          speakBrowserNow(d.answerText, lang);
        } else {
          // Generate now, in the background - the user taps the button to actually
          // hear it once it's ready, which is what keeps playback reliable.
          patchMessage(botId, { audioState: "generating" });
          fetchIndicAudio(d.answerText, short)
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
      setSending(false);
    }
  }, [sending, lang, speakOn]);

  const toggleMic = useCallback(() => {
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
  }, [recording, lang, send, rec]);

  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
  };
  const onInput = (e) => {
    setInput(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = Math.min(e.target.scrollHeight, 150) + "px";
  };

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
          <select class="lang-select" value=${lang} onChange=${(e) => setLang(e.target.value)} aria-label="Voice language">
            ${LANGS.map((l) => html`<option key=${l.code} value=${l.code}>${l.label}</option>`)}
          </select>
          <button class=${"icon-btn" + (speakOn ? " on" : "")} title="Read answers aloud"
                  onClick=${() => { setSpeakOn(!speakOn); if (speakOn) stopSpeaking(); }}>
            ${Icon.speaker}
          </button>
        </div>
      </header>

      <main class="thread" ref=${threadRef}>
        ${messages.length === 0 && html`
          <div class="empty">
            <h1>Ask anything about admissions</h1>
            <p>Answers come straight from the prospectus, in your language, with page references.</p>
            <div class="chips">
              ${SUGGESTIONS.map((s) => html`<button class="chip" key=${s} onClick=${() => send(s)}>${s}</button>`)}
            </div>
          </div>`}
        ${messages.map((m, i) => html`<${Message} key=${m.id || i} m=${m} lang=${lang} onReplayBrowser=${(t) => speakBrowserNow(t, lang)} />`)}
      </main>

      <footer class="composer">
        <div class="bar">
          ${micSupported && html`<button class=${"mic" + (recording ? " rec" : "")} title="Speak your question" onClick=${toggleMic}>${Icon.mic}</button>`}
          <textarea ref=${taRef} rows="1" placeholder="Ask about admissions…" value=${input}
                    onInput=${onInput} onKeyDown=${onKey}></textarea>
          <button class="send" disabled=${sending} onClick=${() => send(input)} aria-label="Send">${Icon.send}</button>
        </div>
        <p class="hint">${hint}</p>
      </footer>
    </div>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
