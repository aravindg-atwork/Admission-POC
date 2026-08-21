export type Language = "en" | "hi" | "mr";

export type Programme = "bvsc" | "bfsc" | "btech-dairy";

export interface Message {
  id: string;
  role: "student" | "assistant";
  text: string;
  status?: "sending" | "sent" | "failed";
  interviewOptions?: InterviewOption[];
  interviewField?: string | null;
  source?: string;
  cacheHit?: boolean;
}

export interface InterviewOption {
  label: string;
  value: string;
}

export type ConversationState = Record<string, string | number | null | Record<string, number>>;

export interface ChatResponse {
  answer: string;
  source: string;
  interviewField?: string | null;
  interviewOptions?: InterviewOption[];
  carryQuestion?: string | null;
  slotUpdate?: ConversationState;
  language?: Language;
  cacheHit?: boolean;
  projectId?: Programme;
  sessionId?: string | null;
  messageId?: number | null;
}
