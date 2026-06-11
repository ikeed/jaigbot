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

const context = {
  console,
  setTimeout: () => 0,
  clearTimeout: () => {},
  MutationObserver: FakeMutationObserver,
  window: {
    setTimeout: () => 0,
    clearTimeout: () => {},
    MutationObserver: FakeMutationObserver,
    Event: function Event(type, init) {
      this.type = type;
      this.bubbles = init && init.bubbles;
    },
    TrainingUI: {
      chainlitIconButtonClass: "icon-button",
      prevent() {},
      state: {}
    }
  },
  document: {
    body: {
      contains() {
        return true;
      }
    },
    querySelectorAll() {
      return [];
    },
    createElement() {
      return {
        setAttribute() {},
        addEventListener() {},
        querySelector() {
          return null;
        },
        innerHTML: "",
        className: "",
        disabled: false,
        title: ""
      };
    }
  }
};

context.window.document = context.document;

const scriptPath = path.join(
  __dirname,
  "..",
  "..",
  "..",
  "public",
  "js",
  "platform",
  "dictation.js"
);

const script = fs.readFileSync(scriptPath, "utf8");
vm.runInNewContext(script, context, { filename: scriptPath });

const hooks = context.window.TrainingUI.dictation.testHooks;

function FakeSpeechRecognition() {}
function FakeWebkitSpeechRecognition() {}

assert.equal(hooks.getRecognitionCtor({ SpeechRecognition: FakeSpeechRecognition }), FakeSpeechRecognition);
assert.equal(hooks.getRecognitionCtor({ webkitSpeechRecognition: FakeWebkitSpeechRecognition }), FakeWebkitSpeechRecognition);
assert.equal(hooks.getRecognitionCtor({}), null);

assert.equal(hooks.joinTranscriptParts("", "Hello"), "Hello");
assert.equal(hooks.joinTranscriptParts("Hello", "world"), "Hello world");

assert.equal(hooks.composeTextareaValue("", "hello", ""), "hello");
assert.equal(hooks.composeTextareaValue("Need to discuss", "timing", "and side effects"), "Need to discuss timing and side effects");
assert.equal(hooks.composeTextareaValue("Need to discuss ", "timing", ""), "Need to discuss timing");

assert.equal(hooks.describeError("not-allowed"), "Microphone access was blocked.");
assert.equal(hooks.describeError("no-speech"), "No speech was detected.");
assert.equal(hooks.describeError("something-else"), "Voice dictation hit an unexpected error.");
