(function (window, document) {
  "use strict";

    const app = window.TrainingUI || window.AIMSBotUI;
    if (!app || app.reportIssueReady) return;

  app.reportIssueReady = true;
  app.modals.reportIssue = app.createModal({
    id: "report-issue-modal",
    title: "Report Issue",
    description: "Describe the issue you encountered. This will end the session and log a report.",
    placeholder: "What went wrong?",
    showTextarea: true,
    confirmText: "Submit Report",
    onConfirm: function (reason) {
      app.postToChainlit({ type: "report_issue", reason: reason });
    }
  });

  app.showReportIssueModal = function () {
    app.showModal(app.modals.reportIssue);
    window.setTimeout(function () {
        const input = document.getElementById("report-issue-modal-input");
        if (input) input.focus();
    }, 100);
  };

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

  function injectReportIssueButton() {
    const rightContainer = app.findHeaderActions && app.findHeaderActions();
    if (!rightContainer || document.getElementById("sidebar-report-button")) return;

    rightContainer.insertBefore(
      makeHeaderButton(
        "sidebar-report-button",
        "Report Issue",
        '<span aria-hidden="true" style="font-size:18px">🪲</span>',
        app.showReportIssueModal
      ),
      rightContainer.firstChild
    );
  }

  injectReportIssueButton();
  if (typeof app.observeDomTask === "function") {
    app.observeDomTask("reportIssueHeaderButton", injectReportIssueButton, { debounceMs: 100 });
  } else {
    window.setInterval(injectReportIssueButton, 1000);
  }
})(window, document);
