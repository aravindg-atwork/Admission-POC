import { useCallback, useState, type FormEvent } from "react";
import { COPY } from "../copy";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import type { Language } from "../types";
import "./Composer.css";

interface Props {
  language: Language;
  disabled: boolean;
  onSend: (text: string) => void;
}

export function Composer({ language, disabled, onSend }: Props) {
  const [value, setValue] = useState("");
  const copy = COPY[language];

  // Voice fills the input rather than sending directly - the student
  // still reviews (and can edit) a transcript before it goes anywhere,
  // same as typed text always has.
  const handleTranscript = useCallback((text: string) => {
    setValue((prev) => (prev ? `${prev} ${text}` : text));
  }, []);
  const speech = useSpeechRecognition(language, handleTranscript);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      {speech.isSupported && (
        <button
          type="button"
          className={`composer__mic${speech.isListening ? " composer__mic--listening" : ""}`}
          onClick={speech.isListening ? speech.stop : speech.start}
          disabled={disabled}
          aria-pressed={speech.isListening}
          aria-label={speech.isListening ? "Stop voice input" : "Ask by voice"}
          title={speech.isListening ? "Stop voice input" : "Ask by voice"}
        >
          <MicIcon />
        </button>
      )}
      <input
        className="composer__input"
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={speech.isListening ? "Listening…" : copy.placeholder}
        aria-label={copy.placeholder}
        autoComplete="off"
      />
      <button
        type="submit"
        className="composer__send"
        disabled={disabled || !value.trim()}
      >
        {copy.send}
      </button>
    </form>
  );
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path
        d="M6 11v1a6 6 0 0 0 12 0v-1M12 19v3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
