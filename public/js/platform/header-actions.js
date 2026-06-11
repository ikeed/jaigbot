(function (window, document) {
  "use strict";

    const app = window.TrainingUI || window.AIMSBotUI;
    if (!app || app.headerActionsReady) return;

  app.headerActionsReady = true;

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

  function injectHeaderButtons() {
      const rightContainer = app.findHeaderActions();
      if (!rightContainer) return;

    if (!document.getElementById("aims-info-button")) {
      rightContainer.insertBefore(makeHeaderButton(
        "aims-info-button",
        "AIMS infographic",
        '<span aria-hidden="true" style="font-size:18px">?</span>',
        function () {
          app.infographic.show(false);
        }
      ), rightContainer.firstChild);
    }

    if (!document.getElementById("sidebar-report-button")) {
      rightContainer.insertBefore(makeHeaderButton(
        "sidebar-report-button",
        "Report Issue",
        '<span aria-hidden="true" style="font-size:18px">🪲</span>',
        app.showReportIssueModal
      ), rightContainer.firstChild);
    }
  }

  injectHeaderButtons();
  window.setInterval(injectHeaderButtons, 1000);
})(window, document);
