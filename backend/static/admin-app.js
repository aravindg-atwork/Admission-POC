const { useState, useRef, useEffect, useLayoutEffect, useCallback } = React;
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
  flag: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><path d="M5 17V3M5 3.5c1.5-1 3.5-1 5 0s3.5 1 5 0v8c-1.5 1-3.5 1-5 0s-3.5-1-5 0" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
  doc: html`<svg viewBox="0 0 20 20" width="15" height="15" fill="none"><path d="M6 2.5h6l3 3V17a.5.5 0 01-.5.5h-9a.5.5 0 01-.5-.5V3a.5.5 0 01.5-.5z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M7.5 8h5M7.5 11h5M7.5 14h3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>`,
  check: html`<svg viewBox="0 0 20 20" width="10" height="10" fill="none"><path d="M4 10.5l4 4 8-9" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
};

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
    const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}) }, body: JSON.stringify({ text, language: short }) });
    if (!res.ok) throw new Error(String(res.status));
    const blob = await res.blob(); const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    currentAudio.onended = () => { hooks.onEnd && hooks.onEnd(); URL.revokeObjectURL(url); };
    currentAudio.onerror = () => { hooks.onEnd && hooks.onEnd(); URL.revokeObjectURL(url); };
    await currentAudio.play();
  } catch (e) { hooks.onError && hooks.onError(e); speakBrowser(text, lang, hooks.onEnd); }
}

function useSpeechRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recRef = useRef(null);
  useEffect(() => { if (!SR) return; const r = new SR(); r.interimResults = false; r.maxAlternatives = 1; recRef.current = r; }, []);
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
    <div class="panel"><h1>Dashboard</h1><p class="lead">Live overview of the admission assistant — volume, cache effectiveness, and system health.</p>
      <div class="health-strip">
        <div class="health-item"><span class=${"status-dot "+(d.health.embedding==="up"?"ok":"err")}></span>Embeddings ${d.health.embedding}</div>
        <div class="health-item"><span class=${"status-dot "+(d.health.ollama==="up"?"ok":"err")}></span>Ollama ${d.health.ollama}</div>
        <div class="health-item"><span class=${"status-dot "+(d.health.sarvam==="configured"?"ok":"idle")}></span>Sarvam ${d.health.sarvam}</div>
        ${d.health.selfhosted ? html`<div class="health-item"><span class=${"status-dot "+(d.health.selfhosted==="up"?"ok":"err")}></span>Self-hosted ${d.health.selfhosted}</div>` : ""}
        ${d.health.hetzner ? html`<div class="health-item"><span class=${"status-dot "+(d.health.hetzner==="up"?"ok":"err")}></span>Hetzner ${d.health.hetzner}</div>` : ""}
      </div>
      <div class="stat-grid">
        <div class="stat-card"><div class="num">${d.totalQuestions}</div><div class="lbl">Questions answered</div></div>
        <div class="stat-card"><div class="num">${d.cacheHitRate}%</div><div class="lbl">Cache hit rate</div><div class="sub">${d.cacheHits} instant</div></div>
        <div class="stat-card"><div class="num">${d.avgLatencyMs?(d.avgLatencyMs/1000).toFixed(1)+"s":"—"}</div><div class="lbl">Avg response time</div></div>
        <div class="stat-card"><div class="num">${d.activeKeys}<span style=${{fontSize:"1rem",color:"var(--ink-3)"}}>/${d.totalKeys}</span></div><div class="lbl">Active keys</div></div>
      </div>
      <div class="section-h">Language mix</div>
      <div class="card" style=${{padding:"18px 20px"}}>
        <div class="lang-bars">${Object.entries(d.languages).map(([k,v])=>html`<div class="lang-bar-row" key=${k}><span class="lbl">${LANG_LABELS[k]||k}</span><div class="lang-bar-track"><div class="lang-bar-fill" style=${{width:Math.round(v/langTotal*100)+"%"}}></div><span class="cnt">${v}</span></div></div>`)}</div>
      </div>
      <div class="section-h">Recent activity</div>
      <div class="card activity">${d.recent.length===0?html`<div class="empty-hint">No questions answered yet.</div>`:d.recent.map((r,i)=>html`<div class="activity-row" key=${i}><span class="t">${timeAgo(r.ts)}</span><span class=${"pill "+(r.source==="faq-cache"?"cache":"src")}>${r.source==="faq-cache"?"⚡ cache":(r.model||"").replace("sarvam:","")}</span><span class="muted">${LANG_LABELS[r.language]||r.language}</span><span class="muted" style=${{marginLeft:"auto"}}>${(r.latencyMs/1000).toFixed(1)}s</span></div>`)}</div>
      ${d.catalogueCalls>0?html`<div class="section-h">Catalogue matching (order-assist extension)</div>`:""}
      ${d.catalogueCalls>0?html`<div class="card activity">
        <div class="activity-row"><span class="muted">${d.catalogueCalls} calls</span><span class="muted">${d.catalogueFailures} failed</span><span class="muted" style=${{marginLeft:"auto"}}>${d.catalogueFailureRate}% failure rate</span></div>
        ${d.catalogueRecentFailures.map((f,i)=>html`<div class="activity-row" key=${i}><span class="t">${timeAgo(f.ts)}</span><span class=${"pill src"}>${f.endpoint}</span><span class="muted">${f.error}</span></div>`)}
      </div>`:""}
    </div>`;
}

