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
	    AIMSBotUI: {
	      chainlitIconButtonClass: "icon-button",
	      t(key) {
	        const messages = {
	          "dictation.errors.blocked": "Microphone access was blocked.",
	          "dictation.errors.unavailable": "No microphone was found.",
	          "dictation.errors.noSpeech": "No speech was detected.",
	          "dictation.errors.network": "Speech recognition lost network access.",
	          "dictation.errors.cancelled": "Voice dictation stopped.",
	          "dictation.errors.unexpected": "Voice dictation hit an unexpected error.",
	          "dictation.errors.unsupported": "Voice dictation is not supported in this browser.",
	          "dictation.errors.unavailableShort": "Dictation unavailable",
	          "dictation.errors.startFailed": "Voice dictation could not start.",
	          "dictation.start": "Start dictation",
	          "dictation.stop": "Stop dictation",
	          "dictation.listening": "Listening...",
	          "dictation.lang": "en-US"
	        };
	        return messages[key] || key;
	      },
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
  "aimsbot",
  "dictation.js"
);

const script = fs.readFileSync(scriptPath, "utf8");
vm.runInNewContext(script, context, { filename: scriptPath });

const hooks = context.window.AIMSBotUI.dictation.testHooks;

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
