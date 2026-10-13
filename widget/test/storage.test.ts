// storage.ts keeps the conversation across a page reload. It is a convenience: when the
// browser refuses (Safari private mode throws), the chat has to carry on without it.
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { readJson, removeKey, writeJson } from "../src/storage.ts";

type Globals = { sessionStorage?: unknown };

function memoryStorage() {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key: string) => (items.has(key) ? items.get(key)! : null),
    setItem: (key: string, value: string) => void items.set(key, value),
    removeItem: (key: string) => void items.delete(key),
  };
}

// What a browser that refuses storage looks like: every access throws.
const refusing = {
  getItem: () => { throw new Error("SecurityError"); },
  setItem: () => { throw new Error("QuotaExceededError"); },
  removeItem: () => { throw new Error("SecurityError"); },
};

let storage: ReturnType<typeof memoryStorage>;

beforeEach(() => {
  storage = memoryStorage();
  (globalThis as Globals).sessionStorage = storage;
});

afterEach(() => {
  delete (globalThis as Globals).sessionStorage;
});

test("a value written is read back with its structure intact", () => {
  writeJson("acme.state", { turn: 3, items: ["a", "b"], nested: { ok: true } });
  assert.deepEqual(readJson("acme.state"), { turn: 3, items: ["a", "b"], nested: { ok: true } });
});

test("values are stored as JSON under the key given", () => {
  writeJson("acme.session", { token: "t" });
  assert.equal(storage.items.get("acme.session"), '{"token":"t"}');
});

test("a key that was never written reads as null", () => {
  assert.equal(readJson("acme.missing"), null);
});

test("an empty stored string reads as null", () => {
  storage.items.set("acme.state", "");
  assert.equal(readJson("acme.state"), null);
});

test("a corrupted value reads as null instead of throwing", () => {
  storage.items.set("acme.state", "{not json");
  assert.equal(readJson("acme.state"), null);
});

test("removing a key forgets it and leaves the others", () => {
  writeJson("acme.state", { a: 1 });
  writeJson("acme.history", [1]);
  removeKey("acme.state");
  assert.equal(readJson("acme.state"), null);
  assert.deepEqual(readJson("acme.history"), [1]);
});

test("when the browser refuses storage, nothing throws and reads are null", () => {
  (globalThis as Globals).sessionStorage = refusing;
  assert.doesNotThrow(() => writeJson("acme.state", { a: 1 }));
  assert.doesNotThrow(() => removeKey("acme.state"));
  assert.equal(readJson("acme.state"), null);
});

test("with no storage at all, as outside a browser, nothing throws", () => {
  delete (globalThis as Globals).sessionStorage;
  assert.doesNotThrow(() => writeJson("acme.state", 1));
  assert.equal(readJson("acme.state"), null);
});
