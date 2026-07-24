const { useState, useRef, useEffect, useCallback } = React;
const createRoot = ReactDOM.createRoot;
const html = htm.bind(React.createElement);

const TOKEN_KEY = "admissionAdminToken";
const PROJECT_KEY = "admissionAdminProject";
const LANG_LABELS = { latin: "English", devanagari: "Hindi / Marathi", tamil: "Tamil" };

async function api(path, { method = "GET", token, body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { "X-Admin-Token": token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(String(res.status));
  return res.status === 204 ? null : res.json();
}

const Icon = {
  dashboard: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><rect x="3" y="3" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="11" y="3" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="3" y="11" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="11" y="11" width="6" height="6" rx="1.5" stroke="currentColor" stroke-width="1.5"/></svg>`,
  link: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><path d="M8 12l4-4M6.5 9.5L5 11a2.83 2.83 0 004 4l1.5-1.5M13.5 10.5L15 9a2.83 2.83 0 00-4-4l-1.5 1.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  chat: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><path d="M3 4h14v9H8l-3 3v-3H3V4z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  puzzle: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><path d="M7 3.5a1.5 1.5 0 013 0V5h2a1 1 0 011 1v2h1.5a1.5 1.5 0 010 3H13v2a1 1 0 01-1 1h-2v1.5a1.5 1.5 0 01-3 0V14H5a1 1 0 01-1-1v-2H2.5a1.5 1.5 0 010-3H4V6a1 1 0 011-1h2V3.5z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>`,
  coin: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.5"/><path d="M10 6.5v7M12 8.2c0-.9-.9-1.7-2-1.7s-2 .7-2 1.6c0 2 4 1 4 3 0 .9-.9 1.6-2 1.6s-2-.7-2-1.6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>`,
  upload: html`<svg viewBox="0 0 20 20" width="13" height="13" fill="none"><path d="M10 13V4M6.5 7.5L10 4l3.5 3.5M4 14.5v1a1 1 0 001 1h10a1 1 0 001-1v-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  trash: html`<svg viewBox="0 0 20 20" width="13" height="13" fill="none"><path d="M4.5 6h11M8 6V4.5a1 1 0 011-1h2a1 1 0 011 1V6m-6.5 0l.6 9a1 1 0 001 .9h5.8a1 1 0 001-.9l.6-9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  mic: html`<svg viewBox="0 0 20 20" width="16" height="16" fill="none"><rect x="7.5" y="2.5" width="5" height="9" rx="2.5" fill="currentColor"/><path d="M5 9a5 5 0 0 0 10 0M10 14v3M7.5 17h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`,
  speaker: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6M16 5c2 2 2 8 0 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>`,
  play: html`<svg viewBox="0 0 20 20" width="13" height="13" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>`,
};

// Voice, shared with the student-facing widget's approach (app.js): Indic
// languages get the self-hosted AI4Bharat voice via /api/tts, English stays on
// the instant browser voice. Lets an admin test the exact voice path a student gets.
const TTS_LANG_MAP = { "hi-IN": "hi", "mr-IN": "mr", "ta-IN": "ta", "en-IN": "en" };
const VOICE_LANGS = [
  { code: "en-IN", label: "English" },
  { code: "hi-IN", label: "हिंदी" },
  { code: "mr-IN", label: "मराठी" },
  { code: "ta-IN", label: "தமிழ்" },
];
let currentAudio = null;

function stopSpeaking() {
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

function speakBrowser(text, lang, onEnd) {
  if (!window.speechSynthesis) { onEnd && onEnd(); return; }
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang;
  const v = window.speechSynthesis.getVoices().find((x) => x.lang === lang);
  if (v) u.voice = v;
  u.onend = () => onEnd && onEnd();
  u.onerror = () => onEnd && onEnd();
  window.speechSynthesis.speak(u);
}

async function speak(text, lang, apiKey, hooks = {}) {
  stopSpeaking();
  const short = TTS_LANG_MAP[lang] || "en";
  if (short === "en") { speakBrowser(text, lang, hooks.onEnd); return; }
  hooks.onStart && hooks.onStart();
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}) },
      body: JSON.stringify({ text, language: short }),
    });
    if (!res.ok) throw new Error(String(res.status));
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    currentAudio.onended = () => { hooks.onEnd && hooks.onEnd(); URL.revokeObjectURL(url); };
    currentAudio.onerror = () => { hooks.onEnd && hooks.onEnd(); URL.revokeObjectURL(url); };
    await currentAudio.play();
  } catch (e) {
    hooks.onError && hooks.onError(e);
    speakBrowser(text, lang, hooks.onEnd);
  }
}

function useSpeechRecognition() {
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

function timeAgo(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  return Math.floor(s / 3600) + "h ago";
}

// ---------- Dashboard ----------
function Dashboard({ token, projectId }) {
  const [d, setD] = useState(null);
  const load = useCallback(() => { if (token && projectId) api(`/admin/projects/${projectId}/stats`, { token }).then(setD).catch(() => {}); }, [token, projectId]);
  useEffect(() => { setD(null); load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  if (!token) return html`<div class="panel"><h1>Dashboard</h1><p class="lead">Connect with the admin token to view live metrics.</p></div>`;
  if (!d) return html`<div class="panel"><h1>Dashboard</h1><p class="lead">Loading…</p></div>`;

  const langTotal = Object.values(d.languages).reduce((a, b) => a + b, 0) || 1;

  return html`
    <div class="panel">
      <h1>Dashboard</h1>
      <p class="lead">Live overview of the admission assistant — volume, cache effectiveness, and system health.</p>

      <div class="health-strip">
        <div class="health-item"><span class=${"status-dot " + (d.health.embedding === "up" ? "ok" : "err")}></span>Embeddings ${d.health.embedding}</div>
        <div class="health-item"><span class=${"status-dot " + (d.health.ollama === "up" ? "ok" : "err")}></span>Ollama ${d.health.ollama}</div>
        <div class="health-item"><span class=${"status-dot " + (d.health.sarvam === "configured" ? "ok" : "idle")}></span>Sarvam ${d.health.sarvam}</div>
      </div>

      <div class="stat-grid">
        <div class="stat-card"><div class="num">${d.totalQuestions}</div><div class="lbl">Questions answered</div></div>
        <div class="stat-card"><div class="num">${d.cacheHitRate}%</div><div class="lbl">Cache hit rate</div><div class="sub">${d.cacheHits} instant</div></div>
        <div class="stat-card"><div class="num">${d.avgLatencyMs ? (d.avgLatencyMs / 1000).toFixed(1) + "s" : "—"}</div><div class="lbl">Avg response time</div></div>
        <div class="stat-card"><div class="num">${d.activeKeys}<span style=${{fontSize:"1rem",color:"var(--ink-3)"}}>/${d.totalKeys}</span></div><div class="lbl">Active keys</div></div>
      </div>

      <div class="section-h">Language mix</div>
      <div class="card" style=${{padding:"18px 20px"}}>
        <div class="lang-bars">
          ${Object.entries(d.languages).map(([k, v]) => html`
            <div class="lang-bar-row" key=${k}>
              <span class="lbl">${LANG_LABELS[k] || k}</span>
              <div class="lang-bar-track"><div class="lang-bar-fill" style=${{width: Math.round(v / langTotal * 100) + "%"}}></div></div>
              <span class="cnt">${v}</span>
            </div>`)}
        </div>
      </div>

      <div class="section-h">Recent activity</div>
      <div class="card activity">
        ${d.recent.length === 0 ? html`<div class="empty-hint">No questions answered yet.</div>` :
          d.recent.map((r, i) => html`
            <div class="activity-row" key=${i}>
              <span class="t">${timeAgo(r.ts)}</span>
              <span class=${"pill " + (r.source === "faq-cache" ? "cache" : "src")}>${r.source === "faq-cache" ? "⚡ cache" : (r.model || "").replace("sarvam:", "")}</span>
              <span class="muted">${LANG_LABELS[r.language] || r.language}</span>
              <span class="muted" style=${{marginLeft:"auto"}}>${(r.latencyMs / 1000).toFixed(1)}s</span>
            </div>`)}
      </div>
    </div>`;
}

// ---------- Cost ----------
function Cost({ token, projectId, onChange }) {
  const [d, setD] = useState(null);
  const load = useCallback(() => { if (token && projectId) api(`/admin/projects/${projectId}/stats`, { token }).then(setD).catch(() => {}); }, [token, projectId]);
  useEffect(() => { setD(null); load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  const clearCache = async () => {
    if (!confirm("Clear the FAQ cache? Future questions will re-run the full pipeline until re-cached.")) return;
    await api(`/admin/projects/${projectId}/cache/clear`, { method: "POST", token });
    load();
  };

  const toggleCloud = async () => {
    await api(`/admin/projects/${projectId}`, { method: "PATCH", token, body: { allow_cloud: !d.allowCloud } });
    load();
    onChange && onChange();
  };

  if (!token) return html`<div class="panel"><h1>Cost</h1><p class="lead">Connect with the admin token to view usage and cost exposure.</p></div>`;
  if (!d) return html`<div class="panel"><h1>Cost</h1><p class="lead">Loading…</p></div>`;

  const pct = Math.min(100, Math.round(d.sarvam.count / d.sarvam.limit * 100));
  const warn = pct >= 80;

  return html`
    <div class="panel">
      <h1>Cost</h1>
      <p class="lead">What this project's answers cost, and which model is allowed to answer them. The Sarvam daily cap below is a shared, account-wide safety limit — it can never drift into paid usage on its own, it just falls back to the free local model once the cap is hit.</p>

      <div class="cap-bar-wrap">
        <div class="cap-bar-head">
          <span>Sarvam cloud calls today (all projects)</span>
          <span class="n">${d.sarvam.count} / ${d.sarvam.limit}</span>
        </div>
        <div class="cap-track"><div class=${"cap-fill" + (warn ? " warn" : "")} style=${{width: pct + "%"}}></div></div>
      </div>

      <div class="section-h">This project's model policy</div>
      <div class="card">
        <div class="agent-row">
          <span class="agent-name"><span class="agent-dot" style=${{background: d.allowCloud ? "var(--amber)" : "var(--ink-3)"}}></span>Sarvam AI (cloud)</span>
          <div class="agent-meta">
            <span class="agent-cost cloud">${d.allowCloud ? `allowed — shares the ${d.sarvam.limit}/day cap` : "disabled for this project"}</span>
            <span class="agent-count">${d.sarvamCalls}</span>
            <button class=${"switch" + (d.allowCloud ? " on" : "")} title=${d.allowCloud ? "Turn off cloud for this project" : "Allow cloud for this project"} onClick=${toggleCloud}></button>
          </div>
        </div>
        <div class="agent-row">
          <span class="agent-name"><span class="agent-dot" style=${{background:"var(--ink-3)"}}></span>Local model (Ollama)</span>
          <div class="agent-meta"><span class="agent-cost free">${d.allowCloud ? "$0 — the fallback, runs on your server" : "$0 — the only model this project uses"}</span><span class="agent-count">${d.localCalls}</span></div>
        </div>
        <div class="agent-row">
          <span class="agent-name"><span class="agent-dot" style=${{background:"var(--accent)"}}></span>FAQ cache</span>
          <div class="agent-meta"><span class="agent-cost free">$0 — no model call at all</span><span class="agent-count">${d.cacheHits}</span></div>
        </div>
      </div>
      <p style=${{fontSize:12.5,color:"var(--ink-3)",margin:"10px 2px 0"}}>Turn Sarvam off here for projects that don't need cloud quality — they'll always use the free local model instead, and never touch the shared daily cap. Every project in the sidebar has its own policy and its own row like this one.</p>

      <div class="section-h">Cache</div>
      <div class="card" style=${{padding:"16px 18px",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div>
          <div style=${{fontSize:14,fontWeight:500}}>${d.cacheHits} instant answers served, ${d.cacheHitRate}% hit rate</div>
          <div style=${{fontSize:12.5,color:"var(--ink-3)",marginTop:3}}>Every RAG answer is auto-cached, so repeat questions skip the LLM entirely.</div>
        </div>
        <button class="btn danger" onClick=${clearCache}>Clear cache</button>
      </div>
    </div>`;
}

// ---------- API Keys (URL Generator) ----------
function KeysPanel({ token, projectId, keys, onChange, err }) {
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true);
    try { await api("/admin/keys", { method: "POST", token, body: { label, project_id: projectId } }); setLabel(""); onChange(); }
    finally { setBusy(false); }
  };
  const toggle = async (k) => { await api(`/admin/keys/${k.id}`, { method: "PATCH", token, body: { active: !k.active } }); onChange(); };
  const del = async (k) => {
    if (!confirm(`Delete "${k.label}"? Anything using it stops working immediately.`)) return;
    await api(`/admin/keys/${k.id}`, { method: "DELETE", token }); onChange();
  };
  const copy = (v, e) => { navigator.clipboard.writeText(v); const t = e.target; const old = t.textContent; t.textContent = "copied"; setTimeout(() => t.textContent = old, 1200); };

  return html`
    <div class="panel">
      <h1>URL Generator</h1>
      <p class="lead">One URL, many keys. Each consumer — the admission site, the browser extension, any integration — gets its own key against the same endpoint, so any one can be deactivated without affecting the others.</p>
      <div class="create">
        <input placeholder="Label, e.g. browser-extension" value=${label} onInput=${(e) => setLabel(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && generate()} />
        <button class="btn primary" disabled=${busy || !token} onClick=${generate}>Generate key</button>
      </div>
      <div class="card">
        ${!token ? html`<div class="empty-hint">Connect with the admin token to view and manage keys.</div>`
        : err ? html`<div class="empty-hint">${err}</div>`
        : keys.length === 0 ? html`<div class="empty-hint">No keys yet. Generate one above.</div>`
        : html`<table class="keys">
            <thead><tr><th>Label</th><th>Key</th><th>Status</th><th>Created</th><th></th></tr></thead>
            <tbody>
              ${keys.map((k) => html`
                <tr key=${k.id}>
                  <td>${k.label}</td>
                  <td><span class="kv"><code title=${k.key}>${k.key}</code><button class="copy" onClick=${(e) => copy(k.key, e)}>copy</button></span></td>
                  <td><span class=${"badge " + (k.active ? "on" : "off")}>${k.active ? "Active" : "Inactive"}</span></td>
                  <td class="muted">${new Date(k.created_at).toLocaleDateString()}</td>
                  <td><div class="acts">
                    <button class="btn sm" onClick=${() => toggle(k)}>${k.active ? "Deactivate" : "Activate"}</button>
                    <button class="btn sm danger" onClick=${() => del(k)}>Delete</button>
                  </div></td>
                </tr>`)}
            </tbody>
          </table>`}
      </div>
    </div>`;
}

// ---------- Try It ----------
function TesterPanel({ keys }) {
  const active = keys.filter((k) => k.active);
  const [keyVal, setKeyVal] = useState("");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [lang, setLang] = useState("en-IN");
  const [speakOn, setSpeakOn] = useState(false);
  const [recording, setRecording] = useState(false);
  const [ttsBusy, setTtsBusy] = useState(false);
  const [hint, setHint] = useState("");
  const threadRef = useRef(null);
  const { supported: micSupported, rec } = useSpeechRecognition();

  useEffect(() => { if (!keyVal && active.length) setKeyVal(active[0].key); }, [keys]);
  useEffect(() => { if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight; }, [messages]);
  useEffect(() => () => stopSpeaking(), []);

  const doSpeak = (text) => {
    if (!speakOn) return;
    setTtsBusy(true);
    speak(text, lang, keyVal, {
      onStart: () => setHint("Generating voice…"),
      onEnd: () => { setTtsBusy(false); setHint(""); },
      onError: () => setHint("Voice service unavailable — using device voice instead."),
    });
  };

  const send = async (text) => {
    const q = (text || input).trim();
    if (!q || busy) return;
    if (!keyVal) { alert("No active key selected. Generate or activate one in URL Generator first."); return; }
    setMessages((m) => [...m, { role: "user", text: q }, { role: "thinking" }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json", "X-API-Key": keyVal }, body: JSON.stringify({ question: q }) });
      if (res.status === 401) { setMessages((m) => [...m.slice(0, -1), { role: "err", text: "401 Unauthorized — that key is inactive or invalid." }]); return; }
      const d = await res.json();
      setMessages((m) => [...m.slice(0, -1), { role: "bot", text: d.answerText, pages: d.pageReferences, model: d.model, source: d.source }]);
      doSpeak(d.answerText);
    } catch { setMessages((m) => [...m.slice(0, -1), { role: "err", text: "Request failed. Check that the backend is running." }]); }
    finally { setBusy(false); }
  };

  const toggleMic = () => {
    const r = rec.current;
    if (!r) return;
    if (recording) { r.stop(); return; }
    r.lang = lang;
    r.onresult = (e) => setInput(e.results[0][0].transcript);
    r.onend = () => { setRecording(false); setHint(""); };
    r.onerror = () => { setRecording(false); setHint("Couldn't hear that — try again or type."); };
    try { r.start(); setRecording(true); setHint("Listening… speak now."); } catch {}
  };

  return html`
    <div class="panel">
      <h1>Try It</h1>
      <p class="lead">Send a question through a selected key, exactly as an external consumer (or the student widget's mic/voice reply) would hit <code>/api/chat</code> and <code>/api/tts</code>.</p>
      <div class="tester-ctrl">
        <label>Test with key</label>
        <select class="sel" value=${keyVal} onChange=${(e) => setKeyVal(e.target.value)}>
          ${active.length === 0 ? html`<option value="">No active keys</option>` : active.map((k) => html`<option key=${k.id} value=${k.key}>${k.label}</option>`)}
        </select>
        <div class="tester-tools">
          <select class="sel" value=${lang} onChange=${(e) => setLang(e.target.value)} aria-label="Voice language">
            ${VOICE_LANGS.map((l) => html`<option key=${l.code} value=${l.code}>${l.label}</option>`)}
          </select>
          <button class=${"icon-btn" + (speakOn ? " on" : "")} title="Read answers aloud"
                  onClick=${() => { setSpeakOn(!speakOn); if (speakOn) { stopSpeaking(); setTtsBusy(false); setHint(""); } }}>
            ${ttsBusy ? html`<span class="dots" style=${{ padding: 0 }}><i></i><i></i><i></i></span>` : Icon.speaker}
          </button>
        </div>
      </div>
      <div class="tester-thread" ref=${threadRef}>
        ${messages.length === 0 && html`<div class="empty" style=${{margin:"auto"}}><h2 style=${{fontFamily:"var(--font-display)",fontSize:"1.1rem",margin:"0 0 6px"}}>Ask the prospectus</h2><p style=${{color:"var(--ink-2)",fontSize:14}}>Pick an active key above, then ask by typing or speaking.</p></div>`}
        ${messages.map((m, i) => {
          if (m.role === "user") return html`<div class="row user" key=${i}><div class="bubble">${m.text}</div></div>`;
          if (m.role === "thinking") return html`<div class="row bot" key=${i}><div class="bubble"><span class="dots"><i></i><i></i><i></i></span></div></div>`;
          if (m.role === "err") return html`<div class="row bot err" key=${i}><div class="bubble">${m.text}</div></div>`;
          return html`<div class="row bot" key=${i}><div><div class="bubble">${m.text}</div>
            <div class="meta">
              ${(m.pages || []).map((p) => html`<span class="pill" key=${p}>p. ${p}</span>`)}
              ${m.source === "faq-cache" ? html`<span class="pill cache">⚡ instant</span>` : m.model && html`<span class="pill src">${m.model.replace("sarvam:", "")}</span>`}
              <button class="mini-btn" title="Read aloud" onClick=${() => doSpeak(m.text)}>${Icon.play}</button>
            </div></div></div>`;
        })}
      </div>
      <div class="tester-bar">
        ${micSupported && html`<button class=${"mic" + (recording ? " rec" : "")} title="Speak your question" onClick=${toggleMic}>${Icon.mic}</button>`}
        <input placeholder="Ask about admissions…" value=${input} onInput=${(e) => setInput(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && send()} />
        <button class="btn primary" disabled=${busy} onClick=${() => send()}>Send</button>
      </div>
      <p class="hint">${hint}</p>
    </div>`;
}

// ---------- Extension Controller ----------
function ExtensionPanel({ keys }) {
  const active = keys.filter((k) => k.active);
  const [keyVal, setKeyVal] = useState("");
  useEffect(() => { if (!keyVal && active.length) setKeyVal(active[0].key); }, [keys]);
  const key = keyVal || "(your active key)";
  const origin = window.location.origin;
  const snippet = `fetch('${origin}/api/chat', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': '${key}'
  },
  body: JSON.stringify({ question: 'What are the eligibility criteria?' })
})
  .then(r => r.json())
  .then(data => console.log(data.answerText, data.pageReferences));`;

  return html`
    <div class="panel">
      <h1>Extension Controller</h1>
      <p class="lead">What another app — the admission WebForms site, or the cross-product browser extension — needs to connect.</p>
      <div class="grid">
        <div class="info"><h3>Base URL</h3><code>${origin}</code><p>Same origin serves the chat widget, the API, and this console.</p></div>
        <div class="info"><h3>Chat endpoint</h3><code>POST /api/chat</code><p>Header <code>X-API-Key: (your key)</code>, body <code>{ "question": "..." }</code></p></div>
        <div class="info"><h3>Ingest endpoint</h3><code>POST /api/ingest</code><p><code>multipart/form-data</code> with the prospectus PDF. Same key header.</p></div>
        <div class="info"><h3>Integration options</h3><p>1. Call these URLs over HTTP (extension, any site).<br/>2. Reference <code>AdmissionAssistant.Core.dll</code> in-process (WebForms).</p></div>
      </div>
      <div class="snippet">
        <div class="head"><span>Extension fetch snippet</span>
          <select class="sel" value=${keyVal} onChange=${(e) => setKeyVal(e.target.value)}>
            ${active.length === 0 ? html`<option value="">No active keys</option>` : active.map((k) => html`<option key=${k.id} value=${k.key}>${k.label}</option>`)}
          </select>
        </div>
        <pre>${snippet}</pre>
      </div>
    </div>`;
}

// ---------- Sidebar: nav + projects + auth, one shell ----------
const TABS = [
  { id: "dashboard", label: "Dashboard", icon: Icon.dashboard },
  { id: "keys", label: "URL Generator", icon: Icon.link },
  { id: "tester", label: "Try It", icon: Icon.chat },
  { id: "ext", label: "Extension", icon: Icon.puzzle },
  { id: "cost", label: "Cost", icon: Icon.coin },
];

function Sidebar({
  tab, onTab, projects, selectedId, onSelect, onCreate, onDropFile, onDelete, toast,
  status, tokenInput, onTokenInput, onConnect,
}) {
  const [dragOverNew, setDragOverNew] = useState(false);
  const [dragOverId, setDragOverId] = useState(null);
  const fileInputs = useRef({});

  const onAgentDragStart = (e) => {
    e.dataTransfer.setData("text/x-agent", "admission-assistant");
    e.dataTransfer.effectAllowed = "copy";
  };

  const newProjectDrop = (e) => {
    e.preventDefault();
    setDragOverNew(false);
    if (!e.dataTransfer.types.includes("text/x-agent")) return;
    const name = prompt("Name this project (e.g. a college or department):");
    if (name && name.trim()) onCreate(name.trim());
  };

  const rowDrop = (e, id) => {
    e.preventDefault();
    setDragOverId(null);
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      onDropFile(id, e.dataTransfer.files[0]);
    } else if (e.dataTransfer.types.includes("text/x-agent")) {
      toast("Admission Assistant is already running on this project.");
    }
  };

  return html`
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-mark">A</span>
        <div><div class="brand-name">Admission Assistant</div><div class="brand-sub">Console</div></div>
      </div>

      <nav class="sidebar-nav">
        ${TABS.map((t) => html`
          <button key=${t.id} class=${tab === t.id ? "on" : ""} onClick=${() => onTab(t.id)}>${t.icon}${t.label}</button>`)}
      </nav>

      <div class="sidebar-divider"></div>

      <div class="sidebar-block">
        <div class="sidebar-label">Agents</div>
        <div class="agent-card" draggable="true" onDragStart=${onAgentDragStart} title="Drag onto a project">
          ${Icon.puzzle}<span>Admission Assistant</span>
        </div>
      </div>

      <div class="sidebar-block grow" style=${{ marginTop: 10 }}>
        <div class="sidebar-label">Projects</div>
        <div class="project-list">
          ${projects.map((p) => html`
            <div key=${p.id}
                 class=${"project-row" + (p.id === selectedId ? " on" : "") + (dragOverId === p.id ? " drag" : "")}
                 onClick=${() => onSelect(p.id)}
                 onDragOver=${(e) => { e.preventDefault(); setDragOverId(p.id); }}
                 onDragLeave=${() => setDragOverId(null)}
                 onDrop=${(e) => rowDrop(e, p.id)}>
              <div class="project-row-top">
                <span class="project-name">${p.name}</span>
                <button class="mini-btn" title="Upload prospectus"
                        onClick=${(e) => { e.stopPropagation(); fileInputs.current[p.id] && fileInputs.current[p.id].click(); }}>
                  ${Icon.upload}
                </button>
                <input type="file" accept="application/pdf" style=${{ display: "none" }}
                       ref=${(el) => { fileInputs.current[p.id] = el; }}
                       onClick=${(e) => e.stopPropagation()}
                       onChange=${(e) => { if (e.target.files[0]) onDropFile(p.id, e.target.files[0]); e.target.value = ""; }} />
                <button class="mini-btn" title="Delete project" onClick=${(e) => { e.stopPropagation(); onDelete(p.id, p.name); }}>${Icon.trash}</button>
              </div>
              <div class="project-row-status">
                ${p.prospectus.embedded
                  ? html`<span class="pill cache">embedded · ${p.prospectus.chunksIndexed} chunks</span>`
                  : html`<span class="pill">no prospectus yet</span>`}
                ${!p.allowCloud && html`<span class="pill" title="Cloud disabled — always uses the local model">local only</span>`}
              </div>
              <div class="project-row-cost">
                <span>${p.totalQuestions} asked</span>
                <span>${p.sarvamCalls} cloud</span>
                <span>${p.localCalls} local</span>
                <span>${p.cacheHits} cached</span>
              </div>
            </div>`)}
          <div class=${"project-row new-drop" + (dragOverNew ? " drag" : "")}
               onDragOver=${(e) => { e.preventDefault(); setDragOverNew(true); }}
               onDragLeave=${() => setDragOverNew(false)}
               onDrop=${newProjectDrop}
               onClick=${() => { const name = prompt("Project name:"); if (name && name.trim()) onCreate(name.trim()); }}>
            + New project
          </div>
        </div>
      </div>

      <div class="sidebar-auth">
        <div class="status-row">
          <span class=${"status-dot " + (status === "Connected" ? "ok" : status ? "err" : "idle")}></span>
          ${status || "Not connected"}
        </div>
        <input type="password" placeholder="Admin token" value=${tokenInput}
               onInput=${(e) => onTokenInput(e.target.value)} onKeyDown=${(e) => e.key === "Enter" && onConnect()} />
        <button class="btn primary" onClick=${onConnect}>Connect</button>
      </div>
    </aside>`;
}

function App() {
  const [tab, setTab] = useState("dashboard");
  const [token, setToken] = useState(localStorage.getItem(TOKEN_KEY) || "");
  const [tokenInput, setTokenInput] = useState(localStorage.getItem(TOKEN_KEY) || "");
  const [keys, setKeys] = useState([]);
  const [projects, setProjects] = useState([]);
  const [selectedProjectId, setSelectedProjectId] = useState(localStorage.getItem(PROJECT_KEY) || "");
  const [status, setStatus] = useState("");
  const [err, setErr] = useState("");
  const [toastMsg, setToastMsg] = useState("");

  const toast = useCallback((msg) => {
    setToastMsg(msg);
    setTimeout(() => setToastMsg((cur) => (cur === msg ? "" : cur)), 3000);
  }, []);

  const refresh = useCallback(async (t) => {
    const useToken = t !== undefined ? t : token;
    if (!useToken) return;
    try {
      const [keyData, projectData] = await Promise.all([
        api("/admin/keys", { token: useToken }),
        api("/admin/projects", { token: useToken }),
      ]);
      setKeys(keyData);
      setProjects(projectData);
      setStatus("Connected");
      setErr("");
      setSelectedProjectId((cur) => (cur && projectData.some((p) => p.id === cur) ? cur : (projectData[0] ? projectData[0].id : "")));
    } catch { setStatus("Invalid token"); setErr("Invalid token."); }
  }, [token]);

  useEffect(() => { if (token) refresh(token); }, []);
  useEffect(() => { if (selectedProjectId) localStorage.setItem(PROJECT_KEY, selectedProjectId); }, [selectedProjectId]);

  const connect = () => { localStorage.setItem(TOKEN_KEY, tokenInput); setToken(tokenInput); refresh(tokenInput); };

  const createProject = async (name) => {
    const entry = await api("/admin/projects", { method: "POST", token, body: { name } });
    await refresh();
    setSelectedProjectId(entry.id);
  };

  const deleteProject = async (id, name) => {
    if (!confirm(`Delete project "${name}"? Its prospectus, cache, keys, and stats are gone for good.`)) return;
    await api(`/admin/projects/${id}`, { method: "DELETE", token });
    await refresh();
  };

  const ingestPdf = async (projectId, file) => {
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(`/admin/projects/${projectId}/ingest`, {
        method: "POST", headers: { "X-Admin-Token": token }, body: form,
      });
      const d = await res.json();
      if (!res.ok) { toast(d.error || "Ingest failed."); return; }
      toast(d.skipped
        ? `Already up to date — ${d.chunksIndexed} chunks, no re-embed needed.`
        : `Re-embedded — ${d.chunksIndexed} chunks from ${d.pagesProcessed} pages.`);
      refresh();
    } catch { toast("Ingest failed. Check that the backend is running."); }
  };

  const projectKeys = keys.filter((k) => k.project_id === selectedProjectId);

  return html`
    <div class="shell">
      <${Sidebar} tab=${tab} onTab=${setTab}
         projects=${projects} selectedId=${selectedProjectId} onSelect=${setSelectedProjectId}
         onCreate=${createProject} onDropFile=${ingestPdf} onDelete=${deleteProject} toast=${toast}
         status=${status} tokenInput=${tokenInput} onTokenInput=${setTokenInput} onConnect=${connect} />
      <div class="content">
        ${toastMsg && html`<div class="toast">${toastMsg}</div>`}
        ${!selectedProjectId && html`<div class="panel"><h1>No project selected</h1><p class="lead">Connect with the admin token, then pick a project from the sidebar or drag the Admission Assistant agent onto "+ New project".</p></div>`}
        ${selectedProjectId && tab === "dashboard" && html`<${Dashboard} token=${token} projectId=${selectedProjectId} />`}
        ${selectedProjectId && tab === "keys" && html`<${KeysPanel} token=${token} projectId=${selectedProjectId} keys=${projectKeys} err=${err} onChange=${() => refresh()} />`}
        ${selectedProjectId && tab === "tester" && html`<${TesterPanel} keys=${projectKeys} />`}
        ${selectedProjectId && tab === "ext" && html`<${ExtensionPanel} keys=${projectKeys} />`}
        ${selectedProjectId && tab === "cost" && html`<${Cost} token=${token} projectId=${selectedProjectId} onChange=${() => refresh()} />`}
      </div>
    </div>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
