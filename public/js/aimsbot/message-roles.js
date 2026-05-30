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
