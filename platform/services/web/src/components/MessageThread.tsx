import { useEffect, useRef } from "react";
import type { Language, Message } from "../types";
import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";
import { ThinkingIndicator } from "./ThinkingIndicator";
import "./MessageThread.css";

interface Props {
  language: Language;
  messages: Message[];
  isThinking: boolean;
  onPickExample: (question: string) => void;
}

export function MessageThread({ language, messages, isThinking, onPickExample }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [messages.length, isThinking]);

  if (messages.length === 0) {
    return (
      <div className="message-thread message-thread--empty">
        <EmptyState language={language} onPick={onPickExample} />
      </div>
    );
  }

  return (
    <div className="message-thread">
      <div className="message-thread__list">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        {isThinking && <ThinkingIndicator language={language} />}
        <div ref={endRef} />
      </div>
    </div>
  );
}
