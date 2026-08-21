import { COPY } from "../copy";
import type { Language } from "../types";
import "./NotLiveBanner.css";

// Shown once, the first time a real /api/chat call fails - honest about
// the system's actual state rather than a raw network error. "Treat
// failure as a moment for direction, not mood": says plainly what's true
// and doesn't apologize for a build phase the student has no reason to
// know or care about.
export function NotLiveBanner({ language }: { language: Language }) {
  return (
    <div className="not-live-banner" role="status">
      {COPY[language].notLive}
    </div>
  );
}
