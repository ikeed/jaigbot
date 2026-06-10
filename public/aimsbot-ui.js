/**
 * Stable Chainlit UI entry point.
 *
 * Chainlit accepts a single custom_js file, so this file remains the stable
 * bootstrap and then loads generic platform modules plus active-module assets.
 */
(function () {
  "use strict";

  if (window.__aimsbotCustomJsInitialized) return;
  window.__aimsbotCustomJsInitialized = true;

  const assetVersion = "20260610-platform-1";
  window.TrainingUI = window.TrainingUI || {};
  window.AIMSBotUI = window.TrainingUI;
  window.TrainingUI.pendingWindowMessages = window.TrainingUI.pendingWindowMessages || [];
  window.TrainingUI.handleWindowMessagePayload =
    window.TrainingUI.handleWindowMessagePayload || null;

  window.addEventListener("message", function (event) {
    const app = window.TrainingUI || {};
    if (typeof app.handleWindowMessagePayload === "function") {
      app.handleWindowMessagePayload(event.data);
      return;
    }
    app.pendingWindowMessages = app.pendingWindowMessages || [];
    app.pendingWindowMessages.push(event.data);
  });

  const platformModules = [
        "/public/js/aimsbot/core.js?v=" + assetVersion,
        "/public/js/aimsbot/modal.js?v=" + assetVersion,
        "/public/js/aimsbot/report-issue.js?v=" + assetVersion,
        "/public/js/aimsbot/session-controls.js?v=" + assetVersion,
        "/public/js/aimsbot/dictation.js?v=" + assetVersion,
        "/public/js/aimsbot/splash.js?v=" + assetVersion,
        "/public/js/aimsbot/window-events.js?v=" + assetVersion
    ];

  function withVersion(path) {
    return path.indexOf("?") === -1 ? path + "?v=" + assetVersion : path + "&v=" + assetVersion;
  }

  function loadSequentially(modules, done) {
    function loadNext(index) {
      if (index >= modules.length) {
        if (typeof done === "function") done();
        return;
      }

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
  }

  function loadModuleAssets() {
    const configUrl = window.location.origin + "/config";
    return window.fetch(configUrl, { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) return null;
        return response.json();
      })
      .then(function (config) {
        const activeModule = config && config.activeModule ? config.activeModule : null;
        const bundles = activeModule && Array.isArray(activeModule.frontendJsBundles)
          ? activeModule.frontendJsBundles.map(withVersion)
          : [];
        if (activeModule && activeModule.branding) {
          window.TrainingUI.activeModule = activeModule;
          window.TrainingUI.branding = activeModule.branding;
        }
        if (!bundles.length) return;
        loadSequentially(bundles, function () {});
      })
      .catch(function () {
        // Keep the chat shell usable even if config lookup fails.
      });
  }

  loadSequentially(platformModules, loadModuleAssets);
})();
