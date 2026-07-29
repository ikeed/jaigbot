(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.splashReady) return;

  app.splashReady = true;
  app.state.startupStorageKey = app.state.startupStorageKey || "aimsbot.startupRecoveryAttempted";
  app.state.startupRecoveryMs = app.state.startupRecoveryMs || 15000;
  app.state.chatPath = app.state.chatPath || "/chat";

  function hasStartupContent() {
      const hasScenarioOrMessage = !!document.querySelector(
          ".aims-scenario-briefing, [data-step-type], [data-author]"
      );
      if (hasScenarioOrMessage) return true;

      const introModal = document.getElementById("aims-infographic-modal");
      return !!(
          introModal &&
          introModal.getAttribute("aria-hidden") === "false" &&
          introModal.style.display !== "none"
      );
  }

  function markStartupLoaded() {
      app.state.startupResolved = true;
      try {
          window.sessionStorage.removeItem(app.state.startupStorageKey);
      } catch (_) {}
  }

  function showRecoveryMessage(message) {
      const div = document.createElement("div");
      div.id = "aimsbot-recovery-message";
      div.style.position = "fixed";
      div.style.bottom = "24px";
      div.style.left = "50%";
      div.style.transform = "translateX(-50%)";
      div.style.padding = "12px 20px";
      div.style.background = "rgba(15, 23, 42, 0.9)";
      div.style.color = "#fff";
      div.style.borderRadius = "8px";
      div.style.zIndex = "999999";
      div.style.fontSize = "14px";
      div.style.fontFamily = "sans-serif";
      div.style.boxShadow = "0 4px 12px rgba(0, 0, 0, 0.2)";
      div.style.backdropFilter = "blur(4px)";
      div.textContent = message;
      document.body.appendChild(div);
  }

  function recoverFromStartupTimeout() {
      if (app.state.startupResolved || hasStartupContent()) {
          markStartupLoaded();
          return;
      }

      let alreadyTriedReload = false;
      try {
          alreadyTriedReload = window.sessionStorage.getItem(app.state.startupStorageKey) === "1";
      } catch (_) {}

      if (!alreadyTriedReload) {
          try {
              window.sessionStorage.setItem(app.state.startupStorageKey, "1");
          } catch (_) {}

          showRecoveryMessage(app.t("splash.recovery"));
          window.setTimeout(function () {
              window.location.reload();
          }, 1000);
          return;
      }

      try {
          window.sessionStorage.removeItem(app.state.startupStorageKey);
      } catch (_) {}
      window.location.assign(app.state.chatPath + "/logout?reason=startup_timeout");
  }

  function startStartupRecoveryTimer() {
      if (app.state.startupTimerStarted) return;
      if (window.location.pathname.indexOf(app.state.chatPath) !== 0) return;
      app.state.startupTimerStarted = true;
      window.setTimeout(recoverFromStartupTimeout, app.state.startupRecoveryMs);
  }

  function revealComposerWhenMessagesAppear(form) {
      const observer = new MutationObserver(function () {
          if (!hasStartupContent()) return;
          markStartupLoaded();
          form.style.display = "";
          observer.disconnect();
      });
      observer.observe(document.body, { childList: true, subtree: true });
  }

  function tweakSplash() {
    document.querySelectorAll("img").forEach(function (img) {
        const src = (img.src || "").toLowerCase();
        if (src.indexOf("aimsbot") === -1) return;

      img.style.width = "256px";
      img.style.height = "256px";
      img.style.maxWidth = "none";
      img.style.maxHeight = "none";
    });

    if (document._aimsComposerHidden) return;

    document.querySelectorAll("textarea[placeholder]").forEach(function (textarea) {
      if (textarea.id === "report-issue-modal-input") return;
      if (textarea.closest("#report-issue-modal")) return;

        const form = textarea.closest("form");
        if (!form || form._aimsHidden) return;

      form._aimsHidden = true;
      form.style.display = "none";
      document._aimsComposerHidden = form;
      revealComposerWhenMessagesAppear(form);
    });
  }

  tweakSplash();
  if (hasStartupContent()) {
      markStartupLoaded();
  } else {
      startStartupRecoveryTimer();
  }
  window.setTimeout(tweakSplash, 300);
  window.setTimeout(tweakSplash, 800);
  window.setTimeout(tweakSplash, 1500);

  app.splash = {
    tweak: tweakSplash,
    markStartupLoaded: markStartupLoaded,
    testHooks: {
      hasStartupContent: hasStartupContent,
      recoverFromStartupTimeout: recoverFromStartupTimeout,
      startStartupRecoveryTimer: startStartupRecoveryTimer
    }
  };
})(window, document);
