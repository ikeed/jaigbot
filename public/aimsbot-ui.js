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

  var modules = [
    "/public/js/aimsbot/core.js",
    "/public/js/aimsbot/modal.js",
    "/public/js/aimsbot/report-issue.js",
    "/public/js/aimsbot/infographic.js",
    "/public/js/aimsbot/session-controls.js",
    "/public/js/aimsbot/header-actions.js",
    "/public/js/aimsbot/message-roles.js",
    "/public/js/aimsbot/splash.js",
    "/public/js/aimsbot/window-events.js"
  ];

  function loadNext(index) {
    if (index >= modules.length) return;

    var script = document.createElement("script");
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
