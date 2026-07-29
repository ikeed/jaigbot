(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.sessionControlsReady) return;

  app.sessionControlsReady = true;

  app.modals.newSession = app.createModal({
    id: "new-session-modal",
    title: app.t("session.newTitle"),
    description: app.t("session.newDescription"),
    showTextarea: false,
    confirmText: app.t("session.confirm"),
    onConfirm: function () {
      app.postToChainlit({ type: "new_chat" });
      window.setTimeout(function () {
        window.location.href = window.location.origin + "/chat?aims_new=1";
      }, 100);
    }
  });

  app.modals.logout = app.createModal({
    id: "logout-modal",
    title: app.t("session.logoutTitle"),
    description: app.t("session.logoutDescription"),
    showTextarea: false,
    confirmText: app.t("session.logoutConfirm"),
    onConfirm: leaveChatForLogout
  });

  function leaveChatForLogout() {
    if (app.state.logoutInProgress) return;
    app.state.logoutInProgress = true;
    app.hideModal(app.modals.logout);

      const confirmBtn = app.modals.logout.querySelector(".modal-confirm-btn");
      if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.style.cursor = "default";
      confirmBtn.textContent = app.t("session.loggingOut");
    }

    window.location.assign("/chat/logout");
  }

  function showLogoutModal() {
    if (app.state.logoutInProgress) return;
    document.querySelectorAll("#logout-modal").forEach(function (modal, index) {
      modal.style.display = index === 0 ? "flex" : "none";
      modal.setAttribute("aria-hidden", index === 0 ? "false" : "true");
    });
    attachLogoutConfirmHandler();
  }

  function attachLogoutConfirmHandler() {
      const buttons = document.querySelectorAll("#logout-modal .modal-confirm-btn");
      buttons.forEach(function (button) {
      if (button._aimsLogoutConfirmAttached) return;
      button._aimsLogoutConfirmAttached = true;

      ["pointerdown", "click"].forEach(function (eventName) {
        button.addEventListener(eventName, function (event) {
          app.prevent(event);
          leaveChatForLogout();
        }, true);
      });
    });
  }

  function logoutConfirmTargetFromEvent(event) {
      const directTarget = event.target && event.target.closest
          ? event.target.closest("#logout-modal .modal-confirm-btn")
          : null;
      if (directTarget) return directTarget;

      let elementAtPoint = null;
      try {
      elementAtPoint = document.elementFromPoint(event.clientX, event.clientY);
    } catch (_) {}
    return elementAtPoint && elementAtPoint.closest
      ? elementAtPoint.closest("#logout-modal .modal-confirm-btn")
      : null;
  }

  function handleLogoutConfirmDocumentEvent(event) {
      const target = logoutConfirmTargetFromEvent(event);
      if (!target) return;
    app.prevent(event);
    leaveChatForLogout();
  }

  function interceptNewChat() {
      const button = document.getElementById("new-chat-button");
      if (!button || button._aimsIntercepted) return;

    button.addEventListener("click", function (event) {
      if (button._aimsConfirmBypass) {
        button._aimsConfirmBypass = false;
        return;
      }

      app.prevent(event);
      app.showModal(app.modals.newSession);
    }, true);

    button._aimsIntercepted = true;
  }

  function isLogoutControl(control) {
    if (!control) return false;
      const text = (control.textContent || "").toLowerCase();
      const href = control.href || "";
      const id = control.id || "";
      const role = control.getAttribute("role");

      if (href.indexOf("logout") !== -1 || id.indexOf("logout") !== -1) return true;
    const matchers = app.t("session.logoutMatchers") || [];
    return role === "menuitem" && matchers.some(function (matcher) {
      return text.indexOf(matcher) !== -1;
    });
  }

  function interceptLogout() {
      const selectors = [
          'a[href*="logout"]',
          'button[id*="logout"]',
          '[role="menuitem"]',
          ".cl-user-menu-logout"
      ];

      document.querySelectorAll(selectors.join(",")).forEach(function (button) {
      if (!isLogoutControl(button) || button._aimsIntercepted) return;

      button.addEventListener("click", function (event) {
        if (button._aimsLogoutBypass) {
          button._aimsLogoutBypass = false;
          return;
        }

        app.prevent(event);
        showLogoutModal();
      }, true);

      button._aimsIntercepted = true;
    });
  }

  ["pointerdown", "pointerup", "mouseup", "click"].forEach(function (eventName) {
    document.addEventListener(eventName, handleLogoutConfirmDocumentEvent, true);
  });

  document.addEventListener("click", function (event) {
      const target = event.target.closest("a, button, [role='menuitem']");
      if (!target || target._aimsIntercepted || !isLogoutControl(target)) return;

    if (target._aimsLogoutBypass) {
      target._aimsLogoutBypass = false;
      return;
    }

    app.prevent(event);
    showLogoutModal();
    target._aimsIntercepted = true;
  }, true);

  attachLogoutConfirmHandler();
  window.setInterval(function () {
    interceptNewChat();
    interceptLogout();
  }, 1000);

  app.sessionControls = {
    leaveChatForLogout: leaveChatForLogout,
    showLogoutModal: showLogoutModal,
    interceptNewChat: interceptNewChat,
    interceptLogout: interceptLogout
  };
})(window, document);
