import type { Message } from "../types";
import "./MessageBubble.css";

export function MessageBubble({ message }: { message: Message }) {
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
      </div>
    </div>
  );
}
