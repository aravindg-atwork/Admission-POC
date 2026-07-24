(function () {
    var thread = document.getElementById("thread");
    var emptyState = document.getElementById("empty-state");
    var input = document.getElementById("chat-input");
    var sendBtn = document.getElementById("chat-send");
    var suggestions = document.getElementById("suggestions");
    var micBtn = document.getElementById("mic-btn");
    var speakToggle = document.getElementById("speak-toggle");
    var langSelect = document.getElementById("lang-select");
    var voiceHint = document.getElementById("voice-hint");

    // The API key for this first-party chat widget. On the real site this is injected
    // server-side (see Default.aspx.cs); window.ADMISSION_API_KEY lets a host page or
    // the dev server override it.
    var API_KEY = window.ADMISSION_API_KEY || "";

    var isSending = false;
    var speakEnabled = true;

    // --- Speech-to-text (browser Web Speech API - no server, no model download) ---
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    var recognition = null;
    var isListening = false;

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.interimResults = false;
        recognition.maxAlternatives = 1;

        recognition.onresult = function (e) {
            var transcript = e.results[0][0].transcript;
            input.value = transcript;
            autoResize();
        };
        recognition.onend = function () {
            isListening = false;
            micBtn.classList.remove("is-listening");
            if (input.value.trim()) sendMessage(input.value);
        };
        recognition.onerror = function () {
            isListening = false;
            micBtn.classList.remove("is-listening");
            setHint("Couldn't hear that. Try again or type your question.");
        };
    } else {
        micBtn.style.display = "none";
    }

    micBtn.addEventListener("click", function () {
        if (!recognition) return;
        if (isListening) {
            recognition.stop();
            return;
        }
        recognition.lang = langSelect.value;
        try {
            recognition.start();
            isListening = true;
            micBtn.classList.add("is-listening");
            setHint("Listening... speak now.");
        } catch (err) {
            isListening = false;
        }
    });

    // --- Text-to-speech ---
    speakToggle.addEventListener("click", function () {
        speakEnabled = !speakEnabled;
        speakToggle.classList.toggle("is-on", speakEnabled);
        speakToggle.setAttribute("aria-pressed", String(speakEnabled));
        if (!speakEnabled && window.speechSynthesis) window.speechSynthesis.cancel();
    });

    function speak(text) {
        if (!speakEnabled || !window.speechSynthesis) return;
        window.speechSynthesis.cancel();
        var utter = new SpeechSynthesisUtterance(text);
        utter.lang = langSelect.value;
        var match = window.speechSynthesis.getVoices().filter(function (v) {
            return v.lang === langSelect.value;
        })[0];
        if (match) utter.voice = match;
        window.speechSynthesis.speak(utter);
    }

    function setHint(msg) {
        voiceHint.textContent = msg || "";
        if (msg) {
            setTimeout(function () {
                if (voiceHint.textContent === msg) voiceHint.textContent = "";
            }, 4000);
        }
    }

    // --- Chat send flow ---
    sendBtn.addEventListener("click", function () { sendMessage(input.value); });

    input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage(input.value);
        }
    });

    input.addEventListener("input", autoResize);

    if (suggestions) {
        suggestions.addEventListener("click", function (e) {
            var chip = e.target.closest(".suggestion-chip");
            if (chip) sendMessage(chip.textContent);
        });
    }

    function autoResize() {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 140) + "px";
    }

    function sendMessage(text) {
        var question = (text || "").trim();
        if (!question || isSending) return;

        if (emptyState) {
            emptyState.remove();
            emptyState = null;
        }

        appendUserMessage(question);
        input.value = "";
        autoResize();

        var thinkingRow = appendThinking();
        setSending(true);

        var headers = { "Content-Type": "application/json" };
        if (API_KEY) headers["X-API-Key"] = API_KEY;

        fetch("/api/chat", {
            method: "POST",
            headers: headers,
            body: JSON.stringify({ question: question })
        })
            .then(function (res) {
                if (!res.ok) throw new Error("Request failed");
                return res.json();
            })
            .then(function (data) {
                thinkingRow.remove();
                appendAssistantMessage(data.answerText, data.pageReferences || []);
                speak(data.answerText);
            })
            .catch(function () {
                thinkingRow.remove();
                appendErrorMessage("Something went wrong reaching the assistant. Please try again.");
            })
            .then(function () {
                setSending(false);
            });
    }

    function setSending(sending) {
        isSending = sending;
        sendBtn.disabled = sending;
    }

    function appendUserMessage(text) {
        var row = document.createElement("div");
        row.className = "msg-row user";

        var bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;

        row.appendChild(bubble);
        thread.appendChild(row);
        scrollToEnd();
    }

    function appendAssistantMessage(text, pageReferences) {
        var row = document.createElement("div");
        row.className = "msg-row assistant";

        var wrap = document.createElement("div");

        var bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;
        wrap.appendChild(bubble);

        var meta = document.createElement("div");
        meta.className = "msg-meta";

        if (pageReferences.length) {
            pageReferences.forEach(function (page) {
                var pill = document.createElement("span");
                pill.className = "citation-pill";
                pill.textContent = "p. " + page;
                meta.appendChild(pill);
            });
        }

        if (window.speechSynthesis) {
            var replay = document.createElement("button");
            replay.type = "button";
            replay.className = "replay-btn";
            replay.setAttribute("aria-label", "Read this answer aloud");
            replay.innerHTML =
                '<svg viewBox="0 0 20 20" width="14" height="14" fill="none"><path d="M4 8v4h3l4 3V5L7 8H4z" fill="currentColor"/><path d="M14 7c1 1 1 5 0 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
            replay.addEventListener("click", function () { speak(text); });
            meta.appendChild(replay);
        }

        if (meta.childNodes.length) wrap.appendChild(meta);

        row.appendChild(wrap);
        thread.appendChild(row);
        scrollToEnd();
    }

    function appendErrorMessage(text) {
        var row = document.createElement("div");
        row.className = "msg-row assistant error";

        var bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.textContent = text;

        row.appendChild(bubble);
        thread.appendChild(row);
        scrollToEnd();
    }

    function appendThinking() {
        var row = document.createElement("div");
        row.className = "msg-row assistant thinking";
        row.innerHTML =
            '<div class="bubble"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>';
        thread.appendChild(row);
        scrollToEnd();
        return row;
    }

    function scrollToEnd() {
        thread.scrollTop = thread.scrollHeight;
    }
})();
