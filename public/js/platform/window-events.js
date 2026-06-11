(function (window) {
  "use strict";

    const app = window.TrainingUI;
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
    } else if ((type === "training_resume_thread" || type === "aims_resume_thread") && data.threadId) {
        const target = "/chat/thread/" + encodeURIComponent(data.threadId);
        if (window.location.pathname !== target) {
        window.location.replace(target);
      }
    } else if (type === "training_intro_required" || type === "aims_intro_required") {
      app.emitLifecycleEvent("intro_required", data);
    } else if (type === "training_participant_name" || type === "aims_persona_name") {
      const participantName = data.participantName || data.personaName;
      if (!participantName) return;
      app.state = app.state || {};
      app.state.participantName = String(participantName).trim();
      if (app.messagePresentation && app.messagePresentation.decorateMessages) {
        app.messagePresentation.decorateMessages();
      }
    }
  }

  app.handleWindowMessagePayload = handlePayload;

  (app.pendingWindowMessages || []).forEach(handlePayload);
  app.pendingWindowMessages = [];
})(window);
