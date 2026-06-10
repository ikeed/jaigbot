(function (window, document) {
  "use strict";

  const app = window.TrainingUI || window.AIMSBotUI;
  if (!app || app.dictationReady) return;

  app.dictationReady = true;

  const dictation = app.dictation = app.dictation || {};
  const state = dictation.state = {
    status: "idle",
    message: "",
    activeTextarea: null,
    recognition: null,
    session: null,
    stopRequested: false
  };

  function getRecognitionCtor(targetWindow) {
    const source = targetWindow || window;
    return source.SpeechRecognition || source.webkitSpeechRecognition || null;
  }

  function composerRoots() {
    return document.querySelectorAll("form.aimsbot-composer, #message-composer");
  }

  function joinTranscriptParts(left, right) {
    const first = String(left || "").trim();
    const second = String(right || "").trim();
    if (!first) return second;
    if (!second) return first;
    return first + " " + second;
  }

  function composeTextareaValue(baseText, finalText, interimText) {
    const combinedTranscript = joinTranscriptParts(finalText, interimText);
    if (!String(baseText || "").trim()) return combinedTranscript;
    if (!combinedTranscript) return String(baseText || "");

    const base = String(baseText || "");
    const separator = /\s$/.test(base) ? "" : " ";
    return base + separator + combinedTranscript;
  }

  function describeError(errorCode) {
    switch (String(errorCode || "")) {
      case "not-allowed":
      case "service-not-allowed":
        return "Microphone access was blocked.";
      case "audio-capture":
        return "No microphone was available.";
      case "no-speech":
        return "No speech was detected.";
      case "network":
        return "Voice recognition could not reach the speech service.";
      case "aborted":
        return "Voice dictation was cancelled.";
      default:
        return "Voice dictation hit an unexpected error.";
    }
  }

  function setTextareaValue(textarea, nextValue) {
    if (!textarea || typeof textarea.dispatchEvent !== "function") return;
    const prototype = Object.getPrototypeOf(textarea);
    const descriptor = prototype ? Object.getOwnPropertyDescriptor(prototype, "value") : null;
    if (descriptor && typeof descriptor.set === "function") {
      descriptor.set.call(textarea, nextValue);
    } else {
      textarea.value = nextValue;
    }

    try {
      textarea.dispatchEvent(new window.InputEvent("input", { bubbles: true, data: nextValue }));
    } catch (_) {
      textarea.dispatchEvent(new window.Event("input", { bubbles: true }));
    }
    textarea.dispatchEvent(new window.Event("change", { bubbles: true }));
  }

  function setStatus(status, message) {
    state.status = status;
    state.message = message || "";

    document.querySelectorAll(".aims-dictation-button").forEach(function (button) {
      button.setAttribute("data-dictation-state", status);
      button.setAttribute("aria-pressed", status === "listening" ? "true" : "false");
      button.classList.toggle("aims-dictation-active", status === "listening");
      button.disabled = status === "unsupported";
      const title = message || (
        status === "unsupported"
          ? "Voice dictation is not supported in this browser."
          : status === "listening"
            ? "Stop voice dictation"
            : "Start voice dictation"
      );
      button.title = title;
      button.setAttribute("aria-label", title);
    });
  }

  function stopRecognition() {
    const recognition = state.recognition;
    if (!recognition) return;
    state.stopRequested = true;
    recognition.stop();
  }

  function clearSession() {
    state.activeTextarea = null;
    state.recognition = null;
    state.session = null;
    state.stopRequested = false;
  }

  function handleRecognitionEnd() {
    const message = !state.stopRequested ? state.message : "";
    clearSession();
    setStatus("idle", message);
  }

  function updateTextareaFromSession() {
    if (!state.session || !state.activeTextarea) return;
    const nextValue = composeTextareaValue(
      state.session.baseText,
      state.session.finalText,
      state.session.interimText
    );
    setTextareaValue(state.activeTextarea, nextValue);
  }

  function startRecognition(textarea) {
    const RecognitionCtor = getRecognitionCtor(window);
    if (!RecognitionCtor) {
      setStatus("unsupported", "Voice input unavailable");
      return;
    }

    if (state.recognition) {
      stopRecognition();
      return;
    }

    const recognition = new RecognitionCtor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    state.activeTextarea = textarea;
    state.recognition = recognition;
    state.session = {
      baseText: textarea.value || "",
      finalText: "",
      interimText: ""
    };
    state.stopRequested = false;

    recognition.onstart = function () {
      setStatus("listening", "Listening...");
    };

    recognition.onresult = function (event) {
      if (!state.session) return;

      let finalText = state.session.finalText;
      let interimText = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result && result[0] && result[0].transcript ? result[0].transcript.trim() : "";
        if (!transcript) continue;
        if (result.isFinal) {
          finalText = joinTranscriptParts(finalText, transcript);
        } else {
          interimText = joinTranscriptParts(interimText, transcript);
        }
      }

      state.session.finalText = finalText;
      state.session.interimText = interimText;
      updateTextareaFromSession();
    };

    recognition.onerror = function (event) {
      setStatus("idle", describeError(event && event.error));
    };

    recognition.onend = function () {
      handleRecognitionEnd();
    };

    try {
      recognition.start();
    } catch (_) {
      handleRecognitionEnd();
      setStatus("idle", "Voice dictation could not start.");
    }
  }

  function createMicButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = app.chainlitIconButtonClass + " aims-dictation-button";
    button.setAttribute("aria-label", "Start voice dictation");
    button.setAttribute("aria-pressed", "false");
    button.setAttribute("data-dictation-state", "idle");
    button.title = "Start voice dictation";
    button.innerHTML = [
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">',
      '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z"></path>',
      '<path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>',
      '<line x1="12" y1="19" x2="12" y2="22"></line>',
      '<line x1="8" y1="22" x2="16" y2="22"></line>',
      "</svg>"
    ].join("");
    return button;
  }

  function injectComposerControls() {
    const RecognitionCtor = getRecognitionCtor(window);
    composerRoots().forEach(function (composer) {
      if (composer.getAttribute("data-aims-dictation-bound") === "true") return;

      const textarea = composer.querySelector("textarea");
      const submitButton =
        composer.querySelector('button[type="submit"]') ||
        composer.querySelector("#chat-submit");
      if (!textarea || !submitButton) return;

      composer.classList.add("aimsbot-composer");
      textarea.classList.add("aimsbot-composer-input");

      const micButton = createMicButton();
      micButton.disabled = !RecognitionCtor;
      if (!RecognitionCtor) {
        micButton.setAttribute("data-dictation-state", "unsupported");
        micButton.title = "Voice dictation is not supported in this browser.";
      }

      micButton.addEventListener("click", function (event) {
        app.prevent(event);
        if (!getRecognitionCtor(window)) {
          setStatus("unsupported", "Voice input unavailable");
          return;
        }
        if (state.recognition && state.activeTextarea === textarea) {
          stopRecognition();
          return;
        }
        if (state.recognition && state.activeTextarea && state.activeTextarea !== textarea) {
          stopRecognition();
        }
        startRecognition(textarea);
      });

      const stopActiveRecognition = function () {
        if (state.activeTextarea === textarea && state.recognition) {
          stopRecognition();
        }
      };
      composer.addEventListener("submit", stopActiveRecognition);
      submitButton.addEventListener("click", stopActiveRecognition);

      const submitContainer = submitButton.parentElement || composer;
      submitContainer.insertBefore(micButton, submitButton);
      composer.setAttribute("data-aims-dictation-bound", "true");
    });

    if (!RecognitionCtor) {
      setStatus("unsupported", "Voice input unavailable");
    } else if (!state.recognition && state.status !== "idle") {
      setStatus("idle", "");
    }
  }

  function ensureActiveTextareaStillMounted() {
    if (state.activeTextarea && !document.body.contains(state.activeTextarea) && state.recognition) {
      stopRecognition();
    }
  }

  let debounce = null;
  const observer = new MutationObserver(function () {
    if (debounce) return;
    debounce = window.setTimeout(function () {
      debounce = null;
      injectComposerControls();
      ensureActiveTextareaStillMounted();
    }, 100);
  });

  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  }

  injectComposerControls();
  window.setTimeout(injectComposerControls, 300);
  window.setTimeout(injectComposerControls, 1000);
  window.setTimeout(injectComposerControls, 3000);

  dictation.injectComposerControls = injectComposerControls;
  dictation.stopRecognition = stopRecognition;
  dictation.testHooks = {
    getRecognitionCtor: getRecognitionCtor,
    joinTranscriptParts: joinTranscriptParts,
    composeTextareaValue: composeTextareaValue,
    describeError: describeError
  };
})(window, document);
