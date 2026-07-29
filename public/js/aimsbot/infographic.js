(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.infographicReady) return;

  app.infographicReady = true;

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
      '      <h2 id="aims-infographic-title">' + app.t("infographic.title") + '</h2>' +
      '      <p>' + app.t("infographic.intro") + '</p>' +
      '    </div>' +
      '    <div class="aims-infographic-actions">' +
      '      <button type="button" class="aims-infographic-close" aria-label="' + app.t("infographic.close") + '">' + app.t("infographic.close") + '</button>' +
      '      <button type="button" class="aims-infographic-continue">' + app.t("infographic.start") + '</button>' +
      '    </div>' +
      '  </div>' +
      '  <div class="aims-infographic-scroll">' +
      '    <img src="/public/aims_infographic.svg" alt="' + app.t("infographic.alt") + '" />' +
      '  </div>' +
      "</div>";

    document.body.appendChild(modal);
    return modal;
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
    if (img && !img.complete) {
      img.addEventListener("load", reset, { once: true });
    }
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

  modal.querySelector(".aims-infographic-close").addEventListener("click", hide);
  modal.querySelector(".aims-infographic-continue").addEventListener("click", function () {
    app.postToChainlit({ type: "aims_intro_continue" });
    hide();
  });
  modal.addEventListener("click", function (event) {
    if (event.target === modal && modal.getAttribute("data-mode") === "reference") {
      hide();
    }
  });

  app.infographic = {
    show: show,
    hide: hide,
    showPendingWhenReady: showPendingWhenReady
  };

  window.setInterval(showPendingWhenReady, 1000);
})(window, document);