// ---------- Cost ----------
function Cost({ token, projectId, onChange }) {
  const [d, setD] = useState(null);
  const [watchUrl, setWatchUrl] = useState("");
  const [checking, setChecking] = useState(false);
  const [checkMsg, setCheckMsg] = useState("");
  const load = useCallback(() => { if (token && projectId) api(`/admin/projects/${projectId}/stats`,{token}).then(x=>{setD(x); setWatchUrl(x.prospectusWatch.url||"");}).catch(()=>{}); }, [token, projectId]);
  useEffect(() => { setD(null); setCheckMsg(""); load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  const clearCache = async () => { if (!confirm("Clear the FAQ cache? Future questions will re-run the full pipeline until re-cached.")) return; await api(`/admin/projects/${projectId}/cache/clear`,{method:"POST",token}); load(); };
  const toggleCloud = async () => { await api(`/admin/projects/${projectId}`,{method:"PATCH",token,body:{allow_cloud:!d.allowCloud}}); load(); onChange && onChange(); };
  const saveWatchUrl = async () => { if (watchUrl === d.prospectusWatch.url) return; await api(`/admin/projects/${projectId}`,{method:"PATCH",token,body:{prospectus_url:watchUrl}}); load(); };
  const toggleWatch = async () => { await api(`/admin/projects/${projectId}`,{method:"PATCH",token,body:{watch_enabled:!d.prospectusWatch.enabled}}); load(); };
  const checkNow = async () => {
    setChecking(true); setCheckMsg("");
    try {
      const r = await api(`/admin/projects/${projectId}/watch/check`,{method:"POST",token});
      setCheckMsg(r.changed ? `Source changed — re-ingested (${r.status}).`
        : r.checked ? `No change (${r.status||"same"}).`
        : (r.reason || "Not configured."));
      load(); onChange && onChange();
    } catch { setCheckMsg("Check failed."); } finally { setChecking(false); }
  };
  if (!token) return html`<div class="panel"><h1>Cost</h1><p class="lead">Connect with the admin token to view usage and cost exposure.</p></div>`;
  if (!d) return html`<div class="panel"><h1>Cost</h1><p class="lead">Loading…</p></div>`;
  const pct = Math.min(100, Math.round(d.sarvam.count/d.sarvam.limit*100)); const warn = pct >= 80;
  const w = d.prospectusWatch;
  return html`
    <div class="panel"><h1>Cost</h1><p class="lead">What this project's answers cost, and which model is allowed to answer them.</p>
      <div class="cap-bar-wrap">
        <div class="cap-bar-head"><span>Sarvam cloud calls today</span><span class="n">${d.sarvam.count} / ${d.sarvam.limit}</span></div>
        <div class="cap-track"><div class=${"cap-fill"+(warn?" warn":"")} style=${{width:pct+"%"}}></div></div>
      </div>
      <div class="section-h">This project's model policy</div>
      <div class="card">
        <div class="agent-row"><span class="agent-name"><span class="agent-dot" style=${{background:d.allowCloud?"var(--amber)":"var(--ink-3)"}}></span>Sarvam AI (cloud)</span><div class="agent-meta"><span class="agent-cost cloud">${d.allowCloud?"allowed":"disabled"}</span><span class="agent-count">${d.sarvamCalls}</span><button class=${"switch"+(d.allowCloud?" on":"")} onClick=${toggleCloud}></button></div></div>
        <div class="agent-row"><span class="agent-name"><span class="agent-dot" style=${{background:"var(--ink-3)"}}></span>Local model (Ollama)</span><div class="agent-meta"><span class="agent-cost free">$0</span><span class="agent-count">${d.localCalls}</span></div></div>
        <div class="agent-row"><span class="agent-name"><span class="agent-dot" style=${{background:"var(--accent)"}}></span>FAQ cache</span><div class="agent-meta"><span class="agent-cost free">$0</span><span class="agent-count">${d.cacheHits}</span></div></div>
      </div>
      <div class="section-h">Prospectus auto-refresh</div>
      <div class="card" style=${{padding:"16px 20px"}}>
        <div class="info-row"><label>Source URL (direct link to the live prospectus PDF)</label><input value=${watchUrl} onInput=${e=>setWatchUrl(e.target.value)} onBlur=${saveWatchUrl} placeholder="https://college.edu/prospectus.pdf"/></div>
        <div class="agent-row"><span class="agent-name">Watch for changes</span><div class="agent-meta"><span class="agent-cost">${w.enabled?"on":"off"}</span><button class=${"switch"+(w.enabled?" on":"")} onClick=${toggleWatch}></button></div></div>
        <div class="agent-row"><span class="agent-name">Last checked</span><div class="agent-meta"><span class="muted">${w.lastCheckedAt?timeAgo(new Date(w.lastCheckedAt).getTime()/1000)+(w.lastStatus?` · ${w.lastStatus}`:""):"never"}</span></div></div>
        ${w.lastRefreshedAt?html`<div class="agent-row"><span class="agent-name">Last re-ingested</span><div class="agent-meta"><span class="muted">${timeAgo(new Date(w.lastRefreshedAt).getTime()/1000)}</span></div></div>`:""}
        ${w.lastError?html`<p class="hint" style=${{margin:"8px 0 0",color:"var(--danger)"}}>${w.lastError}</p>`:""}
        <div class="actions" style=${{marginTop:12}}><button class="btn sm" disabled=${checking} onClick=${checkNow}>${checking?"Checking…":"Check now"}</button><span style=${{fontSize:12.5,color:"var(--ink-3)",marginLeft:12}}>${checkMsg}</span></div>
      </div>
      <div class="section-h">Cache</div>
      <div class="card" style=${{padding:"16px 18px",display:"flex",alignItems:"center",justifyContent:"space-between"}}><div><div style=${{fontSize:14,fontWeight:500}}>${d.cacheHits} instant answers, ${d.cacheHitRate}% hit rate</div></div><button class="btn danger" onClick=${clearCache}>Clear cache</button></div>
    </div>`;
}

// ---------- Flagged answers (dislikes) ----------
// Every dislike lands here (see faq.apply_feedback) whether or not it got
// pulled from the cache - a plain auto-cached guess is removed immediately
// on a dislike, but a seeded/trusted/verified entry stays served and is
// only flagged for review, on the theory that one click is too noisy a
// signal to override an admin's curation or the system's own deterministic
// table-lookup confirmation on its own (see rag.py's cache-hit re-check).
// The pills below are what let an admin tell those apart at a glance,
// instead of re-deriving it from raw booleans each time.
const _RESOLUTION_LABELS = {
  open: "open", dismissed: "dismissed - answer was fine",
  corrected: "corrected", "rule-changed": "fixed at the rule level",
};

function FlaggedPanel({ token, projectId }) {
  const [items, setItems] = useState(null);
  const load = useCallback(() => {
    if (token && projectId) api(`/admin/projects/${projectId}/flagged`, { token }).then(setItems).catch(() => {});
  }, [token, projectId]);
  useEffect(() => { setItems(null); load(); }, [load]);

  const resolve = async (flagId, resolution) => {
    const note = resolution === "open" ? "" : (prompt(`Note for "${_RESOLUTION_LABELS[resolution]}" (optional):`) || "");
    await api(`/admin/projects/${projectId}/flagged/${flagId}`, { method: "PATCH", token, body: { resolution, note } });
    load();
  };

  if (!token) return html`<div class="panel"><h1>Flagged</h1><p class="lead">Connect with the admin token to review disliked answers.</p></div>`;
  if (!items) return html`<div class="panel"><h1>Flagged</h1><p class="lead">Loading…</p></div>`;

  return html`
    <div class="panel"><h1>Flagged</h1><p class="lead">Answers a student disliked, newest first. A pill shows why it was kept (or that it was pulled) so you can tell a genuine wrong answer from noise.</p>
      ${items.length === 0 && html`<div class="card" style=${{padding:"20px",color:"var(--ink-3)"}}>No flagged answers yet.</div>`}
      ${items.slice().reverse().map((it) => html`
        <div class="card" key=${it.flag_id || it.id + "_" + it.flagged_at} style=${{padding:"14px 18px",marginBottom:10}}>
          <div style=${{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:12}}>
            <div style=${{fontWeight:600,fontSize:14}}>${it.question}</div>
            <span style=${{fontSize:11.5,color:"var(--ink-3)",whiteSpace:"nowrap"}}>${timeAgo(it.flagged_at)}</span>
          </div>
          <div style=${{fontSize:13,color:"var(--ink-2)",margin:"6px 0"}}>${it.answer}</div>
          <div class="project-row-status">
            ${it.was_verified && html`<span class="pill cache" title=${"Table-confirmed: "+it.verified_figure}>verified figure kept</span>`}
            ${it.was_seeded && html`<span class="pill src">admin-seeded, kept</span>`}
            ${it.was_trusted && !it.was_seeded && html`<span class="pill src">earlier liked, kept</span>`}
            ${it.removed_from_cache
              ? html`<span class="pill" style=${{color:"var(--danger)",borderColor:"var(--danger)"}}>removed from cache</span>`
              : !(it.was_verified || it.was_seeded || it.was_trusted) && html`<span class="pill">kept</span>`}
            ${it.pages.length > 0 && html`<span class="pill">pages ${it.pages.join(", ")}</span>`}
            ${it.resolution && it.resolution !== "open" && html`<span class="pill cache" title=${it.resolution_note || ""}>${_RESOLUTION_LABELS[it.resolution] || it.resolution}</span>`}
          </div>
          ${(!it.resolution || it.resolution === "open") && it.flag_id && html`
            <div class="actions" style=${{marginTop:10,display:"flex",gap:8}}>
              <button class="btn sm" onClick=${() => resolve(it.flag_id, "dismissed")}>Dismiss (was fine)</button>
              <button class="btn sm" onClick=${() => resolve(it.flag_id, "corrected")}>Mark corrected</button>
              <button class="btn sm" onClick=${() => resolve(it.flag_id, "rule-changed")}>Fixed at rule level</button>
            </div>`}
        </div>`)}
    </div>`;
}

// ---------- Review: the system's own self-detected near-misses ----------
// Distinct from FlaggedPanel above (student dislikes only) - this surfaces
// a validation FAIL/regeneration even on a day no student happened to
// click dislike, per the 2026-08-12 orchestration/validation plan.
function ReviewPanel({ token, projectId }) {
  const [summary, setSummary] = useState(null);
  const [log, setLog] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [learned, setLearned] = useState(null);
  const [wordInputs, setWordInputs] = useState({});
  const load = useCallback(() => {
    if (!token || !projectId) return;
    api(`/admin/projects/${projectId}/review-summary`, { token }).then(setSummary).catch(() => {});
    api(`/admin/projects/${projectId}/review-log`, { token }).then(setLog).catch(() => {});
    api(`/admin/projects/${projectId}/suggestions`, { token }).then(setSuggestions).catch(() => {});
    api("/admin/learned-discriminators", { token }).then(setLearned).catch(() => {});
  }, [token, projectId]);
  useEffect(() => { setSummary(null); setLog(null); setSuggestions(null); setLearned(null); load(); }, [load]);

  const applySafe = async (pattern) => {
    const [group, canonical] = (pattern.signature[0] || ["", [""]]);
    const word = (wordInputs[JSON.stringify(pattern.signature)] || "").trim();
    if (!word) { alert("Type the synonym word to add first."); return; }
    await api(`/admin/projects/${projectId}/suggestions/apply`, {
      method: "POST", token,
      body: { group, canonical: canonical[0], word, signature: pattern.signature, count: pattern.count },
    });
    load();
  };
  const revertLearned = async (id) => { await api(`/admin/learned-discriminators/${id}`, { method: "DELETE", token }); load(); };

  if (!token) return html`<div class="panel"><h1>Review</h1><p class="lead">Connect with the admin token to see self-detected validation events.</p></div>`;
  if (!summary || !log || !suggestions || !learned) return html`<div class="panel"><h1>Review</h1><p class="lead">Loading…</p></div>`;

  return html`
    <div class="panel"><h1>Review</h1><p class="lead">Answers the system itself flagged during validation - a numeric claim not grounded in the excerpts, or a reply that drifted off-topic - whether or not a student happened to dislike it. See the Flagged tab for student-reported issues.</p>
      <div class="stat-grid">
        <div class="stat-card"><div class="num">${summary.reviewLogTotal}</div><div class="lbl">Validation flags</div></div>
        <div class="stat-card"><div class="num">${summary.reviewLogRegenerated}</div><div class="lbl">Auto-regenerated</div></div>
        <div class="stat-card"><div class="num">${summary.flaggedOpen}</div><div class="lbl">Open student flags</div><div class="sub">${summary.flaggedTotal} total</div></div>
      </div>
      ${Object.keys(summary.reasonCounts).length > 0 && html`
        <div class="section-h">Recurring reasons</div>
        <div class="card" style=${{padding:"14px 18px"}}>
          ${Object.entries(summary.reasonCounts).map(([reason, count]) => html`
            <div key=${reason} style=${{display:"flex",justifyContent:"space-between",fontSize:13,padding:"4px 0"}}>
              <span>${reason}</span><span class="pill">${count}</span>
            </div>`)}
        </div>`}

      <div class="section-h">Recurring flag patterns - safe to fix directly</div>
      <p class="lead" style=${{fontSize:12.5}}>An existing FAQ-cache discriminator just needs one more synonym word - can only make matching MORE conservative, never cause a wrong cache hit.</p>
      ${suggestions.safeToAutomate.length === 0 && html`<div class="card" style=${{padding:"16px",color:"var(--ink-3)"}}>No recurring patterns yet.</div>`}
      ${suggestions.safeToAutomate.map((p, i) => html`
        <div class="card" key=${i} style=${{padding:"12px 16px",marginBottom:8}}>
          <div style=${{fontSize:13,fontWeight:600}}>${p.signature.map(([g,v]) => `${g}=${v.join("/")}`).join(", ")} <span class="pill">${p.count}×</span></div>
          <div style=${{fontSize:12,color:"var(--ink-3)",margin:"4px 0"}}>${p.sampleQuestions.slice(0,3).join(" · ")}</div>
          <div style=${{display:"flex",gap:8,marginTop:6}}>
            <input placeholder="synonym word to add" style=${{flex:1,fontSize:12.5}}
                   value=${wordInputs[JSON.stringify(p.signature)] || ""}
                   onInput=${e => setWordInputs({...wordInputs, [JSON.stringify(p.signature)]: e.target.value})} />
            <button class="btn sm" onClick=${() => applySafe(p)}>Apply</button>
          </div>
        </div>`)}

      ${suggestions.proposeOnly.length > 0 && html`
        <div class="section-h">Other suggestions - needs a human look</div>
        ${suggestions.proposeOnly.map((s, i) => html`
          <div class="card" key=${i} style=${{padding:"12px 16px",marginBottom:8,fontSize:13,color:"var(--ink-2)"}}>${s.summary}</div>`)}`}

      ${learned.length > 0 && html`
        <div class="section-h">Learned discriminators (applied)</div>
        ${learned.map(e => html`
          <div class="card" key=${e.id} style=${{padding:"10px 16px",marginBottom:6,display:"flex",justifyContent:"space-between",alignItems:"center",fontSize:13}}>
            <span><span class="pill">${e.group}</span> ${e.canonical} += "${e.word}"</span>
            <button class="mini-btn warn" title="Revert" onClick=${() => revertLearned(e.id)}>${Icon.trash}</button>
          </div>`)}`}

      <div class="section-h">Recent events</div>
      ${log.length === 0 && html`<div class="card" style=${{padding:"20px",color:"var(--ink-3)"}}>No validation events logged yet.</div>`}
      ${log.slice(0, 50).map((e, i) => html`
        <div class="card" key=${i} style=${{padding:"10px 16px",marginBottom:8,fontSize:13}}>
          <div style=${{display:"flex",justifyContent:"space-between"}}>
            <span><span class="pill">${e.kind}</span> from <span class="pill">${e.source}</span></span>
            <span style=${{fontSize:11.5,color:"var(--ink-3)"}}>${timeAgo(e.ts)}</span>
          </div>
          <div style=${{color:"var(--ink-2)",marginTop:4}}>${(e.reasons || []).join("; ")}</div>
        </div>`)}
    </div>`;
}

// ---------- API Keys ----------
function KeysPanel({ token, projectId, keys, onChange, err }) {
  const [label, setLabel] = useState(""); const [busy, setBusy] = useState(false);
  const generate = async () => { setBusy(true); try { await api("/admin/keys",{method:"POST",token,body:{label,project_id:projectId}}); setLabel(""); onChange(); } finally { setBusy(false); } };
  const toggle = async (k) => { await api(`/admin/keys/${k.id}`,{method:"PATCH",token,body:{active:!k.active}}); onChange(); };
  const del = async (k) => { if (!confirm(`Delete "${k.label}"?`)) return; await api(`/admin/keys/${k.id}`,{method:"DELETE",token}); onChange(); };
  const copy = (v, e) => { navigator.clipboard.writeText(v); const t=e.target; const old=t.textContent; t.textContent="copied"; setTimeout(()=>t.textContent=old,1200); };
  return html`
    <div class="panel"><h1>URL Generator</h1><p class="lead">One URL, many keys. Each consumer gets its own key so any one can be deactivated without affecting the others.</p>
      <div class="create"><input placeholder="Label, e.g. browser-extension" value=${label} onInput=${e=>setLabel(e.target.value)} onKeyDown=${e=>e.key==="Enter"&&generate()}/><button class="btn primary" disabled=${busy||!token} onClick=${generate}>Generate key</button></div>
      <div class="card">${!token?html`<div class="empty-hint">Connect with the admin token.</div>`:err?html`<div class="empty-hint">${err}</div>`:keys.length===0?html`<div class="empty-hint">No keys yet.</div>`:html`<table class="keys"><thead><tr><th>Label</th><th>Key</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>${keys.map(k=>html`<tr key=${k.id}><td>${k.label}</td><td><span class="kv"><code title=${k.key}>${k.key}</code><button class="copy" onClick=${e=>copy(k.key,e)}>copy</button></span></td><td><span class=${"badge "+(k.active?"on":"off")}>${k.active?"Active":"Inactive"}</span></td><td class="muted">${new Date(k.created_at).toLocaleDateString()}</td><td><div class="acts"><button class="btn sm" onClick=${()=>toggle(k)}>${k.active?"Deactivate":"Activate"}</button><button class="btn sm danger" onClick=${()=>del(k)}>Delete</button></div></td></tr>`)}</tbody></table>`}</div>`;
}

// ---------- Live: composer + real-time reasoning trace (Request 3) ----------
// Absorbs the old "Try It" tester (same composer, same /api/chat call) and
// pairs it with a live EventSource feed of EVERY real /api/chat request
// system-wide - not just this admin's own test messages - see
// backend/trace/hub.py's module docstring for the deliberate live-only,
// never-persisted design.
const _TRACE_STEP_LABEL = {
  guard: "Guard", intent_router: "Intent", model_routing: "Model allotter", cache_lookup: "Cache lookup", routing: "Routing",
  retrieval: "Retrieval", table_lookup: "Table lookup", generation: "Generation",
  validation: "Validation", final_answer: "Final answer",
};

function TraceEventRow({ event }) {
  const { step, detail } = event;
  const label = _TRACE_STEP_LABEL[step] || step;
  if (step === "intent_router") {
    if (!detail.available) {
      return html`<div class="trace-row"><span class="trace-dot guard-fired"></span>
        <span class="trace-label">${label}</span>
        <span class="pill guard-fired">keyword fallback</span>
        <span class="muted">${detail.reason}</span></div>`;
    }
    return html`<div class="trace-row-block">
      <div class="trace-row"><span class="trace-dot routing"></span>
        <span class="trace-label">${label}</span>
        <span class="pill src">${detail.intent}</span>
        ${detail.reused ? html`<span class="pill" title="Carried over from the redirecting request - no second model call">reused</span>` : ""}
        ${detail.confidence === "low" ? html`<span class="pill guard-fired">low confidence</span>` : ""}
        ${(detail.targetPrograms || []).length ? html`<span class="pill program">${detail.targetPrograms.join(", ")}</span>` : ""}
        ${detail.isComparison ? html`<span class="pill">comparison</span>` : ""}
        ${detail.needsProgramClarification ? html`<span class="pill">needs program</span>` : ""}
      </div>
      ${detail.resolvedQuestion ? html`<div class="context-cards"><div class="context-card">
        <span class="pill">understood as</span>${detail.resolvedQuestion}</div></div>` : ""}
    </div>`;
  }
  if (step === "model_routing") {
    const fast = detail.lane === "fast";
    return html`<div class="trace-row">
      <span class=${"trace-dot" + (fast ? " cache" : "")}></span>
      <span class="trace-label">${label}</span>
      <span class=${"pill" + (fast ? " cache" : "")}>${fast ? "fast" : "quality"}</span>
      <span class="pill src">${detail.provider}</span>
      <span class="muted">${detail.reason}</span></div>`;
  }
  if (step === "guard") {
    const name = (detail.name || "").replace(/^_/, "").replace(/_guard$/, "").replace(/_/g, " ");
    return html`<div class="trace-row">
      ${detail.fired
        ? html`<span class="trace-dot guard-fired"></span>`
        : html`<span class="trace-check">${Icon.check}</span>`}
      <span class="trace-label">${name}</span>
      <span class=${"pill" + (detail.fired ? " guard-fired" : "")}>${detail.fired ? "fired" : "passed"}</span></div>`;
  }
  if (step === "cache_lookup") {
    return html`<div class="trace-row"><span class="trace-dot cache"></span>
      <span class="trace-label">${label}</span>
      <span class=${"pill" + (detail.hit ? " cache" : "")}>${detail.hit ? (detail.verified ? "verified hit" : "hit") : "miss"}</span></div>`;
  }
  if (step === "routing") {
    return html`<div class="trace-row"><span class="trace-dot routing"></span>
      <span class="trace-label">${label}</span><span class="pill">${detail.decision}</span>
      ${detail.subtopics ? html`<span class="muted">${detail.subtopics.length} sub-topics</span>` : ""}
      ${detail.targetPrograms ? html`<span class="muted">${detail.targetPrograms.join(", ")}</span>` : ""}</div>`;
  }
  if (step === "retrieval") {
    return html`<div class="trace-row-block">
      <div class="trace-row"><span class="trace-dot retrieval"></span><span class="trace-label">${label} — top ${detail.topK}</span></div>
      <div class="context-cards">${(detail.chunks || []).slice(0, 6).map((c, i) => html`
        <div class="context-card" key=${i}><span class="pill">p.${c.page}</span>${c.snippet}</div>`)}</div>
    </div>`;
  }
  if (step === "table_lookup") {
    return html`<div class="trace-row"><span class="trace-dot table"></span>
      <span class="trace-label">${label}</span>
      <span class=${"pill" + (detail.matched ? " cache" : "")}>${detail.matched ? `${detail.descriptor}: ${detail.value}` : "no match"}</span></div>`;
  }
  if (step === "generation") {
    return html`<div class="trace-row"><span class="trace-dot generation pulse"></span>
      <span class="trace-label">${label}</span><span class="pill src">${detail.model}</span>
      <span class="muted">${detail.promptId}</span></div>`;
  }
  if (step === "validation") {
    const failed = detail.reasons && detail.reasons.length > 0;
    return html`<div class="trace-row"><span class="trace-dot validation"></span>
      <span class="trace-label">${label}</span>
      <span class=${"pill" + (failed ? " validation-fail" : "")}>${failed ? detail.reasons.join(", ") : "clean"}</span>
      ${detail.regenerated ? html`<span class="pill guard-fired">regenerated</span>` : ""}</div>`;
  }
  if (step === "final_answer") {
    return html`<div class="trace-row-block">
      <div class="trace-row"><span class="trace-dot final"></span><span class="trace-label">${label}</span><span class="pill">${detail.source}</span></div>
      <div class="context-card final-answer-card">${detail.answer}</div>
    </div>`;
  }
  return null;
}

// One step, expandable. Clicking shows the full detail the backend recorded
// for that step - the retrieved chunks and their scores, the validator's
// reasons, the router's resolved question, the prompt id that was used.
// Asked for directly: the summary line alone does not let you see what the
// agent had in front of it when it decided something.
function TraceStep({ event }) {
  const [open, setOpen] = useState(false);
  const detail = event.detail || {};
  const hasDetail = Object.keys(detail).length > 0;
  return html`
    <div class="trace-step">
      <div class=${"trace-step-head" + (hasDetail ? " clickable" : "")}
           onClick=${() => hasDetail && setOpen(!open)}
           title=${hasDetail ? "Click to see what this step worked with" : ""}>
        <${TraceEventRow} event=${event} />
        ${hasDetail ? html`<span class="trace-step-toggle">${open ? "\u2212" : "+"}</span>` : ""}
      </div>
      ${open ? html`<pre class="trace-step-detail">${JSON.stringify(detail, null, 2)}</pre>` : ""}
    </div>`;
}

// Which phase of the pipeline a step belongs to. The trace is a workflow,
// not a flat log, and reading it as one was the whole point of building it -
// but 15 undifferentiated rows, ten of which just say "passed", buries the
// two or three that actually decided the answer.
const _PHASES = [
  { id: "understand", label: "Understand", steps: ["intent_router"] },
  { id: "route", label: "Route", steps: ["guard", "model_routing", "routing"] },
  { id: "retrieve", label: "Retrieve", steps: ["cache_lookup", "retrieval", "table_lookup"] },
  { id: "answer", label: "Answer", steps: ["generation", "validation", "provenance", "citation", "final_answer"] },
];

function _phaseOf(step) {
  const hit = _PHASES.find((p) => p.steps.includes(step));
  return hit ? hit.id : "answer";
}

// The guards that did nothing, folded into one line. Ten rows of "passed" is
// noise; what matters is that they all passed, and WHICH one fired when one
// does. Expandable, so nothing is actually hidden.
function GuardSummary({ events }) {
  const [open, setOpen] = useState(false);
  const fired = events.filter((e) => e.detail && e.detail.fired);
  const passed = events.length - fired.length;
  if (events.length === 0) return null;
  return html`
    <div class="trace-step">
      <div class="trace-step-head clickable" onClick=${() => setOpen(!open)}>
        <div class="trace-row">
          <span class="trace-check">${Icon.check}</span>
          <span class="trace-label">${passed} guard${passed === 1 ? "" : "s"} passed</span>
          ${fired.map((e) => html`<span class="pill guard-fired" key=${e.detail.name}>
            ${(e.detail.name || "").replace(/^_/, "").replace(/_guard$/, "").replace(/_/g, " ")} fired</span>`)}
        </div>
        <span class="trace-step-toggle">${open ? "\u2212" : "+"}</span>
      </div>
      ${open ? html`<div class="trace-guard-list">
        ${events.map((e, i) => html`<${TraceStep} key=${i} event=${e} />`)}
      </div>` : ""}
    </div>`;
}

function TraceCard({ trace, programNames }) {
  const [open, setOpen] = useState(true);
  const [, tick] = useState(0);
  useEffect(() => {
    if (trace.done) return;
    const t = setInterval(() => tick((x) => x + 1), 400);
    return () => clearInterval(t);
  }, [trace.done]);
  const firstTs = trace.events[0] && trace.events[0].ts;
  const lastTs = trace.events[trace.events.length - 1] && trace.events[trace.events.length - 1].ts;
  const elapsed = firstTs ? (trace.done ? lastTs - firstTs : Date.now() / 1000 - firstTs) : 0;
  const final = trace.events.find((e) => e.step === "final_answer");

  // Group into phases, keeping arrival order inside each.
  const grouped = _PHASES.map((phase) => ({
    phase,
    events: trace.events.filter((e) => _phaseOf(e.step) === phase.id),
  })).filter((g) => g.events.length > 0);

  return html`
    <div class=${"card trace-card" + (trace.done ? "" : " running")}>
      <div class="trace-card-head" onClick=${() => setOpen(!open)}>
        <span class="pill program">${(programNames && programNames[trace.projectId]) || trace.projectId}</span>
        ${trace.done
          ? html`<span class="trace-status" style=${{ animation: "fade-in 300ms ease-out both" }}>Thought for ${elapsed.toFixed(1)}s</span>`
          : html`<span class="trace-status shimmer-text">Thinking…</span>`}
        ${final ? html`<span class="pill src">${final.detail.source}</span>` : ""}
        <span class="trace-toggle" style=${{ transform: open ? "rotate(0)" : "rotate(-90deg)" }}>▾</span>
      </div>
      ${open ? html`<div class="trace-body">
        ${grouped.map(({ phase, events }) => html`
          <div class="trace-phase" key=${phase.id}>
            <div class="trace-phase-label">${phase.label}</div>
            <div class="trace-rail">
              ${phase.id === "route"
                ? html`
                    <${GuardSummary} events=${events.filter((e) => e.step === "guard")} />
                    ${events.filter((e) => e.step !== "guard").map((e, i) => html`<${TraceStep} key=${i} event=${e} />`)}`
                : events.map((e, i) => html`<${TraceStep} key=${i} event=${e} />`)}
            </div>
          </div>`)}
      </div>` : ""}
    </div>`;
}

function LiveTraceFeed({ token, programNames }) {
  const [traces, setTraces] = useState({});
  const [order, setOrder] = useState([]);

  useEffect(() => {
    if (!token) return;
    const es = new EventSource(`/admin/trace/stream?token=${encodeURIComponent(token)}`);
    es.onmessage = (e) => {
      let event;
      try { event = JSON.parse(e.data); } catch { return; }
      setTraces((prev) => {
        const existing = prev[event.traceId] || { traceId: event.traceId, projectId: event.projectId, events: [], done: false };
        return { ...prev, [event.traceId]: { ...existing, events: [...existing.events, event], done: existing.done || event.step === "final_answer" } };
      });
      setOrder((prev) => (prev.includes(event.traceId) ? prev : [event.traceId, ...prev]).slice(0, 15));
    };
    es.onerror = () => {}; // browser auto-reconnects; nothing to surface
    return () => es.close();
  }, [token]);

  return html`
    <div class="live-trace">
      <div class="section-h">Live reasoning trace <span class="muted" style=${{fontWeight:400}}>— every real question, system-wide</span></div>
      ${order.length === 0 ? html`<div class="empty-hint">Waiting for a question to come in…</div>` : ""}
      ${order.map((tid) => html`<${TraceCard} key=${tid} trace=${traces[tid]} programNames=${programNames} />`)}
    </div>`;
}

// ---------- Prompts: the master system prompts, byte-for-byte (Request 3.1) ----------
function PromptsPanel({ token, projectId }) {
  const [prompts, setPrompts] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const load = useCallback(() => {
    if (!token) return;
    const qs = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    api(`/admin/prompts${qs}`, { token }).then((d) => setPrompts(d.prompts)).catch(() => {});
  }, [token, projectId]);
  useEffect(() => { setPrompts(null); load(); }, [load]);

  if (!token) return html`<div class="panel"><h1>Prompts</h1><p class="lead">Connect with the admin token to see the master prompts.</p></div>`;
  if (!prompts) return html`<div class="panel"><h1>Prompts</h1><p class="lead">Loading…</p></div>`;

  return html`
    <div class="panel"><h1>Prompts</h1><p class="lead">Exactly what gets sent to the LLM for this project - the full text, not a summary. Templated prompts are rendered with this project's own name filled in.</p>
      ${prompts.map((p) => html`
        <div class="card prompt-card" key=${p.id}>
          <div class="prompt-card-head" onClick=${() => setExpandedId(expandedId === p.id ? null : p.id)}>
            <span class="prompt-name">${p.name}</span>
            <span class="muted">${p.usedBy}</span>
            <span class="pill">${p.text.length.toLocaleString()} chars</span>
            <span class="trace-toggle">${expandedId === p.id ? "▾" : "▸"}</span>
          </div>
          ${expandedId === p.id ? html`<pre class="prompt-text">${p.text}</pre>` : ""}
        </div>`)}
    </div>`;
}

// ---------- Try It (legacy name kept as internal function name for the composer half) ----------
function TesterPanel({ keys, token, projectName, projectId, programNames }) {
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
  // Mirrors the student widget's own follow-up handling (see app.js) so the
  // tester reproduces real behavior rather than a subtly different one -
  // answering a clarification here must resolve exactly as it does live.
  const pendingClarifyRef = useRef(null);

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
    if (!keyVal) { alert("No active key selected. Generate or activate one in the API Keys tab first."); return; }
    const pendingClarification = pendingClarifyRef.current;
    pendingClarifyRef.current = null;
    setMessages((m) => [...m, { role: "user", text: q }, { role: "thinking" }]);
    setInput("");
    setBusy(true);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": keyVal },
        // uiLanguage matters: without it the backend has no explicit
        // language signal from the client (see rag/helpers.py's
        // _english_reply_hint), so the tester was not reproducing what the
        // real widget - which always sends it - actually does.
        body: JSON.stringify({
          question: q,
          uiLanguage: TTS_LANG_MAP[lang] || "en",
          // Prior turns, so the router can resolve a follow-up ("btech")
          // against what was already asked. Only real exchanged text - the
          // transient thinking/error placeholders carry no meaning.
          history: messages
            .filter((x) => (x.role === "user" || x.role === "bot") && x.text)
            .slice(-8)
            .map((x) => ({ role: x.role === "user" ? "user" : "assistant", text: x.text })),
          ...(pendingClarification ? { pendingClarification } : {}),
        }),
      });
      if (res.status === 401) { setMessages((m) => [...m.slice(0, -1), { role: "err", text: "401 Unauthorized — that key is inactive or invalid." }]); return; }
      const d = await res.json();
      if (d.clarifyOptions) pendingClarifyRef.current = { originalQuestion: q };
      setMessages((m) => [...m.slice(0, -1), { role: "bot", text: d.answerText, pages: d.pageReferences, model: d.model, source: d.source, clarifyOptions: d.clarifyOptions || null }]);
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
    <div class="panel live-panel">
      <h1>Live</h1>
      <p class="lead">Send a question through a selected key, and watch every guard, retrieval, and generation step happen on the right - the same live feed shows every OTHER real question hitting the backend right now too, not just this one.</p>
      <div class="live-split">
        <div class="live-tester">
          <div class="testing-as">
            <span class="testing-as-label">Testing as</span>
            <span class="testing-as-program">${projectName}</span>
            <span class="muted">answers come from this program's prospectus only</span>
          </div>
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
              // Program-clarification prompt: same chips the student widget
              // shows (see app.js's Message). Without these the tester had no
              // way to answer "which program?" except typing the name, which
              // is exactly the path that used to lose the original question.
              if (m.clarifyOptions) return html`<div class="row bot" key=${i}><div>
                <div class="bubble">${m.text}</div>
                <div class="chips" style=${{marginTop:8}}>
                  ${m.clarifyOptions.map((o) => html`
                    <button class="chip" key=${o.projectId} disabled=${busy}
                            onClick=${() => send(o.label)}>${o.label}</button>`)}
                </div></div></div>`;
              return html`<div class="row bot" key=${i}><div><div class="bubble">${m.text}</div>
                <div class="meta">
                  ${/* Page pills removed alongside the student widget's (see
                        app.js) so the tester keeps showing what a student
                        actually sees. Retrieved pages remain visible in the
                        Live trace's Retrieval step, which is the right place
                        for them in an operator console. */ ""}
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
        </div>
        <${LiveTraceFeed} token=${token} programNames=${programNames} />
      </div>
    </div>`;
}

