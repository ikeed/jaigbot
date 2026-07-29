const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeClassList {
  constructor() {
    this.names = new Set();
  }

  add(...names) {
    names.forEach((name) => this.names.add(name));
  }

  contains(name) {
    return this.names.has(name);
  }
}

class FakeElement {
  constructor(tagName, { id = "", role = "", text = "", attrs = {}, children = [] } = {}) {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.role = role;
    this._text = text;
    this.attrs = { ...attrs };
    this.children = [];
    this.classList = new FakeClassList();
    this.dataset = {};
    this.style = {};
    this.parentElement = null;

    if (id) this.attrs.id = id;
    if (role) this.attrs.role = role;
    children.forEach((child) => this.appendChild(child));
  }

  appendChild(child) {
    child.parentElement = this;
    this.children.push(child);
  }

  remove() {
    if (!this.parentElement) return;
    this.parentElement.children = this.parentElement.children.filter((child) => child !== this);
    this.parentElement = null;
  }

  get lastElementChild() {
    return this.children[this.children.length - 1] || null;
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === "id") this.id = String(value);
    if (name === "role") this.role = String(value);
  }

  getAttribute(name) {
    return this.attrs[name] || null;
  }

  matches(selector) {
    return selector.split(",").some((part) => this.matchesOne(part.trim()));
  }

  matchesOne(selector) {
    if (!selector) return false;
    if (selector.startsWith("#")) return this.id === selector.slice(1);

    if (selector.startsWith('[role="') && selector.endsWith('"]')) {
      return this.role === selector.slice(7, -2);
    }

    const attrStart = selector.indexOf("[");
    if (attrStart > 0 && selector.endsWith("]")) {
      const tagName = selector.slice(0, attrStart);
      const attrName = selector.slice(attrStart + 1, -1);
      return (
        this.tagName.toLowerCase() === tagName.toLowerCase() &&
        Object.prototype.hasOwnProperty.call(this.attrs, attrName)
      );
    }

    return this.tagName.toLowerCase() === selector.toLowerCase();
  }

  closest(selector) {
    let node = this;
    while (node) {
      if (node.matches(selector)) return node;
      node = node.parentElement;
    }
    return null;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  querySelectorAll(selector) {
    const matches = [];

    function visit(node) {
      node.children.forEach((child) => {
        if (child.matches(selector)) matches.push(child);
        visit(child);
      });
    }

    visit(this);
    return matches;
  }
}

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
  }

  observe() {}
}

function element(tagName, options) {
  return new FakeElement(tagName, options);
}

function runCore(bodyChildren = []) {
  const body = element("body", { children: bodyChildren });
  const documentElement = element("html");
  const document = {
    body,
    documentElement,
    getElementById(id) {
      return body.querySelector("#" + id) || (body.id === id ? body : null);
    },
    querySelectorAll(selector) {
      return body.querySelectorAll(selector);
    }
  };
  const context = {
    console,
    MutationObserver: FakeMutationObserver,
    window: {
      location: { origin: "http://localhost:8000", search: "", pathname: "/chat" },
      history: { replaceState() {} },
      setTimeout() {},
      AIMSBotUI: {}
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
    "core.js"
  );
  const script = fs.readFileSync(scriptPath, "utf8");
  vm.runInNewContext(script, context, { filename: scriptPath });

  return { app: context.window.AIMSBotUI, document };
}

const closeButton = element("button", { text: "×" });
const cancelButton = element("button", { text: "Cancel" });
const confirmButton = element("button", { text: "Confirm" });
const renameInput = element("input", { attrs: { placeholder: "Enter new name" } });
const nameLabel = element("label", { text: "Name" });
const renameDialog = element("div", {
  role: "dialog",
  children: [
    closeButton,
    element("h2", { text: "Rename Thread" }),
    element("p", { text: "Enter a new name for this thread" }),
    nameLabel,
    renameInput,
    element("div", { children: [cancelButton, confirmButton] })
  ]
});

runCore([renameDialog]);

assert.equal(renameDialog.classList.contains("aims-native-dialog"), true);
assert.equal(closeButton.classList.contains("aims-native-dialog-close"), true);
assert.equal(cancelButton.classList.contains("aims-native-dialog-cancel"), true);
assert.equal(confirmButton.classList.contains("aims-native-dialog-confirm"), true);
assert.equal(renameInput.classList.contains("aims-native-dialog-input"), true);
assert.equal(nameLabel.classList.contains("aims-native-dialog-label"), true);

const alertDialog = element("div", {
  role: "alertdialog",
  children: [
    element("h2", { text: "Start New Scenario" }),
    element("button", { text: "Cancel" }),
    element("button", { text: "Confirm" })
  ]
});

runCore([alertDialog]);

assert.equal(alertDialog.classList.contains("aims-native-dialog"), true);

const managedDialog = element("div", { role: "dialog" });
const managedOverlay = element("div", { id: "report-issue-modal", children: [managedDialog] });
const state = runCore();
state.document.body.appendChild(managedOverlay);
state.app.decorateNativeDialogs();

assert.equal(managedDialog.classList.contains("aims-native-dialog"), false);
