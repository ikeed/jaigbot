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
  document.querySelectorAll("#report-issue-modal, #new-session-modal, #logout-modal, #aims-infographic-modal").forEach(function (modal) {
    modal.remove();
  });
  var logoutInProgress = false;
  var pendingIntroStorageKey = "aimsbot.pendingIntro";
  if (window.location.search.indexOf("aims_new=1") !== -1) {
    window.history.replaceState(null, "", window.location.origin + "/chat");
  }

  function isLoginCallbackRoute() {
    return window.location.pathname.indexOf("/login/callback") !== -1;
  }

  function isChatShellReady() {
    return !!document.getElementById("header");
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

  /* ── header buttons ────────────────────────────────────────────── */
  function injectButton() {
    var header = document.getElementById("header");
    if (!header) return;

    // The right-side container is the last child div with flex layout.
    // Chainlit 2.11 uses: className="flex items-center gap-1"
    var rightContainer = header.querySelector('div.flex.items-center.gap-1')
      || header.lastElementChild;
    if (!rightContainer) return;

    if (!document.getElementById("aims-info-button")) {
      var infoBtn = document.createElement("button");
      infoBtn.id = "aims-info-button";
      infoBtn.type = "button";
      infoBtn.className = "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 hover:bg-accent h-9 w-9 text-muted-foreground hover:text-muted-foreground";
      infoBtn.innerHTML = '<span aria-hidden="true" style="font-size:18px">?</span>';
      infoBtn.title = "AIMS infographic";
      rightContainer.insertBefore(infoBtn, rightContainer.firstChild);
      infoBtn.addEventListener("click", function () {
        showInfographicModal(false);
      });
    }

    if (document.getElementById("sidebar-report-button")) return;

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
      existing.remove();
    }

    var modal = document.createElement("div");
    modal.id = id;
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

    modal.querySelector(".modal-cancel-btn").addEventListener("click", function (e) {
      e.preventDefault();
      e.stopPropagation();
      modal.style.display = "none";
    });

    modal.addEventListener("click", function (e) {
      if (e.target === modal) modal.style.display = "none";
    });

    modal.querySelector(".modal-confirm-btn").addEventListener("click", function (e) {
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

  function createInfographicModal() {
    var existing = document.getElementById("aims-infographic-modal");
    if (existing) existing.remove();

    var modal = document.createElement("div");
    modal.id = "aims-infographic-modal";
    modal.className = "aims-infographic-modal";
    modal.setAttribute("aria-hidden", "true");
    Object.assign(modal.style, {
      display: "none",
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
      background: "rgba(15, 23, 42, 0.62)"
    });
    modal.innerHTML =
      '<div class="aims-infographic-panel" role="dialog" aria-modal="true" aria-labelledby="aims-infographic-title">' +
      '  <div class="aims-infographic-header">' +
      '    <div class="aims-infographic-copy">' +
      '      <h2 id="aims-infographic-title">Review the AIMS approach</h2>' +
      '      <p>This bot is going to help you to practice the AIMS communication protocol for helping address vaccine hesitancy. Before you start, please review this infographic so you are best equipped to have a conversation with our vaccine hesitant patients.</p>' +
      '    </div>' +
      '    <div class="aims-infographic-actions">' +
      '      <button type="button" class="aims-infographic-close" aria-label="Close">×</button>' +
      '      <button type="button" class="aims-infographic-continue">Start practicing</button>' +
      '    </div>' +
      '  </div>' +
      '  <div class="aims-infographic-scroll">' +
      '    <img src="/public/aims_infographic.svg" alt="Addressing Vaccine Hesitancy with the AIMS Communication Approach infographic" />' +
      '  </div>' +
      '</div>';

    document.body.appendChild(modal);

    var closeBtn = modal.querySelector(".aims-infographic-close");
    var continueBtn = modal.querySelector(".aims-infographic-continue");

    closeBtn.addEventListener("click", function () {
      hideInfographicModal();
    });
    continueBtn.addEventListener("click", function () {
      window.postMessage(JSON.stringify({ type: "aims_intro_continue" }), "*");
      hideInfographicModal();
    });
    modal.addEventListener("click", function (e) {
      if (e.target === modal && modal.getAttribute("data-mode") === "reference") {
        hideInfographicModal();
      }
    });

    return modal;
  }

  var infographicModal = createInfographicModal();

  function styleInfographicModal(isIntro) {
    var panel = infographicModal.querySelector(".aims-infographic-panel");
    var header = infographicModal.querySelector(".aims-infographic-header");
    var copy = infographicModal.querySelector(".aims-infographic-copy");
    var title = infographicModal.querySelector(".aims-infographic-copy h2");
    var text = infographicModal.querySelector(".aims-infographic-copy p");
    var actions = infographicModal.querySelector(".aims-infographic-actions");
    var closeBtn = infographicModal.querySelector(".aims-infographic-close");
    var continueBtn = infographicModal.querySelector(".aims-infographic-continue");
    var scroll = infographicModal.querySelector(".aims-infographic-scroll");
    var img = infographicModal.querySelector(".aims-infographic-scroll img");

    Object.assign(infographicModal.style, {
      display: "flex",
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
      background: "rgba(15, 23, 42, 0.62)"
    });
    if (panel) {
      Object.assign(panel.style, {
        width: "min(1180px, 96vw)",
        maxHeight: "92vh",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
        borderRadius: "8px",
        border: "1px solid #d7dee8",
        background: "#ffffff",
        color: "#172033",
        boxShadow: "0 20px 60px rgba(15, 23, 42, 0.28)"
      });
    }
    if (header) {
      Object.assign(header.style, {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: isIntro ? "space-between" : "flex-end",
        gap: "18px",
        padding: isIntro ? "18px 20px" : "12px 14px",
        borderBottom: "1px solid #e4e9f1",
        background: "#ffffff",
        flexShrink: "0"
      });
    }
    if (copy) {
      Object.assign(copy.style, {
        display: isIntro ? "block" : "none",
        maxWidth: "760px"
      });
    }
    if (title) {
      Object.assign(title.style, {
        margin: "0 0 8px",
        fontSize: "20px",
        lineHeight: "1.25",
        fontWeight: "700",
        letterSpacing: "0",
        color: "#101828"
      });
    }
    if (text) {
      Object.assign(text.style, {
        margin: "0",
        fontSize: "14px",
        lineHeight: "1.45",
        color: "#344054"
      });
    }
    if (actions) {
      Object.assign(actions.style, {
        display: "flex",
        alignItems: "center",
        gap: "10px",
        flexShrink: "0"
      });
    }
    if (continueBtn) {
      Object.assign(continueBtn.style, {
        display: isIntro ? "inline-flex" : "none",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "36px",
        padding: "0 14px",
        borderRadius: "6px",
        border: "1px solid #0f6b8f",
        background: "#0f6b8f",
        color: "#ffffff",
        fontSize: "14px",
        fontWeight: "600",
        cursor: "pointer",
        whiteSpace: "nowrap"
      });
    }
    if (closeBtn) {
      Object.assign(closeBtn.style, {
        display: isIntro ? "none" : "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "36px",
        minHeight: "36px",
        borderRadius: "6px",
        border: "1px solid #cbd5e1",
        background: "#ffffff",
        color: "#344054",
        fontSize: "20px",
        fontWeight: "600",
        cursor: "pointer"
      });
    }
    if (scroll) {
      Object.assign(scroll.style, {
        overflow: "auto",
        padding: "18px",
        background: "#f8fafc",
        minHeight: "0"
      });
    }
    if (img) {
      Object.assign(img.style, {
        display: "block",
        width: "100%",
        maxWidth: "1080px",
        height: "auto",
        margin: "0 auto",
        border: "1px solid #e5e7eb",
        background: "#ffffff"
      });
    }
  }

  function showInfographicModal(isIntro) {
    if (isIntro && (isLoginCallbackRoute() || !isChatShellReady())) {
      try {
        sessionStorage.setItem(pendingIntroStorageKey, "1");
      } catch (_) {}
      return;
    }

    infographicModal.setAttribute("data-mode", isIntro ? "intro" : "reference");
    infographicModal.setAttribute("aria-hidden", "false");
    styleInfographicModal(isIntro);
  }

  function hideInfographicModal() {
    try {
      sessionStorage.removeItem(pendingIntroStorageKey);
    } catch (_) {}
    infographicModal.setAttribute("aria-hidden", "true");
    infographicModal.style.display = "none";
  }

  function showPendingIntroWhenReady() {
    var pending = false;
    try {
      pending = sessionStorage.getItem(pendingIntroStorageKey) === "1";
    } catch (_) {}
    if (pending && !isLoginCallbackRoute() && isChatShellReady()) {
      showInfographicModal(true);
    }
  }

  function leaveChatForLogout() {
    if (logoutInProgress) return;
    logoutInProgress = true;
    logoutModal.style.display = "none";

    var confirmBtn = logoutModal.querySelector(".modal-confirm-btn");
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.style.cursor = "default";
      confirmBtn.textContent = "Logging out";
    }

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
        e.preventDefault();
        e.stopPropagation();
        e.stopImmediatePropagation();
        leaveChatForLogout();
      }, true);
      btn.addEventListener("click", function(e) {
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

  function handleLogoutConfirmDocumentEvent(e) {
    var target = logoutConfirmTargetFromEvent(e);
    if (!target) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    leaveChatForLogout();
  }

  ["pointerdown", "pointerup", "mouseup", "click"].forEach(function(eventName) {
    document.addEventListener(eventName, function(e) {
      handleLogoutConfirmDocumentEvent(e);
    }, true);
  });

  function showLogoutModal() {
    if (logoutInProgress) return;
    document.querySelectorAll("#logout-modal").forEach(function (modal, index) {
      modal.style.display = index === 0 ? "flex" : "none";
    });
    attachLogoutConfirmHandler();
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
    } else if (event.data === "aims_intro_required" || (event.data && event.data.type === "aims_intro_required")) {
      showInfographicModal(true);
    }
  });

  setInterval(function() {
    interceptNewChat();
    interceptLogout();
    showPendingIntroWhenReady();
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
