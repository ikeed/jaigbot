(function (window) {
  "use strict";

  var app = window.AIMSBotUI;
  if (!app || app.windowEventsReady) return;

  app.windowEventsReady = true;

  window.addEventListener("message", function (event) {
    var type = app.messageType(event.data);

    if (type === "on_duplicate_tab") {
      window.location.href = "/duplicate";
    } else if (type === "on_logout") {
      window.location.href = "/";
    } else if (type === "aims_intro_required") {
      app.infographic.show(true);
    }
  });
})(window);
