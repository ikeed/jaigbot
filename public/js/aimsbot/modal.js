(function (window, document) {
  "use strict";

  var app = window.AIMSBotUI;
  if (!app || app.modalReady) return;

  app.modalReady = true;
  app.modals = app.modals || {};

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  app.createModal = function (options) {
    var existing = document.getElementById(options.id);
    if (existing) existing.remove();

    var modal = document.createElement("div");
    modal.id = options.id;
    modal.className = "aims-modal";
    modal.setAttribute("aria-hidden", "true");

    var textareaHtml = options.showTextarea
      ? '<textarea id="' + options.id + '-input" class="aims-modal-textarea" placeholder="' + escapeHtml(options.placeholder) + '"></textarea>'
      : "";

    modal.innerHTML =
      '<div class="aims-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="' + options.id + '-title">' +
      '  <h3 id="' + options.id + '-title" class="aims-modal-title">' + escapeHtml(options.title) + '</h3>' +
      '  <p class="aims-modal-description">' + escapeHtml(options.description) + '</p>' +
      textareaHtml +
      '  <div class="aims-modal-actions">' +
      '    <button type="button" class="aims-modal-button aims-modal-cancel modal-cancel-btn">Cancel</button>' +
      '    <button type="button" class="aims-modal-button aims-modal-confirm modal-confirm-btn">' + escapeHtml(options.confirmText) + '</button>' +
      "  </div>" +
      "</div>";

    document.body.appendChild(modal);

    modal.querySelector(".modal-cancel-btn").addEventListener("click", function (event) {
      app.prevent(event);
      app.hideModal(modal);
    });

    modal.addEventListener("click", function (event) {
      if (event.target === modal) app.hideModal(modal);
    });

    modal.querySelector(".modal-confirm-btn").addEventListener("click", function (event) {
      app.prevent(event);
      var textarea = modal.querySelector("textarea");
      var value = textarea ? textarea.value.trim() : "";
      if (options.showTextarea && !value) {
        alert(options.emptyMessage || "Please provide a reason.");
        return;
      }

      options.onConfirm(value);
      app.hideModal(modal);
      if (textarea) textarea.value = "";
    });

    return modal;
  };

  app.showModal = function (modal) {
    if (!modal) return;
    modal.setAttribute("aria-hidden", "false");
    modal.style.display = "flex";
  };

  app.hideModal = function (modal) {
    if (!modal) return;
    modal.setAttribute("aria-hidden", "true");
    modal.style.display = "none";
  };
})(window, document);
