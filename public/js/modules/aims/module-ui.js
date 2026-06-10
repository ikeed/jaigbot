(function (window, document) {
  "use strict";

  const app = window.TrainingUI || window.AIMSBotUI;
  if (!app || app.aimsModuleUiReady) return;
  app.aimsModuleUiReady = true;

  function createInfographicModal() {
    const existing = document.getElementById("aims-infographic-modal");
    if (existing) existing.remove();

    const modal = document.createElement("div");
    modal.id = "aims-infographic-modal";
    modal.className = "aims-infographic-modal";
    modal.setAttribute("aria-hidden", "true");
    modal.innerHTML =
      '<div class="aims-infographic-panel" role="dialog" aria-modal="true" aria-labelledby="aims-infographic-title">' +
      '  <div class="aims-infographic-header">' +
      '    <div class="aims-infographic-copy">' +
      '      <h2 id="aims-infographic-title">Review the AIMS approach</h2>' +
      '      <p>This bot is going to help you practice the AIMS communication protocol for addressing vaccine hesitancy. Before you start, review this infographic so you are prepared for the conversation.</p>' +
      "    </div>" +
      '    <div class="aims-infographic-actions">' +
      '      <button type="button" class="aims-infographic-close" aria-label="Close">Close</button>' +
      '      <button type="button" class="aims-infographic-continue">Start practicing</button>' +
      "    </div>" +
      "  </div>" +
      '  <div class="aims-infographic-scroll">' +
      '    <img src="/public/aims_infographic.svg" alt="Addressing Vaccine Hesitancy with the AIMS Communication Approach infographic" />' +
      "  </div>" +
      "</div>";

    document.body.appendChild(modal);
    if (typeof app.registerManagedModalSelector === "function") {
      app.registerManagedModalSelector("#aims-infographic-modal");
    }
    return modal;
  }

  function makeHeaderButton(id, title, html, onClick) {
    const button = document.createElement("button");
    button.id = id;
    button.type = "button";
    button.className = app.chainlitIconButtonClass;
    button.title = title;
    button.innerHTML = html;
    button.addEventListener("click", onClick);
    return button;
  }

  const modal = createInfographicModal();

  function resetScroll() {
    const scroll = modal.querySelector(".aims-infographic-scroll");
    const img = modal.querySelector(".aims-infographic-scroll img");

    function reset() {
      if (!scroll) return;
      scroll.scrollTop = 0;
      scroll.scrollLeft = 0;
    }

    reset();
    window.requestAnimationFrame(reset);
    if (img && !img.complete) img.addEventListener("load", reset, { once: true });
  }

  function hide() {
    try {
      window.sessionStorage.removeItem(app.state.pendingIntroStorageKey);
    } catch (_) {}
    modal.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
  }

  function show(isIntro) {
    if (isIntro && (app.isLoginCallbackRoute() || !app.isChatShellReady())) {
      try {
        window.sessionStorage.setItem(app.state.pendingIntroStorageKey, "1");
      } catch (_) {}
      return;
    }
    modal.setAttribute("data-mode", isIntro ? "intro" : "reference");
    modal.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
    resetScroll();
  }

  function showPendingWhenReady() {
    let pending = false;
    try {
      pending = window.sessionStorage.getItem(app.state.pendingIntroStorageKey) === "1";
    } catch (_) {}
    if (pending && !app.isLoginCallbackRoute() && app.isChatShellReady()) {
      show(true);
    }
  }

  function injectHeaderButtons() {
    const rightContainer = app.findHeaderActions();
    if (!rightContainer) return;
    if (!document.getElementById("aims-info-button")) {
      rightContainer.insertBefore(
        makeHeaderButton(
          "aims-info-button",
          "AIMS infographic",
          '<span aria-hidden="true" style="font-size:18px">?</span>',
          function () {
            show(false);
          }
        ),
        rightContainer.firstChild
      );
    }
  }

  modal.querySelector(".aims-infographic-close").addEventListener("click", hide);
  modal.querySelector(".aims-infographic-continue").addEventListener("click", function () {
    app.postToChainlit({ type: "training_intro_continue" });
    hide();
  });
  modal.addEventListener("click", function (event) {
    if (event.target === modal && modal.getAttribute("data-mode") === "reference") hide();
  });

  document.addEventListener("training:intro_required", function () {
    show(true);
  });

  injectHeaderButtons();
  window.setInterval(injectHeaderButtons, 1000);
  window.setInterval(showPendingWhenReady, 1000);

  app.infographic = {
    show: show,
    hide: hide,
    showPendingWhenReady: showPendingWhenReady,
  };
})(window, document);
