(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.messageRolesReady) return;

  app.messageRolesReady = true;

  function normalizedRole(author) {
    if (author === "Doctor") return "Doctor";
    if (author === "Coach") return "Coach";
    if (author === "System") return "System";
    if (!author || author === "default") return "";
    return "Assistant";
  }

  function avatarSrcForRole(role) {
    if (role === "Doctor") return "/public/avatars/doctor.svg?v=3";
    if (role === "Assistant") return "/public/avatars/assistant.svg?v=3";
    if (role === "Coach") return "/public/avatars/coach.svg?v=3";
    if (role === "System") return "/public/avatars/system.svg?v=3";
    return "";
  }

  function extractPersonaName(text) {
    const source = String(text || "");
    const patterns = [
      /(?:^|\n)Person:\s*([^\n]+)/i,
      /(?:^|\n)Parent:\s*([^\n]+)/i,
      /(?:^|\n)Parent\/Patient:\s*([^\n]+)/i,
      /(?:^|\n)Patient:\s*([^\n]+)/i
    ];

    for (const pattern of patterns) {
      const match = source.match(pattern);
      if (match && match[1]) return match[1].trim();
    }
    return "";
  }

  function getPersonaName() {
    const cached = String((app.state && app.state.personaName) || "").trim();
    if (cached) return cached;

    const systemMessages = document.querySelectorAll('.ai-message[data-aims-role="System"] .message-content, .ai-message[data-author="System"] .message-content');
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
    if (author === "Doctor") return "Clinician";
    if (normalizedRole(author) === "Assistant") return getPersonaName() || (author !== "Assistant" ? author : "") || "Patient";
    if (author === "Coach") return "Coach";
    if (author === "System") return "Scenario";
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
        const img = message.querySelector('img[alt^="Avatar for "]');
        if (img) author = img.alt.replace("Avatar for ", "").trim();
    }
    const role = normalizedRole(author);
    if (!role) return;

    message.setAttribute("data-author", author);
    message.setAttribute("data-aims-role", role);
    if (role === "System") {
        const systemImg = message.querySelector('img[alt="Avatar for System"]');
        if (systemImg) systemImg.src = avatarSrcForRole("System");
    }
    if (role === "Coach") {
        const coachImg = message.querySelector('img[alt="Avatar for Coach"]');
        if (coachImg) coachImg.src = avatarSrcForRole("Coach");
    }
    if (role === "Assistant") {
        const personaName = getPersonaName() || (author !== "Assistant" ? author : "");
        const assistantImg = message.querySelector('img[alt^="Avatar for "]');
        if (assistantImg && personaName) {
          assistantImg.src = avatarSrcForRole("Assistant");
          const tooltip = "Avatar for " + personaName;
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
      if (role === "Coach" || role === "System") {
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
    step.setAttribute("data-author", "Doctor");
    step.classList.add("aims-message-row");

      const content = step.querySelector(".message-content");
      if (!content) return;
      decorateMessageSurface(step, content, "Doctor");

      const bubble = content.closest(".relative") || content;
      bubble.classList.add("aims-message-bubble");
      bubble.setAttribute("data-role-label", roleLabel("Doctor"));

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
    avatar.innerHTML = '<img alt="Avatar for Doctor" src="' + avatarSrcForRole("Doctor") + '" />';
    row.appendChild(avatar);

    injectCopyButton(step);
  }

  function injectCopyButton(step) {
      const author = step.getAttribute("data-author");
      if (!author) return;

      const content = step.querySelector(".message-content");
      if (!content) return;

    // Check if copy button already exists (either Chainlit's or ours)
    if (step.querySelector(".aims-copy-button") || (author === "Assistant" && step.querySelector(".lucide-copy"))) return;

      let container = content.parentElement;
      if (author === "Doctor") {
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
    copyBtn.setAttribute("title", "Copy to clipboard");
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

    let debounce = null;
    const observer = new MutationObserver(function () {
        if (debounce) return;
        debounce = window.setTimeout(function () {
            debounce = null;
            injectDataAuthors();
        }, 100);
    });

    observer.observe(document.body, { childList: true, subtree: true });
  injectDataAuthors();
  window.setTimeout(injectDataAuthors, 300);
  window.setTimeout(injectDataAuthors, 1000);
  window.setTimeout(injectDataAuthors, 3000);

  app.messageRoles = {
    injectDataAuthors: injectDataAuthors
  };
})(window, document);
