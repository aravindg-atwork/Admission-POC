(function ($, window, document) {
  "use strict";

  if (!$) {
    window.console && window.console.error("MAFSU Admissions Widget requires jQuery.");
    return;
  }

  var $root = $("#mafsu-admissions-widget");
  if (!$root.length) return;

  var config = {
    apiBase: String($root.data("api-base") || "").replace(/\/$/, ""),
    language: String($root.data("default-language") || "en"),
    projectId: "bvsc",
    conversationState: {},
    carryQuestion: null,
    sessionId: null,
    busy: false
  };
  var programmeNames = {
    "bvsc": "B.V.Sc. & A.H.",
    "bfsc": "B.F.Sc.",
    "btech-dairy": "B.Tech. Dairy"
  };
  var $panel = $root.find(".mafsu-chat__panel");
  var $launcher = $root.find(".mafsu-chat__launcher");
  var $messages = $root.find("[data-chat-messages]");
  var welcomeHtml = $messages.html();
  var $form = $root.find("[data-chat-form]");
  var $input = $root.find("[data-chat-input]");
  var $charCount = $root.find("[data-char-count]");
  var $send = $root.find("[data-chat-send]");
  var $mic = $root.find("[data-chat-mic]");
  var $status = $root.find("[data-chat-status]");
  var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  var recognition = null;

  function setOpen(open) {
    $panel.prop("hidden", !open);
    $launcher.attr("aria-expanded", String(open));
    if (open) {
      window.requestAnimationFrame(function () {
        $input[0].focus({ preventScroll: true });
      });
    }
    else $launcher.trigger("focus");
  }

  function escapeHtml(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
  }

  function scrollToLatest() {
    $messages.stop(true).animate({ scrollTop: $messages[0].scrollHeight }, 160);
  }

  function scrollToMessageTop($message) {
    var target = $messages.scrollTop() + $message.position().top - 8;
    $messages.stop(true).animate({ scrollTop: Math.max(0, target) }, 180);
  }

  function addMessage(role, text, meta) {
    $messages.find(".mafsu-chat__welcome").remove();
    var className = role === "user" ? " mafsu-chat__message--user" : "";
    var evidence = "";
    if (meta && meta.pages && meta.pages.length) {
      evidence = '<p class="mafsu-chat__evidence">Prospectus pages: ' + escapeHtml(meta.pages.join(", ")) + "</p>";
    }
    var $message = $('<div class="mafsu-chat__message' + className + '"><div class="mafsu-chat__bubble"><p>' + escapeHtml(text) + "</p>" + evidence + "</div></div>");
    $messages.append($message);
    if (role === "assistant") scrollToMessageTop($message);
    else scrollToLatest();
  }

  function addOptions(options, field) {
    if (!options || !options.length || !field) return;
    var $options = $('<div class="mafsu-chat__options" aria-label="Answer choices"></div>');
    $.each(options, function (_, option) {
      $("<button type=\"button\"></button>")
        .text(option.label)
        .attr("data-option-value", option.value)
        .attr("data-option-label", option.label)
        .attr("data-option-field", field)
        .appendTo($options);
    });
    $messages.append($options);
  }

  function setBusy(busy) {
    config.busy = busy;
    $send.prop("disabled", busy);
    $mic.prop("disabled", busy || !SpeechRecognition);
    $input.prop("disabled", busy);
    $messages.find("[data-typing]").remove();
    if (busy) {
      $messages.find(".mafsu-chat__welcome").remove();
      $messages.append('<div class="mafsu-chat__message" data-typing><div class="mafsu-chat__typing" aria-label="Finding your answer"><i></i><i></i><i></i></div></div>');
      scrollToLatest();
    }
  }

  function setError(message) {
    $status.text(message || "The admissions assistant could not connect. Please try again.").prop("hidden", false);
  }

  function updateFromResponse(response) {
    if (response.language && /^(en|hi|mr)$/.test(response.language)) {
      config.language = response.language;
      $root.find("[data-language]").attr("aria-pressed", "false");
      $root.find('[data-language="' + response.language + '"]').attr("aria-pressed", "true");
    }
    if (response.sessionId) config.sessionId = response.sessionId;
    var neutralSource = /^(greeting|identity|language-preference|language-repeat|programme-clarify)$/.test(response.source || "");
    var programmeIsNeutral = !$root.find("[data-programme-select]").val();
    if (response.projectId && programmeNames[response.projectId] && !(neutralSource && programmeIsNeutral)) {
      if (response.projectId !== config.projectId) config.conversationState = {};
      config.projectId = response.projectId;
      $root.find("[data-programme-select]").val(response.projectId);
    }
    config.conversationState = $.extend({}, config.conversationState, response.slotUpdate || {});
    if (response.answer) {
      config.conversationState.lastAssistantAnswer = response.answer;
      config.conversationState.lastAssistantSource = response.source || "";
    }
    config.carryQuestion = response.carryQuestion || null;
  }

  function ask(question, statePatch, visibleLabel) {
    question = $.trim(question || "");
    if (!question || config.busy) return;
    $status.prop("hidden", true).empty();
    addMessage("user", visibleLabel || question);
    config.conversationState = $.extend({}, config.conversationState, statePatch || {});
    setBusy(true);

    $.ajax({
      url: config.apiBase + "/api/chat",
      method: "POST",
      contentType: "application/json; charset=utf-8",
      dataType: "json",
      timeout: 90000,
      data: JSON.stringify({
        question: question,
        uiLanguage: config.language,
        projectId: config.projectId,
        conversationState: config.conversationState,
        sessionId: config.sessionId
      })
    }).done(function (response) {
      setBusy(false);
      updateFromResponse(response);
      addMessage("assistant", response.answer, { pages: response.pages || [] });
      addOptions(response.interviewOptions || [], response.interviewField);
    }).fail(function (xhr) {
      setBusy(false);
      var message = xhr.status === 0
        ? "The admissions service is unreachable. Check the API address or website proxy."
        : "The admissions service returned an error (" + xhr.status + "). Please try again.";
      setError(message);
    }).always(function () {
      $input.prop("disabled", false).trigger("focus");
    });
  }

  function resetChat() {
    config.projectId = "bvsc";
    config.conversationState = {};
    config.carryQuestion = null;
    config.sessionId = null;
    $messages.html(welcomeHtml);
    $root.find("[data-programme-select]").val("");
    $status.prop("hidden", true).empty();
    $input.val("").css("height", "auto");
    updateComposerMeta();
  }

  function updateComposerMeta() {
    var length = String($input.val() || "").length;
    var maximum = Number($input.attr("maxlength")) || 1200;
    $charCount.text(length + " / " + maximum);
    $charCount.parent().attr("data-near-limit", String(length >= maximum * 0.85));
  }

  function setupSpeechInput() {
    if (!SpeechRecognition) {
      $mic.prop("disabled", true).attr("title", "Voice input is not supported in this browser");
      return;
    }
    recognition = new SpeechRecognition();
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = function () {
      $mic.attr("aria-pressed", "true").attr("aria-label", "Stop listening");
      $status.prop("hidden", true).empty();
    };
    recognition.onresult = function (event) {
      var transcript = event.results[0][0].transcript;
      $input.val(transcript).trigger("input").trigger("focus");
    };
    recognition.onerror = function (event) {
      if (event.error !== "aborted") setError("Voice input could not start. You can still type your question.");
    };
    recognition.onend = function () {
      $mic.attr("aria-pressed", "false").attr("aria-label", "Speak your question");
    };
  }

  $root.on("click", "[data-chat-action]", function () {
    var action = $(this).data("chat-action");
    if (action === "toggle") setOpen($panel.prop("hidden"));
    if (action === "close") setOpen(false);
    if (action === "reset" && !config.busy) resetChat();
  });

  $root.on("click", "[data-question]", function () {
    ask($(this).data("question"));
  });

  $root.on("click", "[data-language]", function () {
    config.language = $(this).data("language");
    $root.find("[data-language]").attr("aria-pressed", "false");
    $(this).attr("aria-pressed", "true");
  });

  $root.on("change", "[data-programme-select]", function () {
    var selected = String($(this).val() || "");
    config.projectId = programmeNames[selected] ? selected : "bvsc";
    config.conversationState = selected ? { programme: selected } : {};
    config.carryQuestion = null;
  });

  $root.on("click", "[data-option-value]", function () {
    var patch = {};
    var field = String($(this).data("option-field"));
    var value = String($(this).data("option-value"));
    var label = String($(this).data("option-label"));
    if (field === "projectId" && programmeNames[value]) {
      config.projectId = value;
      config.conversationState = { programme: value };
      $root.find("[data-programme-select]").val(value);
      $messages.find(".mafsu-chat__options button").prop("disabled", true);
      ask(config.carryQuestion || "How can you help me?", {}, label);
      return;
    }
    patch[field] = value;
    $messages.find(".mafsu-chat__options button").prop("disabled", true);
    ask(config.carryQuestion || ("Am I eligible for " + programmeNames[config.projectId] + "?"), patch, label);
  });

  $form.on("submit", function (event) {
    event.preventDefault();
    var question = $input.val();
    $input.val("").css("height", "auto");
    updateComposerMeta();
    ask(question);
  });

  $input.on("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $form.trigger("submit");
    }
  }).on("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 148) + "px";
    updateComposerMeta();
  });

  $(document).on("keydown.mafsuAdmissions", function (event) {
    if (event.key === "Escape" && !$panel.prop("hidden")) setOpen(false);
  });

  $mic.on("click", function () {
    if (!recognition || config.busy) return;
    recognition.lang = config.language === "hi" ? "hi-IN" : config.language === "mr" ? "mr-IN" : "en-IN";
    if ($mic.attr("aria-pressed") === "true") recognition.stop();
    else recognition.start();
  });

  setupSpeechInput();
  updateComposerMeta();
})(window.jQuery, window, document);
