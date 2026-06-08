(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI = window.AIMSBotUI || {};
    if (app.coreReady) return;

  app.coreReady = true;
  app.state = app.state || {};
  app.state.logoutInProgress = false;
  app.state.pendingIntroStorageKey = "aimsbot.pendingIntro";

  app.managedModalSelector = [
    "#report-issue-modal",
    "#new-session-modal",
    "#logout-modal",
    "#aims-infographic-modal"
  ].join(", ");

  app.chainlitIconButtonClass = [
    "inline-flex",
    "items-center",
    "justify-center",
    "gap-2",
    "whitespace-nowrap",
    "rounded-md",
    "text-sm",
    "font-medium",
    "ring-offset-background",
    "transition-colors",
    "focus-visible:outline-none",
    "focus-visible:ring-2",
    "focus-visible:ring-ring",
    "focus-visible:ring-offset-2",
    "disabled:pointer-events-none",
    "disabled:opacity-50",
    "[&_svg]:pointer-events-none",
    "[&_svg]:size-4",
    "[&_svg]:shrink-0",
    "hover:bg-accent",
    "h-9",
    "w-9",
    "text-muted-foreground",
    "hover:text-muted-foreground"
  ].join(" ");

  app.removeManagedModals = function () {
    document.querySelectorAll(app.managedModalSelector).forEach(function (modal) {
      modal.remove();
    });
  };

  app.prevent = function (event) {
    if (!event) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.stopImmediatePropagation) event.stopImmediatePropagation();
  };

  app.postToChainlit = function (payload) {
    window.postMessage(JSON.stringify(payload), "*");
  };

  app.isLoginCallbackRoute = function () {
    return window.location.pathname.indexOf("/login/callback") !== -1;
  };

  app.isChatShellReady = function () {
    return !!document.getElementById("header");
  };

  app.messageType = function (data) {
    if (typeof data === "string") {
      try {
        return (JSON.parse(data) || {}).type || data;
      } catch (_) {
        return data;
      }
    }
    return data && data.type;
  };

  app.findHeaderActions = function () {
      const header = document.getElementById("header");
      if (!header) return null;
    return header.querySelector("div.flex.items-center.gap-1") || header.lastElementChild;
  };

  if (window.location.search.indexOf("aims_new=1") !== -1) {
    window.history.replaceState(null, "", window.location.origin + "/chat");
  }

  app.removeManagedModals();
})(window, document);
