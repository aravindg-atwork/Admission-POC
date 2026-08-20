import { COPY } from "../copy";
import type { Language } from "../types";
import "./EmptyState.css";

interface Props {
  language: Language;
  onPick: (question: string) => void;
}

// The "hero" for this product isn't a banner - it's an invitation to ask
// the first question, in a language the student is actually comfortable
// in. The example chips double as onboarding: a student unsure what's
// even askable sees three concrete, answerable questions instead of a
// blank box.
export function EmptyState({ language, onPick }: Props) {
  const copy = COPY[language];
  return (
    <div className="empty-state">
      <h2
        key={language}
        className={`empty-state__greeting${language === "mr" ? " empty-state__greeting--mr" : ""}`}
      >
        {copy.greeting}
      </h2>
      <p className="empty-state__subtext">{copy.subtext}</p>
      <div className="empty-state__chips">
        {copy.chips.map((chip) => (
          <button
            key={chip}
            type="button"
            className="empty-state__chip"
            onClick={() => onPick(chip)}
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}
