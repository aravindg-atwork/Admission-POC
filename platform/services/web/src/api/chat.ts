// Talks to the real /api/chat contract. askQuestion() reports connection
// failures as {live: false}, allowing the UI to show an honest unavailable
// state instead of exposing a raw fetch error.
import type { ChatResponse, ConversationState, Language, Programme } from "../types";

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
  projectId: Programme,
  conversationState: ConversationState = {},
  sessionId: string | null = null,
): Promise<AskResult> {
  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, uiLanguage: language, projectId, conversationState, sessionId }),
    });
    if (!res.ok) return { live: false };
    const response = (await res.json()) as ChatResponse;
    return { live: true, response };
  } catch {
    return { live: false };
  }
}
