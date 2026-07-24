<%@ Page Title="Admission Assistant" Language="C#" AutoEventWireup="true" CodeBehind="Default.aspx.cs" Inherits="AdmissionAssistant.Web.Default" %>

<!DOCTYPE html>
<html lang="en">
<head runat="server">
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Admission Assistant</title>
    <link rel="stylesheet" href="Content/site.css" />
</head>
<body>
    <form id="form1" runat="server">
        <div class="app">
            <header class="app-header">
                <div class="brand">
                    <span class="brand-mark" aria-hidden="true">A</span>
                    <span class="brand-name">Admission Assistant</span>
                </div>
                <div class="header-controls">
                    <select id="lang-select" aria-label="Voice language" title="Voice language">
                        <option value="en-IN">English</option>
                        <option value="hi-IN">हिंदी</option>
                        <option value="ta-IN">தமிழ்</option>
                        <option value="mr-IN">मराठी</option>
                    </select>
                    <button type="button" id="speak-toggle" class="icon-toggle is-on" aria-pressed="true" title="Read answers aloud">
                        <svg viewBox="0 0 20 20" width="17" height="17" fill="none" aria-hidden="true">
                            <path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor" />
                            <path d="M14 7c1 1 1 5 0 6M16 5c2 2 2 8 0 10" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                        </svg>
                    </button>
                    <span class="status-pill" id="status-pill">Online</span>
                </div>
            </header>

            <main class="thread" id="thread" aria-live="polite">
                <div class="empty-state" id="empty-state">
                    <h1>Ask anything about admissions</h1>
                    <p>Answers come straight from the prospectus, with page references.</p>
                    <div class="suggestions" id="suggestions">
                        <button type="button" class="suggestion-chip">What are the eligibility criteria?</button>
                        <button type="button" class="suggestion-chip">When does the application window close?</button>
                        <button type="button" class="suggestion-chip">What documents do I need to submit?</button>
                    </div>
                </div>
            </main>

            <footer class="composer">
                <div class="composer-bar">
                    <button id="mic-btn" type="button" class="mic-btn" aria-label="Speak your question" title="Speak your question">
                        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
                            <rect x="7.5" y="2.5" width="5" height="9" rx="2.5" fill="currentColor" />
                            <path d="M5 9a5 5 0 0 0 10 0M10 14v3M7.5 17h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
                        </svg>
                    </button>
                    <textarea id="chat-input" placeholder="Ask about admissions..." rows="1"></textarea>
                    <button id="chat-send" type="button" aria-label="Send message">
                        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
                            <path d="M3 10L17 3L11.5 17L9.5 11L3 10Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
                        </svg>
                    </button>
                </div>
                <p class="voice-hint" id="voice-hint"></p>
            </footer>
        </div>
    </form>
    <script>window.ADMISSION_API_KEY = "<%= DefaultApiKey %>";</script>
    <script src="Scripts/chat.js"></script>
</body>
</html>
