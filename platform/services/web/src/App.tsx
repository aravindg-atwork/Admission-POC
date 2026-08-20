import { useState } from "react";
import { askQuestion } from "./api/chat";
import { AppShell } from "./components/AppShell";
import { CheatSheet } from "./components/CheatSheet";
import { Composer } from "./components/Composer";
import { MessageThread } from "./components/MessageThread";
import { NotLiveBanner } from "./components/NotLiveBanner";
import type { Language, Message } from "./types";
import "./App.css";

function newId() {
  return crypto.randomUUID();
}

export default function App() {
  const [language, setLanguage] = useState<Language>("en");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [backendLive, setBackendLive] = useState(true);
  const [cheatSheetOpen, setCheatSheetOpen] = useState(false);

  async function send(text: string) {
    const studentMessage: Message = { id: newId(), role: "student", text };
    setMessages((prev) => [...prev, studentMessage]);
    setIsThinking(true);

    const result = await askQuestion(text, language);
    setIsThinking(false);

    if (!result.live) {
      setBackendLive(false);
      return;
    }
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "assistant", text: result.response.answer },
    ]);
  }

  function clearChat() {
    setMessages([]);
    setBackendLive(true);
  }

  return (
    <div className="app">
      <AppShell
        language={language}
        onLanguageChange={setLanguage}
        onOpenCheatSheet={() => setCheatSheetOpen(true)}
        onClearChat={clearChat}
        hasMessages={messages.length > 0}
      />
      {!backendLive && <NotLiveBanner language={language} />}
      <MessageThread
        language={language}
        messages={messages}
        isThinking={isThinking}
        onPickExample={send}
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
