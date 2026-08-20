// Talks to the real, eventual /api/chat contract - deliberately, so this
// client needs no rework once app/agent's guard pipeline actually exists
// on the backend (see ../../CLAUDE.md's phased plan). Right now that route
// doesn't exist yet, so every call 404s; askQuestion() reports that as
// {live: false} rather than throwing, so the UI can show an honest "not
// connected yet" state instead of a raw fetch error.
import type { ChatResponse, Language } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8100";

export type AskResult =
  | { live: true; response: ChatResponse }
  | { live: false };

export async function askQuestion(
  question: string,
  language: Language,
): Promise<AskResult> {
  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, uiLanguage: language }),
    });
    if (!res.ok) return { live: false };
    const response = (await res.json()) as ChatResponse;
    return { live: true, response };
  } catch {
    return { live: false };
  }
}
