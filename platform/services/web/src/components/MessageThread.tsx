import { useEffect, useRef } from "react";
import type { InterviewOption, Language, Message } from "../types";
import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";
import { ThinkingIndicator } from "./ThinkingIndicator";
import "./MessageThread.css";

interface Props {
  language: Language;
  messages: Message[];
  isThinking: boolean;
  onPickExample: (question: string) => void;
  onPickInterview: (option: InterviewOption, field?: string | null) => void;
}

export function MessageThread({ language, messages, isThinking, onPickExample, onPickInterview }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    const target = !isThinking && lastMessage?.role === "assistant"
      ? listRef.current?.querySelectorAll<HTMLElement>(".bubble-row").item(messages.length - 1)
      : endRef.current;
    target?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: lastMessage?.role === "assistant" ? "start" : "end",
    });
  }, [messages, isThinking]);

  if (messages.length === 0) {
    return (
      <div className="message-thread message-thread--empty">
        <EmptyState language={language} onPick={onPickExample} />
      </div>
    );
  }

  return (
    <div className="message-thread">
      <div className="message-thread__list" ref={listRef}>
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} language={language} onPickInterview={onPickInterview} />
        ))}
        {isThinking && <ThinkingIndicator language={language} />}
        <div ref={endRef} />
      </div>
    </div>
  );
}
