(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI = window.AIMSBotUI || {};
    if (app.coreReady) return;

  app.coreReady = true;
  app.state = app.state || {};
  app.state.logoutInProgress = false;
  app.state.pendingIntroStorageKey = "aimsbot.pendingIntro";

  app.managedModalSelector = [
    "#report-issue-modal",
    "#new-session-modal",
    "#logout-modal",
    "#aims-infographic-modal"
  ].join(", ");
  app.nativeDialogSelector = '[role="alertdialog"], [role="dialog"]';

  app.chainlitIconButtonClass = [
    "inline-flex",
    "items-center",
    "justify-center",
    "gap-2",
    "whitespace-nowrap",
    "rounded-md",
    "text-sm",
    "font-medium",
    "ring-offset-background",
    "transition-colors",
    "focus-visible:outline-none",
    "focus-visible:ring-2",
    "focus-visible:ring-ring",
    "focus-visible:ring-offset-2",
    "disabled:pointer-events-none",
    "disabled:opacity-50",
    "[&_svg]:pointer-events-none",
    "[&_svg]:size-4",
    "[&_svg]:shrink-0",
    "hover:bg-accent",
    "h-9",
    "w-9",
    "text-muted-foreground",
    "hover:text-muted-foreground"
  ].join(" ");

  app.removeManagedModals = function () {
    document.querySelectorAll(app.managedModalSelector).forEach(function (modal) {
      modal.remove();
    });
  };

  app.prevent = function (event) {
    if (!event) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.stopImmediatePropagation) event.stopImmediatePropagation();
  };

  app.postToChainlit = function (payload) {
    window.postMessage(JSON.stringify(payload), "*");
  };

  app.isLoginCallbackRoute = function () {
    return window.location.pathname.indexOf("/login/callback") !== -1;
  };

  app.isChatShellReady = function () {
    return !!document.getElementById("header");
  };

  app.messageType = function (data) {
    if (typeof data === "string") {
      try {
        return (JSON.parse(data) || {}).type || data;
      } catch (_) {
        return data;
      }
    }
    return data && data.type;
  };

  app.findHeaderActions = function () {
      const header = document.getElementById("header");
      if (!header) return null;
    return header.querySelector("div.flex.items-center.gap-1") || header.lastElementChild;
  };

  app.decorateShell = function () {
    document.documentElement.classList.add("aimsbot-shell-root");
    document.body.classList.add("aimsbot-shell");

    const header = document.getElementById("header");
    if (header) header.classList.add("aimsbot-app-header");

    document.querySelectorAll("textarea[placeholder]").forEach(function (textarea) {
      if (textarea.id === "report-issue-modal-input") return;
      if (textarea.closest("#report-issue-modal")) return;

      const composer = textarea.closest("form") || textarea.closest("#message-composer");
      if (!composer) return;
      composer.classList.add("aimsbot-composer");
      textarea.classList.add("aimsbot-composer-input");
    });

    document.querySelectorAll("aside").forEach(function (aside) {
      aside.classList.add("aimsbot-sidebar");
    });
  };

  app.decorateNativeDialogs = function () {
    document.querySelectorAll(app.nativeDialogSelector).forEach(function (dialog) {
      if (dialog.closest && dialog.closest(app.managedModalSelector)) return;
      if (dialog.dataset.aimsStyled === "true") return;
      dialog.dataset.aimsStyled = "true";

      dialog.classList.add("aims-native-dialog");
      dialog.style.width = "min(92vw, 420px)";
      dialog.style.border = "1px solid rgba(126, 155, 193, 0.22)";
      dialog.style.borderRadius = "8px";
      dialog.style.background = "rgba(255, 255, 255, 0.96)";
      dialog.style.color = "#132238";
      dialog.style.boxShadow = "0 28px 80px rgba(15, 23, 42, 0.22)";
      dialog.style.backdropFilter = "blur(22px)";

      const actionRow = dialog.lastElementChild;
      if (actionRow) {
        actionRow.classList.add("aims-native-dialog-actions");
        actionRow.style.marginTop = "0.15rem";
      }

      const heading = dialog.querySelector("h2, h3");
      if (heading) {
        heading.classList.add("aims-native-dialog-title");
        heading.style.color = "#132238";
      }

      const description = dialog.querySelector("p");
      if (description) {
        description.classList.add("aims-native-dialog-description");
        description.style.padding = "3px 0 5px";
        description.style.lineHeight = "1.55";
        description.style.color = "#43556f";
      }

      dialog.querySelectorAll("label").forEach(function (label) {
        label.classList.add("aims-native-dialog-label");
      });

      dialog.querySelectorAll("input, textarea, select").forEach(function (field) {
        field.classList.add("aims-native-dialog-input");
      });

      const buttons = Array.prototype.slice.call(dialog.querySelectorAll("button"));
      const isCloseButton = function (button) {
        const ariaLabel = String(button.getAttribute("aria-label") || "");
        const text = String(button.textContent || "").trim();
        return !text || /close/i.test(ariaLabel) || /^[x×]$/i.test(text);
      };
      const actionButtons = buttons.filter(function (button) {
        return !isCloseButton(button) && !!String(button.textContent || "").trim();
      });

      buttons.forEach(function (button) {
        if (isCloseButton(button)) button.classList.add("aims-native-dialog-close");
        button.style.borderRadius = "4px";
        button.style.boxShadow = "none";
      });

      if (actionButtons.length === 1) {
        actionButtons[0].classList.add("aims-native-dialog-confirm");
      }

      if (actionButtons.length > 1) {
        const cancelButton = actionButtons[0];
        const confirmButton = actionButtons[actionButtons.length - 1];

        cancelButton.classList.add("aims-native-dialog-cancel");
        cancelButton.style.border = "1px solid rgba(128, 153, 195, 0.24)";
        cancelButton.style.background = "rgba(255, 255, 255, 0.86)";
        cancelButton.style.color = "#26405f";

        confirmButton.classList.add("aims-native-dialog-confirm");
        confirmButton.style.border = "none";
        confirmButton.style.background = "linear-gradient(135deg, #2563eb 0%, #0ea5e9 100%)";
        confirmButton.style.backgroundColor = "#2563eb";
        confirmButton.style.color = "#ffffff";
      }
    });
  };

  app.observeNativeDialogs = function () {
    if (app._aimsNativeDialogObserver) return;
    if (!document.body && !document.documentElement) return;

    app._aimsNativeDialogObserver = new MutationObserver(function () {
      app.decorateNativeDialogs();
    });

    app._aimsNativeDialogObserver.observe(document.body || document.documentElement, {
      childList: true,
      subtree: true
    });
  };

  if (window.location.search.indexOf("aims_new=1") !== -1) {
    window.history.replaceState(null, "", window.location.origin + "/chat");
  }

  app.removeManagedModals();
  app.decorateShell();
  app.decorateNativeDialogs();
  app.observeNativeDialogs();
  window.setTimeout(app.decorateShell, 300);
  window.setTimeout(app.decorateShell, 1000);
  window.setTimeout(app.decorateShell, 2500);
})(window, document);
