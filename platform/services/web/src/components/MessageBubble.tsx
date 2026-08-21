import type { InterviewOption, Message } from "../types";
import "./MessageBubble.css";

export function MessageBubble({ message, onPickInterview }: {
  message: Message;
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
      </div>
    </div>
  );
}
