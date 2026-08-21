import { COPY } from "../copy";
import type { Language } from "../types";
import "./ThinkingIndicator.css";

// A soft, marigold-toned pulse rather than a generic spinner - matches the
// accent used everywhere else the assistant is actively doing something
// for you, and reads as "thinking," not "loading a page."
export function ThinkingIndicator({ language }: { language: Language }) {
  return (
    <div className="thinking" role="status" aria-live="polite">
      <span className="thinking__dot" />
      <span className="thinking__dot" />
      <span className="thinking__dot" />
      <span className="thinking__label">{COPY[language].thinking}</span>
    </div>
  );
}
