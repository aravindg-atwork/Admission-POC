// Talks to the real, eventual /api/chat contract - deliberately, so this
// client needs no rework once app/agent's guard pipeline actually exists
// on the backend (see ../../CLAUDE.md's phased plan). Right now that route
// doesn't exist yet, so every call 404s; askQuestion() reports that as
// {live: false} rather than throwing, so the UI can show an honest "not
// connected yet" state instead of a raw fetch error.
import type { ChatResponse, ConversationState, Language } from "../types";

// Empty by default - a relative "/api/chat" resolves against whatever
// origin the page itself was loaded from (proxied server-side to the real
// backend - see vite.config.ts for local dev, nginx.conf for the built
// image). VITE_API_BASE stays available as an override for the rare case
// the API genuinely lives on a different origin than the frontend, but is
// no longer how this works by default - hardcoding an absolute
// http://localhost:8100 here is exactly what broke the first time this
// was shared with someone testing from their own machine.
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export type AskResult =
  | { live: true; response: ChatResponse }
  | { live: false };

export async function askQuestion(
  question: string,
  language: Language,
  conversationState: ConversationState = {},
): Promise<AskResult> {
  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, uiLanguage: language, projectId: "bvsc", conversationState }),
    });
    if (!res.ok) return { live: false };
    const response = (await res.json()) as ChatResponse;
    return { live: true, response };
  } catch {
    return { live: false };
  }
}
