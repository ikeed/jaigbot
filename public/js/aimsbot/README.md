# Training UI Chainlit Modules

`/public/aimsbot-ui.js` is the single Chainlit `custom_js` entry point. It only
loads these modules in dependency order.

- `core.js`: shared namespace, state, DOM helpers, message helpers.
- `modal.js`: reusable modal creation/show/hide behavior.
- `report-issue.js`: report issue modal and browser-to-server message.
- `infographic.js`: AIMS infographic intro/reference modal.
- `session-controls.js`: new scenario and logout interception.
- `header-actions.js`: header buttons for infographic and issue reporting.
- `dictation.js`: clinician voice dictation into the composer textarea.
- `message-presentation.js`: generic Chainlit role labeling, avatar fixes, and
  copy-button injection from module metadata.
- `splash.js`: loading/splash screen and composer visibility tweaks.
- `window-events.js`: backend-to-browser window message handling.

Keep feature code in these focused modules. The entry point should remain a
small loader so Chainlit configuration stays stable.
