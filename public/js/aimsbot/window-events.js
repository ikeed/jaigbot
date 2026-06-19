(function (window) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.windowEventsReady) return;

  app.windowEventsReady = true;

  function handlePayload(payload) {
      const type = app.messageType(payload);
      let data = payload;
      if (typeof data === "string") {
      try {
        data = JSON.parse(data);
      } catch (_) {
        data = {};
      }
    }

    if (type === "on_duplicate_tab") {
      window.location.href = "/duplicate";
    } else if (type === "on_logout") {
      window.location.href = "/";
    } else if (type === "aims_intro_required") {
      app.infographic.show(true);
    } else if (type === "aims_persona_name" && data.personaName) {
      app.state = app.state || {};
      app.state.personaName = String(data.personaName).trim();
      if (app.messageRoles && app.messageRoles.injectDataAuthors) {
        app.messageRoles.injectDataAuthors();
      }
    } else if (type === "aims_thread_bound" && data.threadId) {
      const path = window.location.pathname;
      if (path === "/chat" || path === "/chat/") {
        window.history.replaceState(
          null,
          "",
          window.location.origin + "/chat/thread/" + encodeURIComponent(String(data.threadId))
        );
      }
    }
  }

  app.handleWindowMessagePayload = handlePayload;

  (app.pendingWindowMessages || []).forEach(handlePayload);
  app.pendingWindowMessages = [];
})(window);
