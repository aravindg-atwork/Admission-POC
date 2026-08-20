import { COPY } from "../copy";
import type { Language } from "../types";
import { LanguageSwitch } from "./LanguageSwitch";
import "./AppShell.css";

interface Props {
  language: Language;
  onLanguageChange: (lang: Language) => void;
  onOpenCheatSheet: () => void;
  onClearChat: () => void;
  hasMessages: boolean;
}

// The signature element: the wordmark itself re-renders in the active
// language's display face on every switch, crossfading rather than
// snapping - a small, honest proof that this product treats English,
// Hindi, and Marathi as equally first-class, right where a visitor
// looks first. font-family switches with the `key` prop forcing a
// remount, which is what makes the crossfade actually restart per change
// instead of the browser silently reflowing in place.
export function AppShell({
  language,
  onLanguageChange,
  onOpenCheatSheet,
  onClearChat,
  hasMessages,
}: Props) {
  return (
    <header className="app-shell">
      <div className="app-shell__brand">
        <h1
          key={language}
          className={`app-shell__wordmark app-shell__wordmark--${language}`}
        >
          {COPY[language].wordmark}
        </h1>
      </div>
      <div className="app-shell__actions">
        <button
          type="button"
          className="app-shell__icon-btn"
          onClick={onOpenCheatSheet}
          aria-label={COPY[language].cheatSheet}
          title={COPY[language].cheatSheet}
        >
          <QuestionsIcon />
        </button>
        <button
          type="button"
          className="app-shell__icon-btn"
          onClick={onClearChat}
          disabled={!hasMessages}
          aria-label={COPY[language].clearChat}
          title={COPY[language].clearChat}
        >
          <ClearIcon />
        </button>
        <LanguageSwitch value={language} onChange={onLanguageChange} />
      </div>
    </header>
  );
}

function QuestionsIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M9 9a3 3 0 1 1 4 2.83c-.6.24-1 .83-1 1.47V14"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      <circle cx="12" cy="17.5" r="0.9" fill="currentColor" />
      <rect x="3" y="3" width="18" height="18" rx="5" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function ClearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 7h16M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0 1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
