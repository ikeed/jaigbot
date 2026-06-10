(function (window) {
  "use strict";

  const app = window.TrainingUI || window.AIMSBotUI;
  if (!app || app.interviewModuleUiReady) return;
  app.interviewModuleUiReady = true;
})(window);
