import { useState } from "react";
import { COPY } from "../copy";
import type { Language } from "../types";
import "./CheatSheet.css";

interface Props {
  language: Language;
  open: boolean;
  onClose: () => void;
}

// A reference panel, not a compose shortcut: clicking a question COPIES
// it to the clipboard rather than sending it (contrast the empty-state
// chips, which send immediately) - this is for a student who wants to
// grab a question to paste into the composer after editing it, save it
// for later, or share it with a parent over WhatsApp, not necessarily
// ask it right this second.
export function CheatSheet({ language, open, onClose }: Props) {
  const copy = COPY[language];
  const [copiedQuestion, setCopiedQuestion] = useState<string | null>(null);

  async function handleCopy(question: string) {
    try {
      await navigator.clipboard.writeText(question);
    } catch {
      // Clipboard access can be denied (permissions, insecure context) -
      // fail quietly rather than show an error for a low-stakes action;
      // the student can still select and copy the text manually.
      return;
    }
    setCopiedQuestion(question);
    window.setTimeout(() => setCopiedQuestion((current) => (current === question ? null : current)), 1500);
  }

  if (!open) return null;

  return (
    <div className="cheat-sheet-overlay" onClick={onClose}>
      <aside
        className="cheat-sheet"
        onClick={(e) => e.stopPropagation()}
        aria-label={copy.cheatSheet}
      >
        <div className="cheat-sheet__head">
          <h2 className="cheat-sheet__title">{copy.cheatSheet}</h2>
          <button
            type="button"
            className="cheat-sheet__close"
            onClick={onClose}
            aria-label="Close"
          >
            <CloseIcon />
          </button>
        </div>
        <p className="cheat-sheet__hint">{copy.cheatSheetHint}</p>
        <div className="cheat-sheet__body">
          {copy.cheatSheetCategories.map((category) => (
            <section key={category.label} className="cheat-sheet__category">
              <h3 className="cheat-sheet__category-label">{category.label}</h3>
              <ul className="cheat-sheet__list">
                {category.questions.map((question) => (
                  <li key={question}>
                    <button
                      type="button"
                      className="cheat-sheet__question"
                      onClick={() => handleCopy(question)}
                    >
                      <span>{question}</span>
                      <span className="cheat-sheet__copy-hint">
                        {copiedQuestion === question ? copy.copied : <CopyIcon />}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </aside>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="9" y="9" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5 5l14 14M19 5 5 19" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
