(function (window, document) {
  "use strict";

    const app = window.TrainingUI || window.AIMSBotUI;
    if (!app || app.splashReady) return;

  app.splashReady = true;

  function matchesBrandingLogo(img) {
    const src = String((img && img.src) || "").toLowerCase();
    const logoAsset = String((app.branding && app.branding.logoAsset) || "").toLowerCase();
    return !!logoAsset && src.indexOf(logoAsset) !== -1;
  }

  function revealComposerWhenMessagesAppear(form) {
      const observer = new MutationObserver(function () {
          const hasMessage = document.querySelector("[data-step-type], [data-author]");
          if (!hasMessage) return;
          form.style.display = "";
          observer.disconnect();
      });
      observer.observe(document.body, { childList: true, subtree: true });
  }

  function tweakSplash() {
    document.querySelectorAll("img").forEach(function (img) {
        if (!matchesBrandingLogo(img)) return;

      img.style.width = "256px";
      img.style.height = "256px";
      img.style.maxWidth = "none";
      img.style.maxHeight = "none";
    });

    if (document._aimsComposerHidden) return;

    document.querySelectorAll("textarea[placeholder]").forEach(function (textarea) {
      if (textarea.id === "report-issue-modal-input") return;
      if (textarea.closest("#report-issue-modal")) return;

        const form = textarea.closest("form");
        if (!form || form._aimsHidden) return;

      form._aimsHidden = true;
      form.style.display = "none";
      document._aimsComposerHidden = form;
      revealComposerWhenMessagesAppear(form);
    });
  }

  tweakSplash();
  if (typeof app.observeDomTask === "function") {
    app.observeDomTask("splashTweaks", tweakSplash, { debounceMs: 100 });
  } else if (document.body) {
    const observer = new MutationObserver(function () {
      tweakSplash();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  app.splash = {
    tweak: tweakSplash
  };
})(window, document);
