const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
  }

  observe() {}
}

function runSplash({ hasContent = false, introVisible = false, storage = {} } = {}) {
  const timers = [];
  const location = {
    pathname: "/chat",
    reloadCount: 0,
    assigned: null,
    reload() {
      this.reloadCount += 1;
    },
    assign(url) {
      this.assigned = url;
    }
  };
  const sessionStorage = {
    getItem(key) {
      return Object.prototype.hasOwnProperty.call(storage, key) ? storage[key] : null;
    },
    setItem(key, value) {
      storage[key] = String(value);
    },
    removeItem(key) {
      delete storage[key];
    }
  };
  const document = {
    body: {
      appendChild() {}
    },
    documentElement: {},
    createElement() {
      return { style: {} };
    },
    querySelector(selector) {
      if (
        hasContent &&
        selector === ".aims-scenario-briefing, [data-step-type], [data-author]"
      ) {
        return {};
      }
      return null;
    },
    getElementById(id) {
      if (id !== "aims-infographic-modal") return null;
      return {
        style: { display: introVisible ? "flex" : "none" },
        getAttribute(name) {
          return name === "aria-hidden" && introVisible ? "false" : "true";
        }
      };
    },
    querySelectorAll() {
      return [];
    }
  };
  const context = {
    console,
    MutationObserver: FakeMutationObserver,
    window: {
      location,
      sessionStorage,
      setTimeout(callback) {
        timers.push(callback);
        return timers.length;
      },
      AIMSBotUI: {
        state: {},
        removeManagedModals() {},
        decorateShell() {},
        decorateNativeDialogs() {},
        observeNativeDialogs() {}
      }
    },
    document
  };
  context.window.document = document;
  context.window.MutationObserver = FakeMutationObserver;

  const scriptPath = path.join(
    __dirname,
    "..",
    "..",
    "..",
    "public",
    "js",
    "aimsbot",
    "splash.js"
  );
  const script = fs.readFileSync(scriptPath, "utf8");
  vm.runInNewContext(script, context, { filename: scriptPath });
  return { app: context.window.AIMSBotUI, timers, location, storage };
}

let state = runSplash();
assert.equal(state.storage["aimsbot.startupRecoveryAttempted"], undefined);
state.timers[0](); // Trigger recovery timeout
assert.equal(state.timers.length, 5); // 4 initial + 1 reload delay
state.timers[4](); // Trigger reload delay
assert.equal(state.location.reloadCount, 1);
assert.equal(state.location.assigned, null);
assert.equal(state.storage["aimsbot.startupRecoveryAttempted"], "1");

state = runSplash({ storage: { "aimsbot.startupRecoveryAttempted": "1" } });
state.timers[0]();
assert.equal(state.location.reloadCount, 0);
assert.equal(state.location.assigned, "/chat/logout?reason=startup_timeout");
assert.equal(state.storage["aimsbot.startupRecoveryAttempted"], undefined);

state = runSplash({
  hasContent: true,
  storage: { "aimsbot.startupRecoveryAttempted": "1" }
});
assert.equal(state.app.state.startupResolved, true);
assert.equal(state.storage["aimsbot.startupRecoveryAttempted"], undefined);
state.app.splash.testHooks.recoverFromStartupTimeout();
assert.equal(state.location.reloadCount, 0);
assert.equal(state.location.assigned, null);

state = runSplash({
  introVisible: true,
  storage: { "aimsbot.startupRecoveryAttempted": "1" }
});
assert.equal(state.app.state.startupResolved, true);
assert.equal(state.storage["aimsbot.startupRecoveryAttempted"], undefined);

state = runSplash({
  introVisible: false,
  storage: { "aimsbot.startupRecoveryAttempted": "1" }
});
state.timers[0]();
assert.equal(state.location.assigned, "/chat/logout?reason=startup_timeout");
