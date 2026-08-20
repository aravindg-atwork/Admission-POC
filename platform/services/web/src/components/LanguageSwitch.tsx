import { COPY } from "../copy";
import type { Language } from "../types";
import "./LanguageSwitch.css";

const LANGUAGES: Language[] = ["en", "hi", "mr"];

interface Props {
  value: Language;
  onChange: (lang: Language) => void;
}

export function LanguageSwitch({ value, onChange }: Props) {
  return (
    <div className="lang-switch" role="radiogroup" aria-label="Choose language">
      {LANGUAGES.map((lang) => (
        <button
          key={lang}
          type="button"
          role="radio"
          aria-checked={value === lang}
          className={`lang-switch__option${value === lang ? " lang-switch__option--active" : ""}`}
          onClick={() => onChange(lang)}
        >
          {COPY[lang].languageLabel}
        </button>
      ))}
    </div>
  );
}
