(function (window, document) {
  "use strict";

    const app = window.AIMSBotUI;
    if (!app || app.reportIssueReady) return;

  app.reportIssueReady = true;
  app.modals.reportIssue = app.createModal({
    id: "report-issue-modal",
    title: app.t("reportIssue.title"),
    description: app.t("reportIssue.description"),
    placeholder: app.t("reportIssue.placeholder"),
    showTextarea: true,
    confirmText: app.t("reportIssue.confirm"),
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
