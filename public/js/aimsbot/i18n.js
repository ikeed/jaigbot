(function (window) {
  "use strict";

  const app = window.AIMSBotUI = window.AIMSBotUI || {};
  app.messages = app.messages || {
    dictation: {
      lang: "en-US",
      errors: {
        blocked: "Microphone access was blocked.",
        unavailable: "No microphone was available.",
        noSpeech: "No speech was detected.",
        network: "Voice recognition could not reach the speech service.",
        cancelled: "Voice dictation was cancelled.",
        unexpected: "Voice dictation hit an unexpected error.",
        unsupported: "Voice dictation is not supported in this browser.",
        unavailableShort: "Voice input unavailable",
        startFailed: "Voice dictation could not start."
      },
      start: "Start voice dictation",
      stop: "Stop voice dictation",
      listening: "Listening..."
    },
    modal: {
      cancel: "Cancel",
      emptyReason: "Please provide a reason."
    },
    reportIssue: {
      title: "Report Issue",
      description: "Describe the issue you encountered. This will end the session and log a report.",
      placeholder: "What went wrong?",
      confirm: "Submit Report"
    },
    session: {
      newTitle: "New Scenario",
      newDescription: "This will clear your current chat history and start a fresh session. Are you sure you want to continue?",
      confirm: "Confirm",
      logoutTitle: "Logout",
      logoutDescription: "Are you sure you want to logout? This will end your current session.",
      logoutConfirm: "Logout",
      loggingOut: "Logging out",
      logoutMatchers: ["logout", "sign out"]
    },
    infographic: {
      title: "Review the AIMS approach",
      intro: "This bot is going to help you to practice the AIMS communication protocol for helping address vaccine hesitancy. Before you start, please review this infographic so you are best equipped to have a conversation with our vaccine hesitant patients.",
      close: "Close",
      start: "Start practicing",
      alt: "Addressing Vaccine Hesitancy with the AIMS Communication Approach infographic"
    },
    roles: {
      doctor: "Doctor",
      assistant: "Assistant",
      coach: "Coach",
      system: "System",
      defaultAuthor: "default",
      clinician: "Clinician",
      patient: "Patient",
      scenario: "Scenario",
      avatarFor: "Avatar for {name}",
      personaPatterns: [
        "(?:^|\\n)Person:\\s*([^\\n]+)",
        "(?:^|\\n)Parent:\\s*([^\\n]+)",
        "(?:^|\\n)Parent\\/Patient:\\s*([^\\n]+)",
        "(?:^|\\n)Patient:\\s*([^\\n]+)"
      ]
    },
    copy: {
      title: "Copy to clipboard"
    },
    header: {
      infographic: "AIMS infographic",
      reportIssue: "Report Issue"
    },
    splash: {
      recovery: "Loading is taking longer than usual, refreshing..."
    }
  };

  app.t = app.t || function (path, values) {
    const parts = String(path || "").split(".");
    let current = app.messages;
    for (const part of parts) {
      if (!current || typeof current !== "object" || !(part in current)) return path;
      current = current[part];
    }
    if (typeof current !== "string") return current;
    return current.replace(/\{([a-zA-Z0-9_]+)\}/g, function (_, key) {
      return values && values[key] != null ? String(values[key]) : "";
    });
  };
})(window);
