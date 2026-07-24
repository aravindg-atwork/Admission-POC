(function () {
    var TOKEN_KEY = "admissionAdminToken";
    var keys = [];

    var els = {
        token: document.getElementById("admin-token"),
        connect: document.getElementById("connect-btn"),
        authStatus: document.getElementById("auth-status"),
        newLabel: document.getElementById("new-label"),
        generate: document.getElementById("generate-btn"),
        tableBody: document.querySelector("#keys-table tbody"),
        keysEmpty: document.getElementById("keys-empty"),
        testerKey: document.getElementById("tester-key"),
        testerThread: document.getElementById("tester-thread"),
        testerInput: document.getElementById("tester-input"),
        testerSend: document.getElementById("tester-send"),
        extBaseUrl: document.getElementById("ext-base-url"),
        snippetKey: document.getElementById("snippet-key"),
        extSnippet: document.getElementById("ext-snippet")
    };

    // Sidebar panel switching
    document.querySelectorAll(".nav-item").forEach(function (btn) {
        btn.addEventListener("click", function () {
            document.querySelectorAll(".nav-item").forEach(function (b) { b.classList.remove("is-active"); });
            document.querySelectorAll(".panel").forEach(function (p) { p.classList.remove("is-active"); });
            btn.classList.add("is-active");
            document.getElementById("panel-" + btn.dataset.panel).classList.add("is-active");
        });
    });

    els.extBaseUrl.textContent = window.location.origin;

    var savedToken = localStorage.getItem(TOKEN_KEY);
    if (savedToken) els.token.value = savedToken;

    els.connect.addEventListener("click", connect);
    els.generate.addEventListener("click", generateKey);
    els.testerSend.addEventListener("click", function () { runTest(els.testerInput.value); });
    els.testerInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); runTest(els.testerInput.value); }
    });
    els.snippetKey.addEventListener("change", renderSnippet);

    function token() { return localStorage.getItem(TOKEN_KEY) || ""; }

    function connect() {
        localStorage.setItem(TOKEN_KEY, els.token.value.trim());
        loadKeys();
    }

    function loadKeys() {
        fetch("/admin/keys", { headers: { "X-Admin-Token": token() } })
            .then(function (r) {
                if (!r.ok) throw new Error("unauthorized");
                return r.json();
            })
            .then(function (data) {
                keys = data;
                els.authStatus.textContent = "Connected";
                els.authStatus.className = "auth-status ok";
                renderKeys();
                renderKeyOptions();
                renderSnippet();
            })
            .catch(function () {
                els.authStatus.textContent = "Invalid token";
                els.authStatus.className = "auth-status err";
            });
    }

    function generateKey() {
        if (!token()) { els.authStatus.textContent = "Connect first"; els.authStatus.className = "auth-status err"; return; }
        fetch("/admin/keys", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-Admin-Token": token() },
            body: JSON.stringify({ label: els.newLabel.value.trim() })
        }).then(function () { els.newLabel.value = ""; loadKeys(); });
    }

    function toggleKey(id, active) {
        fetch("/admin/keys/" + id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", "X-Admin-Token": token() },
            body: JSON.stringify({ active: active })
        }).then(loadKeys);
    }

    function deleteKey(id) {
        if (!confirm("Delete this key? Anything using it stops working immediately.")) return;
        fetch("/admin/keys/" + id, { method: "DELETE", headers: { "X-Admin-Token": token() } }).then(loadKeys);
    }

    function renderKeys() {
        els.tableBody.innerHTML = "";
        if (!keys.length) {
            els.keysEmpty.textContent = "No keys yet. Generate one above.";
            els.keysEmpty.style.display = "block";
            return;
        }
        els.keysEmpty.style.display = "none";

        keys.forEach(function (k) {
            var tr = document.createElement("tr");

            var labelTd = document.createElement("td");
            labelTd.textContent = k.label;
            tr.appendChild(labelTd);

            var keyTd = document.createElement("td");
            var wrap = document.createElement("span");
            wrap.className = "key-value";
            var code = document.createElement("code");
            code.textContent = k.key;
            code.title = k.key;
            var copy = document.createElement("button");
            copy.className = "copy-btn";
            copy.textContent = "copy";
            copy.addEventListener("click", function () {
                navigator.clipboard.writeText(k.key);
                copy.textContent = "copied";
                setTimeout(function () { copy.textContent = "copy"; }, 1200);
            });
            wrap.appendChild(code);
            wrap.appendChild(copy);
            keyTd.appendChild(wrap);
            tr.appendChild(keyTd);

            var statusTd = document.createElement("td");
            var badge = document.createElement("span");
            badge.className = "status-badge " + (k.active ? "active" : "inactive");
            badge.textContent = k.active ? "Active" : "Inactive";
            statusTd.appendChild(badge);
            tr.appendChild(statusTd);

            var createdTd = document.createElement("td");
            createdTd.className = "created-cell";
            createdTd.textContent = new Date(k.created_at || k.createdAt).toLocaleDateString();
            tr.appendChild(createdTd);

            var actionsTd = document.createElement("td");
            var actions = document.createElement("div");
            actions.className = "row-actions";

            var toggle = document.createElement("button");
            toggle.className = "btn btn-sm btn-ghost";
            toggle.textContent = k.active ? "Deactivate" : "Activate";
            toggle.addEventListener("click", function () { toggleKey(k.id, !k.active); });
            actions.appendChild(toggle);

            var del = document.createElement("button");
            del.className = "btn btn-sm btn-danger";
            del.textContent = "Delete";
            del.addEventListener("click", function () { deleteKey(k.id); });
            actions.appendChild(del);

            actionsTd.appendChild(actions);
            tr.appendChild(actionsTd);

            els.tableBody.appendChild(tr);
        });
    }

    function renderKeyOptions() {
        var active = keys.filter(function (k) { return k.active; });
        [els.testerKey, els.snippetKey].forEach(function (sel) {
            sel.innerHTML = "";
            if (!active.length) {
                var opt = document.createElement("option");
                opt.textContent = "No active keys";
                opt.value = "";
                sel.appendChild(opt);
                return;
            }
            active.forEach(function (k) {
                var opt = document.createElement("option");
                opt.value = k.key;
                opt.textContent = k.label;
                sel.appendChild(opt);
            });
        });
    }

    function renderSnippet() {
        var key = els.snippetKey.value || "<your-active-key>";
        els.extSnippet.textContent =
            "fetch('" + window.location.origin + "/api/chat', {\n" +
            "  method: 'POST',\n" +
            "  headers: {\n" +
            "    'Content-Type': 'application/json',\n" +
            "    'X-API-Key': '" + key + "'\n" +
            "  },\n" +
            "  body: JSON.stringify({ question: 'What are the eligibility criteria?' })\n" +
            "})\n" +
            "  .then(r => r.json())\n" +
            "  .then(data => console.log(data.answerText, data.pageReferences));";
    }

    function runTest(text) {
        var question = (text || "").trim();
        var key = els.testerKey.value;
        if (!question) return;
        if (!key) { alert("No active key selected. Generate or activate a key first."); return; }

        var empty = els.testerThread.querySelector(".empty-state");
        if (empty) empty.remove();

        appendRow("user", question);
        els.testerInput.value = "";
        var thinking = appendThinking();

        fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-API-Key": key },
            body: JSON.stringify({ question: question })
        })
            .then(function (r) {
                thinking.remove();
                if (r.status === 401) { appendRow("error", "401 Unauthorized - that key is inactive or invalid."); return null; }
                if (!r.ok) throw new Error("failed");
                return r.json();
            })
            .then(function (data) {
                if (!data) return;
                appendAnswer(data.answerText, data.pageReferences || []);
            })
            .catch(function () {
                appendRow("error", "Request failed. Check that the backend is running.");
            });
    }

    function appendRow(kind, text) {
        var row = document.createElement("div");
        row.className = "msg-row " + (kind === "user" ? "user" : "assistant") + (kind === "error" ? " error" : "");
        var bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;
        row.appendChild(bubble);
        els.testerThread.appendChild(row);
        els.testerThread.scrollTop = els.testerThread.scrollHeight;
    }

    function appendAnswer(text, pages) {
        var row = document.createElement("div");
        row.className = "msg-row assistant";
        var wrap = document.createElement("div");
        var bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;
        wrap.appendChild(bubble);
        if (pages.length) {
            var meta = document.createElement("div");
            meta.className = "msg-meta";
            pages.forEach(function (p) {
                var pill = document.createElement("span");
                pill.className = "citation-pill";
                pill.textContent = "p. " + p;
                meta.appendChild(pill);
            });
            wrap.appendChild(meta);
        }
        row.appendChild(wrap);
        els.testerThread.appendChild(row);
        els.testerThread.scrollTop = els.testerThread.scrollHeight;
    }

    function appendThinking() {
        var row = document.createElement("div");
        row.className = "msg-row assistant thinking";
        row.innerHTML = '<div class="bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
        els.testerThread.appendChild(row);
        els.testerThread.scrollTop = els.testerThread.scrollHeight;
        return row;
    }

    if (savedToken) loadKeys();
})();
