import { useState } from "react";
import { askQuestion } from "./api/chat";
import { AppShell } from "./components/AppShell";
import { CheatSheet } from "./components/CheatSheet";
import { Composer } from "./components/Composer";
import { MessageThread } from "./components/MessageThread";
import { NotLiveBanner } from "./components/NotLiveBanner";
import type { ConversationState, InterviewOption, Language, Message, Programme } from "./types";
import "./App.css";

function newId(): string {
  // crypto.randomUUID() requires a "secure context" (HTTPS, or localhost)
  // per the Web Crypto API spec - it's simply undefined otherwise, which
  // is exactly what broke every send on the plain-HTTP production
  // deployment (http://159.69.210.30:8080, a public IP, no TLS yet - see
  // the platform architecture doc's still-open "TLS everywhere" item).
  // This id is only ever a local React key/message identifier, never
  // anything security-sensitive, so a plain fallback is a real fix, not
  // a workaround to remove later - crypto.randomUUID is still used
  // whenever it's actually available (HTTPS, or local dev on localhost).
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

const PROGRAMME_STORAGE_KEY = "mafsu-admissions-programme";

const PROGRAMME_NAMES: Record<Programme, string> = {
  bvsc: "B.V.Sc. & A.H.",
  bfsc: "B.F.Sc.",
  "btech-dairy": "B.Tech. (Dairy Technology)",
};

function initialProgramme(): Programme {
  const saved = localStorage.getItem(PROGRAMME_STORAGE_KEY);
  return saved === "bfsc" || saved === "btech-dairy" || saved === "bvsc" ? saved : "bvsc";
}

export default function App() {
  const [language, setLanguage] = useState<Language>("en");
  const [programme, setProgramme] = useState<Programme>(initialProgramme);
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [backendLive, setBackendLive] = useState(true);
  const [cheatSheetOpen, setCheatSheetOpen] = useState(false);
  const [conversationState, setConversationState] = useState<ConversationState>({});
  const [carryQuestion, setCarryQuestion] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  async function send(text: string) {
    const studentMessage: Message = { id: newId(), role: "student", text };
    setMessages((prev) => [...prev, studentMessage]);
    setIsThinking(true);

    const result = await askQuestion(text, language, programme, conversationState, sessionId);
    setIsThinking(false);

    if (!result.live) {
      setBackendLive(false);
      return;
    }
    if (result.response.language) setLanguage(result.response.language);
    if (result.response.sessionId) setSessionId(result.response.sessionId);
    const programmeSwitched = Boolean(
      result.response.projectId && result.response.projectId !== programme
    );
    if (programmeSwitched && result.response.projectId) {
      setProgramme(result.response.projectId);
      localStorage.setItem(PROGRAMME_STORAGE_KEY, result.response.projectId);
    }
    setMessages((prev) => [
      ...prev,
      {
        id: newId(), role: "assistant", text: result.response.answer,
        interviewOptions: result.response.interviewOptions,
        interviewField: result.response.interviewField,
        source: result.response.source,
        cacheHit: result.response.cacheHit,
      },
    ]);
    setConversationState((previous) => ({
      ...(programmeSwitched ? {} : previous),
      ...(result.response.slotUpdate ?? {}),
      lastAssistantAnswer: result.response.answer,
      lastAssistantSource: result.response.source,
    }));
    setCarryQuestion(result.response.carryQuestion ?? null);
  }

  async function pickInterviewOption(option: InterviewOption, responseField?: string | null) {
    const optionField = responseField ?? (
      option.value === "yes" || option.value === "no" || option.value === "pending"
        ? "entranceExamStatus" : "category"
    );
    const chosenProgramme = optionField === "projectId" ? option.value as Programme : programme;
    if (optionField === "projectId") {
      setProgramme(chosenProgramme);
      localStorage.setItem(PROGRAMME_STORAGE_KEY, chosenProgramme);
    }
    const nextState: ConversationState = optionField === "projectId"
      ? { programme: chosenProgramme }
      : { ...conversationState, [optionField]: option.value };
    setConversationState(nextState);
    const question = carryQuestion ?? `Am I eligible for ${PROGRAMME_NAMES[chosenProgramme]}?`;
    const studentMessage: Message = { id: newId(), role: "student", text: option.label };
    setMessages((previous) => [...previous, studentMessage]);
    setIsThinking(true);
    const result = await askQuestion(question, language, chosenProgramme, nextState, sessionId);
    setIsThinking(false);
    if (!result.live) { setBackendLive(false); return; }
    if (result.response.language) setLanguage(result.response.language);
    if (result.response.sessionId) setSessionId(result.response.sessionId);
    const programmeSwitched = Boolean(
      result.response.projectId && result.response.projectId !== programme
    );
    if (programmeSwitched && result.response.projectId) {
      setProgramme(result.response.projectId);
      localStorage.setItem(PROGRAMME_STORAGE_KEY, result.response.projectId);
    }
    setMessages((previous) => [...previous, {
      id: newId(), role: "assistant", text: result.response.answer,
      interviewOptions: result.response.interviewOptions,
      interviewField: result.response.interviewField,
      source: result.response.source,
      cacheHit: result.response.cacheHit,
    }]);
    setConversationState((previous) => ({
      ...(programmeSwitched ? {} : previous),
      ...(programmeSwitched ? {} : nextState),
      ...(result.response.slotUpdate ?? {}),
      lastAssistantAnswer: result.response.answer,
      lastAssistantSource: result.response.source,
    }));
    setCarryQuestion(result.response.carryQuestion ?? null);
  }

  function clearChat() {
    setMessages([]);
    setBackendLive(true);
    setConversationState({});
    setCarryQuestion(null);
    setSessionId(null);
  }


  function changeProgramme(nextProgramme: Programme) {
    if (nextProgramme === programme) return;
    localStorage.setItem(PROGRAMME_STORAGE_KEY, nextProgramme);
    setProgramme(nextProgramme);
    clearChat();
  }

  return (
    <div className="app">
      <AppShell
        language={language}
        onLanguageChange={setLanguage}
        onOpenCheatSheet={() => setCheatSheetOpen(true)}
        onClearChat={clearChat}
        hasMessages={messages.length > 0}
        programme={programme}
        onProgrammeChange={changeProgramme}
        programmeDisabled={isThinking}
      />
      {!backendLive && <NotLiveBanner language={language} />}
      <MessageThread
        language={language}
        messages={messages}
        isThinking={isThinking}
        onPickExample={send}
        onPickInterview={pickInterviewOption}
      />
      <Composer language={language} disabled={isThinking} onSend={send} />
      <CheatSheet
        language={language}
        open={cheatSheetOpen}
        onClose={() => setCheatSheetOpen(false)}
      />
    </div>
  );
}
