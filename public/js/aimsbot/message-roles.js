(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.messageRolesReady) return;

  app.messageRolesReady = true;

  const labels = {
    doctor: app.t("roles.doctor"),
    assistant: app.t("roles.assistant"),
    coach: app.t("roles.coach"),
    system: app.t("roles.system"),
    defaultAuthor: app.t("roles.defaultAuthor"),
    clinician: app.t("roles.clinician"),
    patient: app.t("roles.patient"),
    scenario: app.t("roles.scenario")
  };

  function normalizedRole(author) {
    if (author === labels.doctor) return labels.doctor;
    if (author === labels.coach) return labels.coach;
    if (author === labels.system) return labels.system;
    if (!author || author === labels.defaultAuthor) return "";
    return labels.assistant;
  }

  function avatarSrcForRole(role) {
    if (role === labels.doctor) return "/public/avatars/doctor.svg?v=3";
    if (role === labels.assistant) return "/public/avatars/assistant.svg?v=3";
    if (role === labels.coach) return "/public/avatars/coach.svg?v=3";
    if (role === labels.system) return "/public/avatars/system.svg?v=3";
    return "";
  }

  function extractPersonaName(text) {
    const source = String(text || "");
    const patterns = (app.t("roles.personaPatterns") || []).map(function (pattern) {
      return new RegExp(pattern, "i");
    });

    for (const pattern of patterns) {
      const match = source.match(pattern);
      if (match && match[1]) return match[1].trim();
    }
    return "";
  }

  function getPersonaName() {
    const cached = String((app.state && app.state.personaName) || "").trim();
    if (cached) return cached;

    const systemMessages = document.querySelectorAll('.ai-message[data-aims-role="' + labels.system + '"] .message-content, .ai-message[data-author="' + labels.system + '"] .message-content');
    for (const message of systemMessages) {
      const name = extractPersonaName(message.innerText || message.textContent || "");
      if (name) {
        app.state = app.state || {};
        app.state.personaName = name;
        return name;
      }
    }

    return "";
  }

  function roleLabel(author) {
    if (author === labels.doctor) return labels.clinician;
    if (normalizedRole(author) === labels.assistant) return getPersonaName() || (author !== labels.assistant ? author : "") || labels.patient;
    if (author === labels.coach) return labels.coach;
    if (author === labels.system) return labels.scenario;
    return author || "";
  }

  function decorateMessageSurface(step, content, author) {
    if (!step || !content || !author) return;
    step.setAttribute("data-role-label", roleLabel(author));
    if (!step.hasAttribute("data-aims-animated")) {
      step.setAttribute("data-aims-animated", "true");
      step.classList.add("aims-message-enter");
    }
    content.setAttribute("data-role-label", roleLabel(author));
  }

  function tagAiMessage(message) {
      let author = message.getAttribute("data-author");
      if (!author) {
        const avatarPrefix = app.t("roles.avatarFor", { name: "" });
        const img = message.querySelector('img[alt^="' + avatarPrefix + '"]');
        if (img) author = img.alt.replace(avatarPrefix, "").trim();
    }
    const role = normalizedRole(author);
    if (!role) return;

    message.setAttribute("data-author", author);
    message.setAttribute("data-aims-role", role);
    if (role === labels.system) {
        const systemImg = message.querySelector('img[alt="' + app.t("roles.avatarFor", { name: labels.system }) + '"]');
        if (systemImg) systemImg.src = avatarSrcForRole(labels.system);
    }
    if (role === labels.coach) {
        const coachImg = message.querySelector('img[alt="' + app.t("roles.avatarFor", { name: labels.coach }) + '"]');
        if (coachImg) coachImg.src = avatarSrcForRole(labels.coach);
    }
    if (role === labels.assistant) {
        const personaName = getPersonaName() || (author !== labels.assistant ? author : "");
        const assistantImg = message.querySelector('img[alt^="' + app.t("roles.avatarFor", { name: "" }) + '"]');
        if (assistantImg && personaName) {
          assistantImg.src = avatarSrcForRole(labels.assistant);
          const tooltip = app.t("roles.avatarFor", { name: personaName });
          assistantImg.alt = tooltip;
          assistantImg.title = tooltip;
          assistantImg.setAttribute("aria-label", tooltip);
        }
    }

      const step = message.closest("[data-step-type]");
      if (step) {
      step.setAttribute("data-author", author);
      step.setAttribute("data-aims-role", role);
      step.classList.add("aims-message-row");
      decorateMessageSurface(step, message.querySelector(".message-content"), author);
      if (role === labels.coach || role === labels.system) {
        injectCopyButton(step);
      }
    }

      const content = message.querySelector(".message-content");
      if (content) {
      content.classList.add("aims-message-bubble");
      content.setAttribute("data-role-label", roleLabel(author));
    }
  }

  function tagDoctorMessage(step) {
    step.setAttribute("data-author", labels.doctor);
    step.classList.add("aims-message-row");

      const content = step.querySelector(".message-content");
      if (!content) return;
      decorateMessageSurface(step, content, labels.doctor);

      const bubble = content.closest(".relative") || content;
      bubble.classList.add("aims-message-bubble");
      bubble.setAttribute("data-role-label", roleLabel(labels.doctor));

      const row = bubble.parentElement;
      if (!row || row.querySelector(".aims-doctor-avatar")) {
      if (row && !row.querySelector(".aims-copy-button")) {
        injectCopyButton(step);
      }
      return;
    }

      const avatarBase = window.location.pathname.indexOf("/chat") === 0 ? "/chat" : "";
      const avatar = document.createElement("span");
      avatar.className = "aims-doctor-avatar";
    avatar.setAttribute("data-state", "closed");
    avatar.innerHTML = '<img alt="' + app.t("roles.avatarFor", { name: labels.doctor }) + '" src="' + avatarSrcForRole(labels.doctor) + '" />';
    row.appendChild(avatar);

    injectCopyButton(step);
  }

  function injectCopyButton(step) {
      const author = step.getAttribute("data-author");
      if (!author) return;

      const content = step.querySelector(".message-content");
      if (!content) return;

    // Check if copy button already exists (either Chainlit's or ours)
    if (step.querySelector(".aims-copy-button") || (author === labels.assistant && step.querySelector(".lucide-copy"))) return;

      let container = content.parentElement;
      if (author === labels.doctor) {
      // For Doctor messages, the .message-content is wrapped in a bubble div.
      // We want to append the action row below the flex row containing bubble + avatar.
        const bubble = content.closest(".aims-message-bubble");
        if (bubble && bubble.parentElement) {
        container = bubble.parentElement.parentElement;
      }
    }
    if (!container) return;

      let actionRow = step.querySelector(".flex.items-center.flex-wrap");
      if (!actionRow) {
      actionRow = document.createElement("div");
      actionRow.className = "-ml-1.5 flex items-center flex-wrap aims-injected-actions";
      container.appendChild(actionRow);
    }

      const copyBtn = document.createElement("button");
      copyBtn.className = app.chainlitIconButtonClass + " aims-copy-button";
    copyBtn.setAttribute("data-state", "closed");
    copyBtn.setAttribute("title", app.t("copy.title"));
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-copy h-4 w-4" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>';
    
    copyBtn.addEventListener("click", function(e) {
      app.prevent(e);
        const text = content.innerText || "";
        if (text) {
        navigator.clipboard.writeText(text).then(function() {
            const originalHtml = copyBtn.innerHTML;
            copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-check h-4 w-4" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';
          setTimeout(function() {
            copyBtn.innerHTML = originalHtml;
          }, 2000);
        });
      }
    });

    actionRow.appendChild(copyBtn);
  }

  function injectDataAuthors() {
    document.querySelectorAll(".ai-message").forEach(tagAiMessage);
    document.querySelectorAll('[data-step-type="user_message"]').forEach(tagDoctorMessage);
  }

  function findComposer() {
    return (
      document.getElementById("message-composer") ||
      document.querySelector("form.aimsbot-composer") ||
      document.querySelector("textarea[placeholder]")?.closest("form")
    );
  }

  function decorateMessageLayout() {
    const composer = findComposer();
    const main = composer ? composer.closest("main") : document.querySelector("main");
    const scrollArea = main ? main.querySelector(".overflow-y-auto") : null;
    if (!scrollArea || !composer) return null;

    const messageList =
      scrollArea.querySelector(".flex.flex-col.mx-auto.w-full.flex-grow") ||
      scrollArea.firstElementChild;
    const composerHeight = Math.ceil(composer.getBoundingClientRect().height || 144);
    const clearance = Math.max(208, composerHeight + 80);

    scrollArea.classList.add("aimsbot-message-scroll");
    scrollArea.style.setProperty("--aims-composer-clearance", clearance + "px");
    if (messageList) {
      messageList.classList.add("aimsbot-message-list");
      messageList.style.setProperty("--aims-composer-clearance", clearance + "px");
    }

    return { scrollArea, clearance };
  }

  function keepLatestMessageVisible() {
    const layout = decorateMessageLayout();
    if (!layout) return;

    const distanceFromBottom =
      layout.scrollArea.scrollHeight -
      layout.scrollArea.scrollTop -
      layout.scrollArea.clientHeight;
    const nearBottomThreshold = Math.max(layout.clearance + 420, 640);
    if (distanceFromBottom <= nearBottomThreshold) {
      layout.scrollArea.scrollTop = layout.scrollArea.scrollHeight;
    }
  }

  function refreshMessages() {
    injectDataAuthors();
    keepLatestMessageVisible();
    if (app.applyComposerLockState) app.applyComposerLockState();
  }

    let debounce = null;
    const observer = new MutationObserver(function () {
        if (debounce) return;
        debounce = window.setTimeout(function () {
            debounce = null;
            refreshMessages();
        }, 100);
    });

    observer.observe(document.body, { childList: true, subtree: true });
  refreshMessages();
  window.setTimeout(refreshMessages, 300);
  window.setTimeout(refreshMessages, 1000);
  window.setTimeout(refreshMessages, 3000);

  app.messageRoles = {
    injectDataAuthors: refreshMessages
  };
})(window, document);
