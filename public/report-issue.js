/**
 * Report Issue – sidebar button & modal
 *
 * Loaded via Chainlit's custom_js config option so it runs as a native
 * <script> in the page and is never subject to message-content sanitisation.
 *
 * Communication: uses window.postMessage → @cl.on_window_message on the
 * Python side, which is the supported Chainlit 2.x browser→server channel.
 */
(function () {
  "use strict";

  /* ── guard against double-init ─────────────────────────────────── */
  if (document.getElementById("sidebar-report-button")) return;

  /* ── splash screen tweaks: enlarge icon & hide composer ──────── */
  function tweakSplash() {
    // Enlarge the chat profile icon (find by src containing "aimsbot")
    document.querySelectorAll("img").forEach(function (img) {
      var src = (img.src || "").toLowerCase();
      if (src.indexOf("aimsbot") !== -1) {
        img.style.width = "256px";
        img.style.height = "256px";
        img.style.maxWidth = "none";
        img.style.maxHeight = "none";
      }
    });

    // Hide the Chainlit composer until a message appears.
    // Target the specific "Type your message" textarea, NOT our report modal textarea.
    if (!document._aimsComposerHidden) {
      var textareas = document.querySelectorAll('textarea[placeholder]');
      textareas.forEach(function (ta) {
        // Skip our own report-issue textarea
        if (ta.id === "report-reason-input-shared") return;
        // Skip if already inside the report modal
        if (ta.closest("#report-issue-modal")) return;

        // Find the composer form wrapper
        var form = ta.closest("form");
        if (form && !form._aimsHidden) {
          form._aimsHidden = true;
          form.style.display = "none";
          document._aimsComposerHidden = form;

          // Reveal once the first chat message appears
          var obs = new MutationObserver(function () {
            var hasMsg = document.querySelector('[data-step-type], [data-author]');
            if (hasMsg) {
              form.style.display = "";
              obs.disconnect();
            }
          });
          obs.observe(document.body, { childList: true, subtree: true });
        }
      });
    }
  }

  // Run immediately and retry (Chainlit renders asynchronously)
  tweakSplash();
  setTimeout(tweakSplash, 300);
  setTimeout(tweakSplash, 800);
  setTimeout(tweakSplash, 1500);

  /* ── button ────────────────────────────────────────────────────── */
  var btn = document.createElement("div");
  btn.id = "sidebar-report-button";
  btn.innerHTML = '<span style="font-size:18px">🪲</span> Report Issue';
  Object.assign(btn.style, {
    position: "fixed",
    left: "16px",
    bottom: "80px",
    zIndex: "1000",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "10px 16px",
    background: "#f0f4f8",
    border: "1px solid #d1d9e0",
    borderRadius: "20px",
    cursor: "pointer",
    fontFamily: "sans-serif",
    color: "#333",
    fontWeight: "500",
    boxShadow: "0 2px 5px rgba(0,0,0,0.1)",
    transition: "background 0.2s",
  });
  btn.addEventListener("mouseenter", function () {
    btn.style.background = "#e2e8f0";
  });
  btn.addEventListener("mouseleave", function () {
    btn.style.background = "#f0f4f8";
  });

  /* ── modal ─────────────────────────────────────────────────────── */
  var modal = document.createElement("div");
  modal.id = "report-issue-modal";
  Object.assign(modal.style, {
    display: "none",
    position: "fixed",
    top: "0",
    left: "0",
    width: "100%",
    height: "100%",
    background: "rgba(0,0,0,0.5)",
    zIndex: "2000",
    justifyContent: "center",
    alignItems: "center",
    fontFamily: "sans-serif",
  });

  modal.innerHTML =
    '<div style="background:#ffffff;padding:24px;border-radius:8px;width:400px;box-shadow:0 4px 12px rgba(0,0,0,0.15)">' +
    '  <h3 style="margin-top:0;color:#1a1a1a;font-size:18px">Report Issue</h3>' +
    '  <p style="color:#444;font-size:14px;line-height:1.5">Describe the issue you encountered. This will end the session and log a report.</p>' +
    '  <textarea id="report-reason-input-shared" placeholder="What went wrong?" style="width:100%;height:100px;margin:12px 0;padding:8px;border:1px solid #999;border-radius:4px;resize:none;font-size:14px;color:#1a1a1a;background:#fff"></textarea>' +
    '  <div style="display:flex;justify-content:flex-end;gap:8px">' +
    '    <button id="report-cancel-btn" style="padding:8px 16px;border:1px solid #888;background:#fff;color:#1a1a1a;border-radius:4px;cursor:pointer;font-size:14px">Cancel</button>' +
    '    <button id="submit-report-btn-shared" style="padding:8px 16px;border:none;background:#1a73e8;color:#fff;border-radius:4px;cursor:pointer;font-size:14px;font-weight:600">Submit Report</button>' +
    "  </div>" +
    "</div>";

  /* ── append to DOM ─────────────────────────────────────────────── */
  document.body.appendChild(btn);
  document.body.appendChild(modal);

  /* ── event listeners ───────────────────────────────────────────── */
  btn.addEventListener("click", function () {
    modal.style.display = "flex";
  });

  document.getElementById("report-cancel-btn").addEventListener("click", function () {
    modal.style.display = "none";
  });

  // Close modal on backdrop click
  modal.addEventListener("click", function (e) {
    if (e.target === modal) modal.style.display = "none";
  });

  document.getElementById("submit-report-btn-shared").addEventListener("click", function () {
    var input = document.getElementById("report-reason-input-shared");
    var reason = input ? input.value.trim() : "";
    if (!reason) {
      alert("Please provide a reason.");
      return;
    }

    // Use Chainlit's window.postMessage channel (@cl.on_window_message)
    var payload = JSON.stringify({ type: "report_issue", reason: reason });
    window.postMessage(payload, "*");
    modal.style.display = "none";
    if (input) input.value = "";
  });
})();
