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
})(window, document);