// ---------- Sidebar: nav + projects + auth, one shell ----------
const TABS = [
  { id: "tester", label: "Live", icon: Icon.chat },
  { id: "prompts", label: "Prompts", icon: Icon.doc },
  { id: "dashboard", label: "Dashboard", icon: Icon.dashboard },
  { id: "cost", label: "Cost", icon: Icon.coin },
  { id: "flagged", label: "Flagged", icon: Icon.flag },
  { id: "review", label: "Review", icon: Icon.flag },
  { id: "keys", label: "API Keys", icon: Icon.link },
];

function Sidebar({
  tab, onTab, projects, selectedId, onSelect, onCreate, onDropFile, onDelete, toast,
  status, tokenInput, onTokenInput, onConnect,
}) {
  const [dragOverNew, setDragOverNew] = useState(false);
  const [dragOverId, setDragOverId] = useState(null);
  const fileInputs = useRef({});
  const [hoveredTab, setHoveredTab] = useState(null);
  const [navBox, setNavBox] = useState(null);
  const navRef = useRef(null);
  const tabRefs = useRef({});

  // Sliding highlight pill, not a static per-button background - tracks
  // whichever tab is hovered, falling back to the active one so there's
  // always exactly one lit up. Measured via getBoundingClientRect rather
  // than CSS-only positioning since button heights/order come from TABS,
  // not fixed values.
  useLayoutEffect(() => {
    const container = navRef.current;
    const target = tabRefs.current[hoveredTab ?? tab];
    if (!container || !target) return;
    const containerRect = container.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    setNavBox({ top: targetRect.top - containerRect.top, height: targetRect.height });
  }, [hoveredTab, tab]);

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

      <nav class="sidebar-nav" ref=${navRef} onMouseLeave=${() => setHoveredTab(null)}>
        <span class="sidebar-nav-highlight" aria-hidden="true" style=${{
          top: navBox ? navBox.top : 0, height: navBox ? navBox.height : 0, opacity: navBox ? 1 : 0,
        }}></span>
        ${TABS.map((t) => html`
          <button key=${t.id}
                  ref=${(el) => { tabRefs.current[t.id] = el; }}
                  class=${tab === t.id ? "on" : ""}
                  onMouseEnter=${() => setHoveredTab(t.id)}
                  onFocus=${() => setHoveredTab(t.id)}
                  onBlur=${() => setHoveredTab(null)}
                  onClick=${() => onTab(t.id)}>${t.icon}${t.label}</button>`)}
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
  const [tab, setTab] = useState("tester");
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
  // id -> display name, so the Live trace can label a card "B.F.Sc." rather
  // than the raw project id. Matters most for the sub-traces a cross-program
  // comparison or a program redirect spawns, which otherwise read as
  // unrelated questions appearing out of nowhere.
  const programNames = {};
  projects.forEach((p) => { programNames[p.id] = p.name; });

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
        ${selectedProjectId && tab === "tester" && html`<${TesterPanel} keys=${projectKeys} token=${token}
           projectName=${(projects.find((p) => p.id === selectedProjectId) || {}).name || selectedProjectId}
           projectId=${selectedProjectId} programNames=${programNames} />`}
        ${selectedProjectId && tab === "prompts" && html`<${PromptsPanel} token=${token} projectId=${selectedProjectId} />`}
        ${selectedProjectId && tab === "cost" && html`<${Cost} token=${token} projectId=${selectedProjectId} onChange=${() => refresh()} />`}
        ${selectedProjectId && tab === "flagged" && html`<${FlaggedPanel} token=${token} projectId=${selectedProjectId} />`}
        ${selectedProjectId && tab === "review" && html`<${ReviewPanel} token=${token} projectId=${selectedProjectId} />`}
      </div>
    </div>`;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
