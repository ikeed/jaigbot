(function (window) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.windowEventsReady) return;

  app.windowEventsReady = true;

  window.addEventListener("message", function (event) {
      const type = app.messageType(event.data);
      let data = event.data;
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
    } else if (type === "aims_resume_thread" && data.threadId) {
        const target = "/chat/thread/" + encodeURIComponent(data.threadId);
        if (window.location.pathname !== target) {
        window.location.replace(target);
      }
    } else if (type === "aims_intro_required") {
      app.infographic.show(true);
    }
  });
})(window);
