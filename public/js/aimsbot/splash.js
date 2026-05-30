(function (window, document) {
  "use strict";

  var app = window.AIMSBotUI;
  if (!app || app.splashReady) return;

  app.splashReady = true;

  function revealComposerWhenMessagesAppear(form) {
    var observer = new MutationObserver(function () {
      var hasMessage = document.querySelector("[data-step-type], [data-author]");
      if (!hasMessage) return;
      form.style.display = "";
      observer.disconnect();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function tweakSplash() {
    document.querySelectorAll("img").forEach(function (img) {
      var src = (img.src || "").toLowerCase();
      if (src.indexOf("aimsbot") === -1) return;

      img.style.width = "256px";
      img.style.height = "256px";
      img.style.maxWidth = "none";
      img.style.maxHeight = "none";
    });

    if (document._aimsComposerHidden) return;

    document.querySelectorAll("textarea[placeholder]").forEach(function (textarea) {
      if (textarea.id === "report-issue-modal-input") return;
      if (textarea.closest("#report-issue-modal")) return;

      var form = textarea.closest("form");
      if (!form || form._aimsHidden) return;

      form._aimsHidden = true;
      form.style.display = "none";
      document._aimsComposerHidden = form;
      revealComposerWhenMessagesAppear(form);
    });
  }

  tweakSplash();
  window.setTimeout(tweakSplash, 300);
  window.setTimeout(tweakSplash, 800);
  window.setTimeout(tweakSplash, 1500);

  app.splash = {
    tweak: tweakSplash
  };
})(window, document);
