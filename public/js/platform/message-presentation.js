(function (window, document) {
  "use strict";

  const app = window.TrainingUI || window.AIMSBotUI;
  if (!app || app.messagePresentationReady) return;
  app.messagePresentationReady = true;

  function activeDialogueRoles() {
    return (app.activeModule && app.activeModule.dialogueRoles) || {};
  }

  function displayNames() {
    return activeDialogueRoles().displayNames || {};
  }

  function roleList(name) {
    const value = activeDialogueRoles()[name];
    return Array.isArray(value) ? value.filter(Boolean) : [];
  }

  function firstRole(name, fallback) {
    const list = roleList(name);
    return list.length ? String(list[0]) : fallback;
  }

  function displayNameForRole(role, fallback) {
    const name = displayNames()[role];
    return typeof name === "string" && name.trim() ? name.trim() : fallback;
  }

  function counterpartDisplayName() {
    const participantName = String((app.state && app.state.participantName) || "").trim();
    if (participantName) return participantName;

    const counterpartRole = firstRole("counterpartRoles", "assistant");
    const brandingName = app.branding && app.branding.avatarName;
    return displayNameForRole(counterpartRole, brandingName || "Assistant");
  }

  function userDisplayName() {
    const userRole = firstRole("userRoles", "user");
    return displayNameForRole(userRole, "User");
  }

  function feedbackDisplayName() {
    const feedbackRole = firstRole("feedbackRoles", "coach");
    return displayNameForRole(feedbackRole, "Coach");
  }

  function metadataDisplayName() {
    return displayNameForRole("system", "System");
  }

  function normalizedRole(author) {
    const raw = String(author || "").trim();
    if (!raw || raw === "default") return "";

    if (raw === metadataDisplayName() || raw === "System") return "system";
    if (raw === feedbackDisplayName() || raw === "Coach") return "feedback";
    if (raw === userDisplayName() || raw === "Doctor") return "user";
    if (raw === counterpartDisplayName() || raw === "Assistant") return "counterpart";
    return "counterpart";
  }

  function avatarSrcForRole(role) {
    const branding = app.activeModule && app.activeModule.branding;
    const configured = branding && branding.avatarAssets && branding.avatarAssets[role];
    if (typeof configured === "string" && configured.trim()) return configured.trim();
    if (role === "user") return "/public/avatars/doctor.svg?v=3";
    if (role === "counterpart") return "/public/avatars/assistant.svg?v=3";
    if (role === "feedback") return "/public/avatars/coach.svg?v=3";
    if (role === "system") return "/public/avatars/system.svg?v=3";
    return "";
  }

  function roleLabel(author, role) {
    if (role === "user") return userDisplayName();
    if (role === "counterpart") return counterpartDisplayName();
    if (role === "feedback") return feedbackDisplayName();
    if (role === "system") return metadataDisplayName();
    return author || "";
  }

  function decorateMessageSurface(step, content, author, role) {
    if (!step || !content || !author) return;
    const label = roleLabel(author, role);
    step.setAttribute("data-role-label", label);
    if (!step.hasAttribute("data-aims-animated")) {
      step.setAttribute("data-aims-animated", "true");
      step.classList.add("aims-message-enter");
    }
    content.setAttribute("data-role-label", label);
  }

  function tagAiMessage(message) {
    let author = message.getAttribute("data-author");
    if (!author) {
      const img = message.querySelector('img[alt^="Avatar for "]');
      if (img) author = img.alt.replace("Avatar for ", "").trim();
    }
    const role = normalizedRole(author);
    if (!role) return;

    const finalAuthor = roleLabel(author, role);
    message.setAttribute("data-author", finalAuthor);
    message.setAttribute("data-training-role", role);

    const avatar = message.querySelector('img[alt^="Avatar for "]');
    if (avatar) {
      const avatarSrc = avatarSrcForRole(role);
      if (avatarSrc) avatar.src = avatarSrc;
      const tooltip = "Avatar for " + finalAuthor;
      avatar.alt = tooltip;
      avatar.title = tooltip;
      avatar.setAttribute("aria-label", tooltip);
    }

    const step = message.closest("[data-step-type]");
    if (step) {
      step.setAttribute("data-author", finalAuthor);
      step.setAttribute("data-training-role", role);
      step.classList.add("aims-message-row");
      decorateMessageSurface(step, message.querySelector(".message-content"), finalAuthor, role);
      if (role === "feedback" || role === "system") {
        injectCopyButton(step);
      }
    }

    const content = message.querySelector(".message-content");
    if (content) {
      content.classList.add("aims-message-bubble");
      content.setAttribute("data-role-label", finalAuthor);
    }
  }

  function tagUserMessage(step) {
    const author = userDisplayName();
    step.setAttribute("data-author", author);
    step.setAttribute("data-training-role", "user");
    step.classList.add("aims-message-row");

    const content = step.querySelector(".message-content");
    if (!content) return;
    decorateMessageSurface(step, content, author, "user");

    const bubble = content.closest(".relative") || content;
    bubble.classList.add("aims-message-bubble");
    bubble.setAttribute("data-role-label", author);

    const row = bubble.parentElement;
    if (!row || row.querySelector(".aims-doctor-avatar")) {
      if (row && !row.querySelector(".aims-copy-button")) {
        injectCopyButton(step);
      }
      return;
    }

    const avatar = document.createElement("span");
    avatar.className = "aims-doctor-avatar";
    avatar.setAttribute("data-state", "closed");
    avatar.innerHTML = '<img alt="Avatar for ' + author + '" src="' + avatarSrcForRole("user") + '" />';
    row.appendChild(avatar);

    injectCopyButton(step);
  }

  function injectCopyButton(step) {
    const author = step.getAttribute("data-author");
    if (!author) return;

    const content = step.querySelector(".message-content");
    if (!content) return;

    if (step.querySelector(".aims-copy-button") || step.querySelector(".lucide-copy")) return;

    let container = content.parentElement;
    if (step.getAttribute("data-training-role") === "user") {
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
    copyBtn.setAttribute("title", "Copy to clipboard");
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-copy h-4 w-4" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>';

    copyBtn.addEventListener("click", function (event) {
      app.prevent(event);
      const text = content.innerText || "";
      if (!text) return;
      navigator.clipboard.writeText(text).then(function () {
        const originalHtml = copyBtn.innerHTML;
        copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-check h-4 w-4" aria-hidden="true"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        window.setTimeout(function () {
          copyBtn.innerHTML = originalHtml;
        }, 2000);
      });
    });

    actionRow.appendChild(copyBtn);
  }

  function decorateMessages() {
    document.querySelectorAll(".ai-message").forEach(tagAiMessage);
    document.querySelectorAll('[data-step-type="user_message"]').forEach(tagUserMessage);
  }

  if (typeof app.observeDomTask === "function") {
    app.observeDomTask("messagePresentation", decorateMessages, { debounceMs: 100 });
  } else if (document.body) {
    const observer = new MutationObserver(function () {
      decorateMessages();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  decorateMessages();

  app.messagePresentation = {
    decorateMessages: decorateMessages,
    userDisplayName: userDisplayName,
    counterpartDisplayName: counterpartDisplayName,
  };
})(window, document);
