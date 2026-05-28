/**
 * Report Issue – sidebar button & modal
 *
 * Loaded via Chainlit's custom_js config option so it runs as a native
 * <script> in the page and is never subject to message-content sanitisation.
 *
 * Communication: uses window.postMessage → @cl.on_window_message on the
 * Python side, which is the supported Chainlit 2.x browser→server channel.
 */
(function () {
  "use strict";

  /* ── guard against double-init ─────────────────────────────────── */
  if (window.__aimsbotCustomJsInitialized) return;
  window.__aimsbotCustomJsInitialized = true;
  document.querySelectorAll("#report-issue-modal, #new-session-modal, #logout-modal").forEach(function (modal) {
    modal.remove();
  });
  var debugCounter = 0;
  var logoutInProgress = false;

  function debugLog(event, details) {
    debugCounter += 1;
    try {
      console.debug("[AIMSBot logout]", debugCounter, event, details || {});
      console.debug("[AIMSBot logout json]", JSON.stringify({
        n: debugCounter,
        event: event,
        details: details || {},
      }));
    } catch (_) {}
  }

  function describeNode(node) {
    if (!node) return null;
    var modal = node.closest ? node.closest("#logout-modal") : null;
    var allLogoutModals = Array.from(document.querySelectorAll("#logout-modal"));
    return {
      tag: node.tagName,
      id: node.id || "",
      className: typeof node.className === "string" ? node.className : "",
      text: (node.textContent || "").trim().slice(0, 80),
      disabled: !!node.disabled,
      modalIndex: modal ? allLogoutModals.indexOf(modal) : -1,
      modalDisplay: modal ? modal.style.display : null,
      logoutModalCount: allLogoutModals.length,
      visibleLogoutModalCount: allLogoutModals.filter(function (m) {
        return getComputedStyle(m).display !== "none";
      }).length,
    };
  }

  function isLogoutModalVisible() {
    return Array.from(document.querySelectorAll("#logout-modal")).some(function (modal) {
      return getComputedStyle(modal).display !== "none";
    });
  }

  function describePoint(e) {
    var elementAtPoint = null;
    try {
      elementAtPoint = document.elementFromPoint(e.clientX, e.clientY);
    } catch (_) {}
    return {
      type: e.type,
      clientX: e.clientX,
      clientY: e.clientY,
      button: e.button,
      buttons: e.buttons,
      target: describeNode(e.target),
      matchedConfirm: describeNode(e.target.closest ? e.target.closest("#logout-modal .modal-confirm-btn") : null),
      matchedLogoutModal: describeNode(e.target.closest ? e.target.closest("#logout-modal") : null),
      elementFromPoint: describeNode(elementAtPoint),
      elementFromPointConfirm: describeNode(elementAtPoint && elementAtPoint.closest ? elementAtPoint.closest("#logout-modal .modal-confirm-btn") : null),
      elementFromPointModal: describeNode(elementAtPoint && elementAtPoint.closest ? elementAtPoint.closest("#logout-modal") : null),
      path: typeof e.composedPath === "function" ? e.composedPath().slice(0, 8).map(describeNode) : [],
    };
  }

  ["pointerdown", "pointerup", "mousedown", "mouseup", "click"].forEach(function (eventName) {
    document.addEventListener(eventName, function(e) {
      if (!isLogoutModalVisible()) return;
      debugLog("logout-modal-event-" + eventName, describePoint(e));
    }, true);
  });
  if (window.location.search.indexOf("aims_new=1") !== -1) {
    window.history.replaceState(null, "", window.location.origin + "/chat");
  }

  /* ── data-author injection ──────────────────────────────────────── */
  /* Chainlit 2.x (shadcn) does NOT emit data-author attributes.       */
  /* We inject data-author on the message row wrapper so CSS can       */
  /* target [data-author="X"] descendants for role-based styling.      */

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
      if (systemImg) {
        systemImg.src = "/public/avatars/system.svg?v=2";
      }
    }

    var step = message.closest('[data-step-type]');
    if (step) {
      step.setAttribute("data-author", author);
      step.classList.add("aims-message-row");
    }

    var content = message.querySelector(".message-content");
    if (content) {
      content.classList.add("aims-message-bubble");
    }
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
    // Assistant, Coach, and System rows are rendered as .ai-message.
    document.querySelectorAll(".ai-message").forEach(tagAiMessage);

    // User rows do not include an avatar or data-author in Chainlit 2.11.
    document.querySelectorAll('[data-step-type="user_message"]').forEach(tagDoctorMessage);
  }

  var _aimsDebounce = null;
  var authorObserver = new MutationObserver(function () {
    if (_aimsDebounce) return;
    _aimsDebounce = setTimeout(function () {
      _aimsDebounce = null;
      injectDataAuthors();
    }, 100);
  });
  authorObserver.observe(document.body, { childList: true, subtree: true });
  setTimeout(injectDataAuthors, 300);
  setTimeout(injectDataAuthors, 1000);
  setTimeout(injectDataAuthors, 3000);

  /* ── splash screen tweaks: enlarge icon & hide composer ──────── */

  function tweakSplash() {
    // Enlarge the chat profile icon (find by src containing "aimsbot")
    document.querySelectorAll("img").forEach(function (img) {
      var src = (img.src || "").toLowerCase();
      if (src.indexOf("aimsbot") !== -1) {
        img.style.width = "256px";
        img.style.height = "256px";
        img.style.maxWidth = "none";
        img.style.maxHeight = "none";
      }
    });

    // Hide the Chainlit composer until a message appears.
    // Target the specific "Type your message" textarea, NOT our report modal textarea.
    if (!document._aimsComposerHidden) {
      var textareas = document.querySelectorAll('textarea[placeholder]');
      textareas.forEach(function (ta) {
        // Skip our own report-issue textarea
        if (ta.id === "report-issue-modal-input") return;
        // Skip if already inside the report modal
        if (ta.closest("#report-issue-modal")) return;

        // Find the composer form wrapper
        var form = ta.closest("form");
        if (form && !form._aimsHidden) {
          form._aimsHidden = true;
          form.style.display = "none";
          document._aimsComposerHidden = form;

          // Reveal once the first chat message appears
          var obs = new MutationObserver(function () {
            var hasMsg = document.querySelector('[data-step-type], [data-author]');
            if (hasMsg) {
              form.style.display = "";
              obs.disconnect();
            }
          });
          obs.observe(document.body, { childList: true, subtree: true });
        }
      });
    }

  }

  // Run immediately and retry (Chainlit renders asynchronously)
  tweakSplash();
  setTimeout(tweakSplash, 300);
  setTimeout(tweakSplash, 800);
  setTimeout(tweakSplash, 1500);

  /* ── button ────────────────────────────────────────────────────── */
  function injectButton() {
    var header = document.getElementById("header");
    if (!header) return;
    if (document.getElementById("sidebar-report-button")) return;

    // The right-side container is the last child div with flex layout.
    // Chainlit 2.11 uses: className="flex items-center gap-1"
    var rightContainer = header.querySelector('div.flex.items-center.gap-1')
      || header.lastElementChild;
    if (!rightContainer) return;

    var btn = document.createElement("button");
    btn.id = "sidebar-report-button";
    btn.type = "button";
    btn.className = "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 hover:bg-accent h-9 w-9 text-muted-foreground hover:text-muted-foreground";
    btn.innerHTML = '<span style="font-size:18px">🪲</span>';
    btn.title = "Report Issue";

    // Insert at the beginning of the right container (before light mode button)
    rightContainer.insertBefore(btn, rightContainer.firstChild);

    btn.addEventListener("click", function () {
      reportModal.style.display = "flex";
      // Focus the textarea when modal opens
      setTimeout(function() {
        var input = document.getElementById("report-issue-modal-input");
        if (input) input.focus();
      }, 100);
    });
  }

  // Poll for header availability
  var buttonInterval = setInterval(function() {
    if (document.getElementById("header")) {
      injectButton();
      // We don't clear interval immediately because Chainlit might re-render
      // but injectButton has a guard against double-init.
    }
  }, 1000);

  /* ── modal ─────────────────────────────────────────────────────── */
  function createModal(id, title, description, placeholder, showTextarea, confirmText, onConfirm) {
    var existing = document.getElementById(id);
    if (existing) {
      debugLog("remove-existing-modal", { id: id });
      existing.remove();
    }

    var modal = document.createElement("div");
    modal.id = id;
    modal.dataset.aimsModalInstance = String(Date.now()) + "-" + Math.random().toString(16).slice(2);
    Object.assign(modal.style, {
      display: "none",
      position: "fixed",
      top: "0",
      left: "0",
      width: "100%",
      height: "100%",
      background: "rgba(0,0,0,0.5)",
      zIndex: "2147483647",
      justifyContent: "center",
      alignItems: "center",
      fontFamily: "sans-serif",
    });

    var textareaHtml = showTextarea ? 
      '<textarea id="' + id + '-input" placeholder="' + placeholder + '" style="width:100%;height:100px;margin:12px 0;padding:8px;border:1px solid #999;border-radius:4px;resize:none;font-size:14px;color:#1a1a1a;background:#fff"></textarea>' : '';

    modal.innerHTML =
      '<div style="background:#ffffff;padding:24px;border-radius:8px;width:400px;box-shadow:0 4px 12px rgba(0,0,0,0.15)">' +
      '  <h3 style="margin-top:0;color:#1a1a1a;font-size:18px">' + title + '</h3>' +
      '  <p style="color:#444;font-size:14px;line-height:1.5">' + description + '</p>' +
      textareaHtml +
      '  <div style="display:flex;justify-content:flex-end;gap:8px">' +
      '    <button class="modal-cancel-btn" style="padding:8px 16px;border:1px solid #888;background:#fff;color:#1a1a1a;border-radius:4px;cursor:pointer;font-size:14px">Cancel</button>' +
      '    <button class="modal-confirm-btn" style="padding:8px 16px;border:none;background:#1a73e8;color:#fff;border-radius:4px;cursor:pointer;font-size:14px;font-weight:600">' + confirmText + '</button>' +
      "  </div>" +
      "</div>";

    document.body.appendChild(modal);
    debugLog("create-modal", {
      id: id,
      instance: modal.dataset.aimsModalInstance,
      count: document.querySelectorAll("#" + id).length,
    });

    modal.querySelector(".modal-cancel-btn").addEventListener("click", function (e) {
      debugLog("modal-cancel-click", describeNode(e.target));
      e.preventDefault();
      e.stopPropagation();
      modal.style.display = "none";
    });

    modal.addEventListener("click", function (e) {
      debugLog("modal-background-click", {
        modalId: id,
        instance: modal.dataset.aimsModalInstance,
        targetIsModal: e.target === modal,
        target: describeNode(e.target),
      });
      if (e.target === modal) modal.style.display = "none";
    });

    modal.querySelector(".modal-confirm-btn").addEventListener("click", function (e) {
      debugLog("modal-confirm-click", {
        modalId: id,
        instance: modal.dataset.aimsModalInstance,
        target: describeNode(e.target),
        currentTarget: describeNode(e.currentTarget),
      });
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      var textarea = modal.querySelector("textarea");
      var value = textarea ? textarea.value.trim() : "";
      if (showTextarea && !value) {
        alert("Please provide a reason.");
        return;
      }
      onConfirm(value);
      modal.style.display = "none";
      if (textarea) textarea.value = "";
    });

    return modal;
  }

  function leaveChatForLogout() {
    debugLog("leave-chat-for-logout", {
      alreadyInProgress: logoutInProgress,
      activeElement: describeNode(document.activeElement),
      modals: Array.from(document.querySelectorAll("#logout-modal")).map(function (modal, index) {
        return {
          index: index,
          instance: modal.dataset.aimsModalInstance,
          display: modal.style.display,
          computedDisplay: getComputedStyle(modal).display,
          confirm: describeNode(modal.querySelector(".modal-confirm-btn")),
        };
      }),
    });
    if (logoutInProgress) return;
    logoutInProgress = true;
    logoutModal.style.display = "none";

    var confirmBtn = logoutModal.querySelector(".modal-confirm-btn");
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.style.cursor = "default";
      confirmBtn.textContent = "Logging out";
    }

    debugLog("logout-navigate", { href: "/chat/logout" });
    window.location.assign("/chat/logout");
  }

  var reportModal = createModal(
    "report-issue-modal",
    "Report Issue",
    "Describe the issue you encountered. This will end the session and log a report.",
    "What went wrong?",
    true,
    "Submit Report",
    function(reason) {
      var payload = JSON.stringify({ type: "report_issue", reason: reason });
      window.postMessage(payload, "*");
    }
  );

  var newSessionModal = createModal(
    "new-session-modal",
    "New Scenario",
    "This will clear your current chat history and start a fresh session. Are you sure you want to continue?",
    "",
    false,
    "Confirm",
    function() {
      // 1. Notify the backend to clear the session state for this user_session
      var payload = JSON.stringify({ type: "new_chat" });
      window.postMessage(payload, "*");

      // 2. Force a full reload to /chat which will trigger cl.on_chat_start
      // with the cleared session state.
      setTimeout(function() {
        window.location.href = window.location.origin + "/chat?aims_new=1";
      }, 100);
    }
  );

  var logoutModal = createModal(
    "logout-modal",
    "Logout",
    "Are you sure you want to logout? This will end your current session.",
    "",
    false,
    "Logout",
    leaveChatForLogout
  );

  function attachLogoutConfirmHandler() {
    var buttons = document.querySelectorAll("#logout-modal .modal-confirm-btn");
    buttons.forEach(function (btn) {
      if (btn._aimsLogoutConfirmAttached) return;
      btn._aimsLogoutConfirmAttached = true;
      btn.addEventListener("pointerdown", function(e) {
        debugLog("logout-confirm-pointerdown-attached", {
          target: describeNode(e.target),
          currentTarget: describeNode(e.currentTarget),
        });
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        leaveChatForLogout();
      }, true);
      btn.addEventListener("click", function(e) {
        debugLog("logout-confirm-click-attached", {
          target: describeNode(e.target),
          currentTarget: describeNode(e.currentTarget),
        });
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        leaveChatForLogout();
      }, true);
    });
  }
  attachLogoutConfirmHandler();

  function logoutConfirmTargetFromEvent(e) {
    var directTarget = e.target && e.target.closest ? e.target.closest("#logout-modal .modal-confirm-btn") : null;
    if (directTarget) return directTarget;

    var elementAtPoint = null;
    try {
      elementAtPoint = document.elementFromPoint(e.clientX, e.clientY);
    } catch (_) {}
    return elementAtPoint && elementAtPoint.closest ? elementAtPoint.closest("#logout-modal .modal-confirm-btn") : null;
  }

  function handleLogoutConfirmDocumentEvent(eventName, e) {
    var target = logoutConfirmTargetFromEvent(e);
    if (!target) return;
    var elementAtPoint = null;
    try {
      elementAtPoint = document.elementFromPoint(e.clientX, e.clientY);
    } catch (_) {}
    debugLog("logout-confirm-" + eventName + "-document", {
      target: describeNode(e.target),
      matchedTarget: describeNode(target),
      point: describeNode(elementAtPoint),
    });
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    leaveChatForLogout();
  }

  ["pointerdown", "pointerup", "mouseup", "click"].forEach(function(eventName) {
    document.addEventListener(eventName, function(e) {
      handleLogoutConfirmDocumentEvent(eventName, e);
    }, true);
  });

  function showLogoutModal() {
    debugLog("show-logout-modal", {
      alreadyInProgress: logoutInProgress,
      modalCountBefore: document.querySelectorAll("#logout-modal").length,
      triggerActiveElement: describeNode(document.activeElement),
    });
    if (logoutInProgress) return;
    document.querySelectorAll("#logout-modal").forEach(function (modal, index) {
      modal.style.display = index === 0 ? "flex" : "none";
    });
    attachLogoutConfirmHandler();
    debugLog("show-logout-modal-after", {
      modals: Array.from(document.querySelectorAll("#logout-modal")).map(function (modal, index) {
        return {
          index: index,
          instance: modal.dataset.aimsModalInstance,
          display: modal.style.display,
          computedDisplay: getComputedStyle(modal).display,
          confirm: describeNode(modal.querySelector(".modal-confirm-btn")),
        };
      }),
    });
  }

  /* ── intercept new chat ────────────────────────────────────────── */
  function interceptNewChat() {
    var btn = document.getElementById("new-chat-button");
    if (!btn || btn._aimsIntercepted) return;

    // Use capturing phase to intercept before Chainlit's own listeners
    btn.addEventListener("click", function (e) {
      if (btn._aimsConfirmBypass) {
        btn._aimsConfirmBypass = false;
        return; // Allow the click to proceed
      }

      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      
      newSessionModal.style.display = "flex";
    }, true);

    btn._aimsIntercepted = true;
  }

  /* ── intercept logout ──────────────────────────────────────────── */
  function interceptLogout() {
    // Chainlit logout button is often a Radix UI menu item or a link/button with logout in the text/id/href
    var logoutSelectors = [
      'a[href*="logout"]',
      'button[id*="logout"]',
      '[role="menuitem"]',
      '.cl-user-menu-logout' // Potential future-proof class
    ];
    
    var logoutBtns = document.querySelectorAll(logoutSelectors.join(','));
    logoutBtns.forEach(function(btn) {
      // Check if it's actually a logout button by text if it's a generic menuitem
      if (btn.getAttribute('role') === 'menuitem') {
        var text = (btn.textContent || "").toLowerCase();
        if (text.indexOf("logout") === -1 && text.indexOf("sign out") === -1) {
          return;
        }
      }

      if (btn._aimsIntercepted) return;

      btn.addEventListener("click", function (e) {
        debugLog("logout-trigger-click-attached", {
          target: describeNode(e.target),
          currentTarget: describeNode(e.currentTarget),
        });
        if (btn._aimsLogoutBypass) {
          btn._aimsLogoutBypass = false;
          return;
        }

        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();

        showLogoutModal();
      }, true);

      btn._aimsIntercepted = true;
    });
  }

  // Global click listener as a backup for dynamically generated or complex logout buttons
  document.addEventListener("click", function(e) {
    var target = e.target.closest('a, button, [role="menuitem"]');
    if (!target) return;
    
    // If we already intercepted it, don't do anything here
    if (target._aimsIntercepted) return;
    
    var text = (target.textContent || "").toLowerCase();
    var href = target.href || "";
    var id = target.id || "";
    
    if (href.indexOf("logout") !== -1 || id.indexOf("logout") !== -1 || 
        (target.getAttribute('role') === 'menuitem' && (text.indexOf("logout") !== -1 || text.indexOf("sign out") !== -1))) {
      debugLog("logout-trigger-click-document", {
        target: describeNode(e.target),
        matchedTarget: describeNode(target),
        href: href,
        id: id,
        role: target.getAttribute("role"),
      });
      
      if (target._aimsLogoutBypass) {
        target._aimsLogoutBypass = false;
        return;
      }
      
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      
      showLogoutModal();
      
      // Mark as intercepted to avoid double modals if the interval also finds it
      target._aimsIntercepted = true;
    }
  }, true);

  // Handle signals from the backend (via cl.send_window_message)
  window.addEventListener("message", function(event) {
    if (event.data === "on_duplicate_tab" || (event.data && event.data.type === "on_duplicate_tab")) {
      window.location.href = "/duplicate";
    } else if (event.data === "on_logout" || (event.data && event.data.type === "on_logout")) {
      window.location.href = "/";
    }
  });

  setInterval(function() {
    interceptNewChat();
    interceptLogout();
  }, 1000);

  /* ── dark mode support ─────────────────────────────────────────── */
  function applyTheme() {
    var isDark = document.documentElement.classList.contains("dark");
    [reportModal, newSessionModal, logoutModal].forEach(function(m) {
      if (!m) return;
      var content = m.querySelector("div");
      if (content) {
        content.style.background = isDark ? "#1e1e1e" : "#ffffff";
        content.style.color = isDark ? "#e0e0e0" : "#1a1a1a";
      }
      var title = m.querySelector("h3");
      if (title) title.style.color = isDark ? "#ffffff" : "#1a1a1a";
      var text = m.querySelector("p");
      if (text) text.style.color = isDark ? "#cccccc" : "#444444";
      var textarea = m.querySelector("textarea");
      if (textarea) {
        textarea.style.background = isDark ? "#2d2d2d" : "#ffffff";
        textarea.style.color = isDark ? "#ffffff" : "#1a1a1a";
        textarea.style.border = isDark ? "1px solid #444" : "1px solid #999";
      }
      var cancelBtn = m.querySelector(".modal-cancel-btn");
      if (cancelBtn) {
        cancelBtn.style.background = isDark ? "#2d2d2d" : "#ffffff";
        cancelBtn.style.color = isDark ? "#ffffff" : "#1a1a1a";
        cancelBtn.style.border = isDark ? "1px solid #555" : "1px solid #888";
      }
    });
  }

  // Watch for theme changes
  var themeObserver = new MutationObserver(applyTheme);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  applyTheme();

  /* ── append to DOM ─────────────────────────────────────────────── */
  // document.body.appendChild(modal); // Handled in createModal
})();
