<%@ Page Title="Admission Assistant - Console" Language="C#" AutoEventWireup="true" CodeBehind="Admin.aspx.cs" Inherits="AdmissionAssistant.Web.Admin" %>

<!DOCTYPE html>
<html lang="en">
<head runat="server">
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Admission Assistant &mdash; Console</title>
    <link rel="stylesheet" href="Content/site.css" />
    <link rel="stylesheet" href="Content/admin.css" />
</head>
<body class="admin">
    <form id="form1" runat="server">
        <div class="console">
            <aside class="sidebar">
                <div class="brand">
                    <span class="brand-mark" aria-hidden="true">A</span>
                    <span class="brand-name">Admission Assistant</span>
                </div>
                <nav class="side-nav">
                    <button type="button" class="nav-item is-active" data-panel="keys">API Keys</button>
                    <button type="button" class="nav-item" data-panel="tester">Try It</button>
                    <button type="button" class="nav-item" data-panel="extension">Extension</button>
                </nav>
                <div class="admin-auth">
                    <label for="admin-token">Admin token</label>
                    <input type="password" id="admin-token" placeholder="Enter admin token" />
                    <button type="button" id="connect-btn" class="btn btn-primary">Connect</button>
                    <p class="auth-status" id="auth-status"></p>
                </div>
            </aside>

            <main class="console-main">
                <!-- API KEYS -->
                <section class="panel is-active" id="panel-keys">
                    <header class="panel-head">
                        <div>
                            <h1>API Keys</h1>
                            <p>Each consumer &mdash; the admission site, the browser extension, any integration &mdash; gets its own key. Deactivate one without affecting the others.</p>
                        </div>
                    </header>

                    <div class="create-row">
                        <input type="text" id="new-label" placeholder="Label, e.g. browser-extension" />
                        <button type="button" id="generate-btn" class="btn btn-primary">Generate key</button>
                    </div>

                    <div class="keys-wrap">
                        <table class="keys-table" id="keys-table">
                            <thead>
                                <tr>
                                    <th>Label</th>
                                    <th>Key</th>
                                    <th>Status</th>
                                    <th>Created</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody></tbody>
                        </table>
                        <div class="empty-hint" id="keys-empty">Connect with the admin token to view and manage keys.</div>
                    </div>
                </section>

                <!-- TRY IT -->
                <section class="panel" id="panel-tester">
                    <header class="panel-head">
                        <div>
                            <h1>Try It</h1>
                            <p>Send a question through a selected key, exactly as an external consumer would hit <code>/api/chat</code>.</p>
                        </div>
                    </header>

                    <div class="tester-controls">
                        <label for="tester-key">Test with key</label>
                        <select id="tester-key"></select>
                    </div>

                    <div class="thread" id="tester-thread" aria-live="polite">
                        <div class="empty-state">
                            <h2>Ask the prospectus</h2>
                            <p>Pick an active key above, then ask a question below.</p>
                        </div>
                    </div>

                    <div class="composer">
                        <div class="composer-bar">
                            <textarea id="tester-input" placeholder="Ask about admissions..." rows="1"></textarea>
                            <button id="tester-send" type="button" aria-label="Send">
                                <svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
                                    <path d="M3 10L17 3L11.5 17L9.5 11L3 10Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </section>

                <!-- EXTENSION -->
                <section class="panel" id="panel-extension">
                    <header class="panel-head">
                        <div>
                            <h1>Extension &amp; Integration</h1>
                            <p>What another app &mdash; the admission WebForms site, or the cross-product browser extension &mdash; needs to connect.</p>
                        </div>
                    </header>

                    <div class="info-grid">
                        <div class="info-card">
                            <h3>Base URL</h3>
                            <code class="info-value" id="ext-base-url"></code>
                            <p class="info-note">Same origin serves the chat widget, the API, and this console.</p>
                        </div>
                        <div class="info-card">
                            <h3>Chat endpoint</h3>
                            <code class="info-value">POST /api/chat</code>
                            <p class="info-note">Header <code>X-API-Key: &lt;your key&gt;</code>, body <code>{ "question": "..." }</code>.</p>
                        </div>
                        <div class="info-card">
                            <h3>Ingest endpoint</h3>
                            <code class="info-value">POST /api/ingest</code>
                            <p class="info-note"><code>multipart/form-data</code> with the prospectus PDF. Same key header.</p>
                        </div>
                        <div class="info-card">
                            <h3>Integration options</h3>
                            <p class="info-note">1. Call these URLs over HTTP (extension, any site).<br />2. Reference <code>AdmissionAssistant.Core.dll</code> in-process (WebForms).</p>
                        </div>
                    </div>

                    <div class="snippet-block">
                        <div class="snippet-head">
                            <span>Extension fetch snippet</span>
                            <select id="snippet-key"></select>
                        </div>
                        <pre id="ext-snippet"></pre>
                    </div>
                </section>
            </main>
        </div>
    </form>
    <script src="Scripts/admin.js"></script>
</body>
</html>
