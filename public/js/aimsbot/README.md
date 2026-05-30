# AIMSBot Chainlit UI Modules

`/public/aimsbot-ui.js` is the single Chainlit `custom_js` entry point. It only
loads these modules in dependency order.

- `core.js`: shared namespace, state, DOM helpers, message helpers.
- `modal.js`: reusable modal creation/show/hide behavior.
- `report-issue.js`: report issue modal and browser-to-server message.
- `infographic.js`: AIMS infographic intro/reference modal.
- `session-controls.js`: new scenario and logout interception.
- `header-actions.js`: header buttons for infographic and issue reporting.
- `message-roles.js`: Chainlit message role tagging and avatar fixes.
- `splash.js`: loading/splash screen and composer visibility tweaks.
- `window-events.js`: backend-to-browser window message handling.

Keep feature code in these focused modules. The entry point should remain a
small loader so Chainlit configuration stays stable.
