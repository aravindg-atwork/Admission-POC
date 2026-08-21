import type { InterviewOption, Language, Message } from "../types";
import "./MessageBubble.css";

const EVIDENCE_LABEL: Record<Language, string> = {
  en: "Evidence",
  hi: "स्रोत विवरण",
  mr: "स्रोत तपशील",
};

const PAGE_LABEL: Record<Language, string> = {
  en: "Prospectus pages",
  hi: "प्रॉस्पेक्टस पृष्ठ",
  mr: "प्रॉस्पेक्टस पृष्ठे",
};

export function MessageBubble({ message, language, onPickInterview }: {
  message: Message;
  language: Language;
  onPickInterview: (option: InterviewOption, field?: string | null) => void;
}) {
  const isStudent = message.role === "student";
  return (
    <div
      className={`bubble-row${isStudent ? " bubble-row--student" : ""}`}
      role="group"
      aria-label={isStudent ? "Your message" : "Assistant's answer"}
    >
      <div
        className={`bubble${isStudent ? " bubble--student" : " bubble--assistant"}${
          message.status === "failed" ? " bubble--failed" : ""
        }`}
      >
        {message.text}
        {!isStudent && message.interviewOptions && message.interviewOptions.length > 0 && (
          <div className="bubble__options" aria-label="Answer choices">
            {message.interviewOptions.map((option) => (
              <button key={option.value} type="button" onClick={() => onPickInterview(option, message.interviewField)}>
                {option.label}
              </button>
            ))}
          </div>
        )}
        {!isStudent && ((message.pages?.length ?? 0) > 0 || (message.policyDecisions?.length ?? 0) > 0) && (
          <details className="bubble__evidence">
            <summary>{EVIDENCE_LABEL[language]}</summary>
            {message.pages && message.pages.length > 0 && (
              <div>{PAGE_LABEL[language]}: {message.pages.join(", ")}</div>
            )}
            {message.policyDecisions?.map((decision) => (
              <div key={`${decision.dimension}-${decision.ruleId}`}>
                {decision.dimension}: {decision.outcome} · {decision.ruleId}
              </div>
            ))}
          </details>
        )}
      </div>
    </div>
  );
}
