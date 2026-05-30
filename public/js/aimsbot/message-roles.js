(function (window, document) {
  "use strict";

  var app = window.AIMSBotUI;
  if (!app || app.messageRolesReady) return;

  app.messageRolesReady = true;

  function tagAiMessage(message) {
    var author = message.getAttribute("data-author");
    if (!author) {
      var img = message.querySelector('img[alt^="Avatar for "]');
      if (img) author = img.alt.replace("Avatar for ", "").trim();
    }
    if (!author || author === "default") return;

    message.setAttribute("data-author", author);
    if (author === "System") {
      var systemImg = message.querySelector('img[alt="Avatar for System"]');
      if (systemImg) systemImg.src = "/public/avatars/system.svg?v=2";
    }

    var step = message.closest("[data-step-type]");
    if (step) {
      step.setAttribute("data-author", author);
      step.classList.add("aims-message-row");
      if (author === "Coach" || author === "System") {
        injectCopyButton(step);
      }
    }

    var content = message.querySelector(".message-content");
    if (content) content.classList.add("aims-message-bubble");
  }

  function tagDoctorMessage(step) {
    step.setAttribute("data-author", "Doctor");
    step.classList.add("aims-message-row");

    var content = step.querySelector(".message-content");
    if (!content) return;

    var bubble = content.closest(".relative") || content;
    bubble.classList.add("aims-message-bubble");

    var row = bubble.parentElement;
    if (!row || row.querySelector(".aims-doctor-avatar")) return;

    var avatarBase = window.location.pathname.indexOf("/chat") === 0 ? "/chat" : "";
    var avatar = document.createElement("span");
    avatar.className = "aims-doctor-avatar";
    avatar.setAttribute("data-state", "closed");
    avatar.innerHTML = '<img alt="Avatar for Doctor" src="' + avatarBase + '/avatars/Doctor" />';
    row.appendChild(avatar);
  }

  function injectCopyButton(step) {
    var author = step.getAttribute("data-author");
    if (!author) return;

    var content = step.querySelector(".message-content");
    if (!content) return;

    // Check if copy button already exists (either Chainlit's or ours)
    if (step.querySelector(".aims-copy-button") || (author === "Assistant" && step.querySelector(".lucide-copy"))) return;

    var container = content.parentElement;
    if (!container) return;

    var actionRow = step.querySelector(".flex.items-center.flex-wrap");
    if (!actionRow) {
      actionRow = document.createElement("div");
      actionRow.className = "-ml-1.5 flex items-center flex-wrap aims-injected-actions";
      container.appendChild(actionRow);
    }

    var copyBtn = document.createElement("button");
    copyBtn.className = app.chainlitIconButtonClass + " aims-copy-button";
    copyBtn.setAttribute("data-state", "closed");
    copyBtn.setAttribute("title", "Copy to clipboard");
    copyBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-copy h-4 w-4" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>';
    
    copyBtn.addEventListener("click", function(e) {
      app.prevent(e);
      var text = content.innerText || "";
      if (text) {
        navigator.clipboard.writeText(text).then(function() {
          var originalHtml = copyBtn.innerHTML;
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

  var debounce = null;
  var observer = new MutationObserver(function () {
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
