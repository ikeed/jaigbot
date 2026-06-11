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
        "/public/js/aimsbot/message-presentation.js?v=" + assetVersion,
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

  function normalizeAssetPath(path) {
    return String(path || "").split("?")[0];
  }

  function ensureStylesheet(path) {
    const normalizedPath = normalizeAssetPath(path);
    if (!normalizedPath) return;
    const existing = Array.from(document.querySelectorAll('link[rel="stylesheet"]')).some(function (link) {
      return normalizeAssetPath(link.getAttribute("href")) === normalizedPath;
    });
    if (existing) return;

    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = path;
    document.head.appendChild(link);
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

  function fetchModuleConfig() {
    const configPaths = ["/api/config", "/config"];

    function fetchNext(index) {
      if (index >= configPaths.length) return Promise.resolve(null);
      return window.fetch(window.location.origin + configPaths[index], { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) return fetchNext(index + 1);
          return response.json();
        })
        .catch(function () {
          return fetchNext(index + 1);
        });
    }

    return fetchNext(0);
  }

  function loadModuleAssets() {
    return fetchModuleConfig()
      .then(function (config) {
        const activeModule = config && config.activeModule ? config.activeModule : null;
        const bundles = activeModule && Array.isArray(activeModule.frontendJsBundles)
          ? activeModule.frontendJsBundles.map(withVersion)
          : [];
        if (activeModule && activeModule.branding) {
          window.TrainingUI.activeModule = activeModule;
          window.TrainingUI.branding = activeModule.branding;
        }
        if (activeModule) {
          window.TrainingUI.activeModule = activeModule;
          window.TrainingUI.stylesheetStrategy = "manifest-driven";
          if (activeModule.frontendCss) {
            ensureStylesheet(withVersion(activeModule.frontendCss));
          }
          if (window.TrainingUI.messagePresentation && window.TrainingUI.messagePresentation.decorateMessages) {
            window.TrainingUI.messagePresentation.decorateMessages();
          }
        }
        if (!bundles.length) return;
        loadSequentially(bundles, function () {});
      });
  }

  loadSequentially(platformModules, loadModuleAssets);
})();
