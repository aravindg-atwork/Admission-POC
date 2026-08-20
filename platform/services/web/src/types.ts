export type Language = "en" | "hi" | "mr";

export interface Message {
  id: string;
  role: "student" | "assistant";
  text: string;
  status?: "sending" | "sent" | "failed";
}

export interface ChatResponse {
  answer: string;
  source: string;
  model: string;
}
