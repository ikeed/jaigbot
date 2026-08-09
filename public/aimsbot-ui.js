/**
 * AIMSBot custom UI entry point.
 *
 * Chainlit accepts a single custom_js file, so this file stays as the stable
 * configured entry point and loads the focused modules in dependency order.
 */
(function () {
  "use strict";

  if (window.__aimsbotCustomJsInitialized) return;
  window.__aimsbotCustomJsInitialized = true;

  const assetVersion = "20260809-session-lock";
  window.AIMSBotUI = window.AIMSBotUI || {};
  window.AIMSBotUI.pendingWindowMessages = window.AIMSBotUI.pendingWindowMessages || [];
  window.AIMSBotUI.handleWindowMessagePayload =
    window.AIMSBotUI.handleWindowMessagePayload || null;

  window.addEventListener("message", function (event) {
    const app = window.AIMSBotUI || {};
    if (typeof app.handleWindowMessagePayload === "function") {
      app.handleWindowMessagePayload(event.data);
      return;
    }
    app.pendingWindowMessages = app.pendingWindowMessages || [];
    app.pendingWindowMessages.push(event.data);
  });

    const modules = [
        "/public/js/aimsbot/i18n.js?v=" + assetVersion,
        "/public/js/aimsbot/core.js?v=" + assetVersion,
        "/public/js/aimsbot/modal.js?v=" + assetVersion,
        "/public/js/aimsbot/report-issue.js?v=" + assetVersion,
        "/public/js/aimsbot/infographic.js?v=" + assetVersion,
        "/public/js/aimsbot/session-controls.js?v=" + assetVersion,
        "/public/js/aimsbot/header-actions.js?v=" + assetVersion,
        "/public/js/aimsbot/dictation.js?v=" + assetVersion,
        "/public/js/aimsbot/message-roles.js?v=" + assetVersion,
        "/public/js/aimsbot/splash.js?v=" + assetVersion,
        "/public/js/aimsbot/window-events.js?v=" + assetVersion
    ];

    function loadNext(index) {
    if (index >= modules.length) return;

      const script = document.createElement("script");
      script.src = modules[index];
    script.async = false;
    script.onload = function () {
      loadNext(index + 1);
    };
    script.onerror = function () {
      // Keep the page usable if one optional customization fails to load.
      loadNext(index + 1);
    };
    document.head.appendChild(script);
  }

  loadNext(0);
})();
