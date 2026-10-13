// api.ts is the widget's whole view of the service: signing in, reading the catalogue, and
// decoding the server-sent event stream of a reply. The service is replaced by a local fetch
// that returns real Response objects, so the parsing under test is the code that ships.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { createSession, fetchCatalog, streamChat, type StreamHandlers } from "../src/api.ts";

const API = "https://assistant.test";
const realFetch = globalThis.fetch;

type Call = { url: string; init: RequestInit };

function serve(reply: (call: Call) => Response): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = (async (url: string | URL | Request, init: RequestInit = {}) => {
    const call = { url: String(url), init };
    calls.push(call);
    return reply(call);
  }) as typeof fetch;
  return calls;
}

afterEach(() => {
  globalThis.fetch = realFetch;
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// A body delivered in the given pieces, as a network would deliver it.
function stream(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status });
}

function recorder() {
  const seen: { verdicts: unknown[]; text: string[]; done: unknown[] } = { verdicts: [], text: [], done: [] };
  const handlers: StreamHandlers = {
    onVerdict: (payload) => seen.verdicts.push(payload),
    onText: (text) => seen.text.push(text),
    onDone: (payload) => seen.done.push(payload),
  };
  return { seen, handlers };
}

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

// ---------------------------------------------------------------- session

test("signing in posts the password and who is asking, and returns the session", async () => {
  const calls = serve(() => json({ token: "tok", expiresAt: 123, role: "requester", country: "United Kingdom", branch: "Acme London" }));
  const session = await createSession(API, "pw", { subject: "Robin", branch: "Acme London" });

  assert.equal(calls[0].url, `${API}/api/session`);
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), { password: "pw", subject: "Robin", branch: "Acme London", country: null });
  assert.deepEqual(session, { token: "tok", expiresAt: 123, role: "requester", subject: "Robin", country: "United Kingdom", branch: "Acme London" });
});

test("the subject the server confirms wins over the one typed", async () => {
  serve(() => json({ token: "t", expiresAt: 1, role: "r", subject: "Robin M." }));
  assert.equal((await createSession(API, "pw", { subject: "robin" })).subject, "Robin M.");
});

test("a refused sign-in reports the server's reason", async () => {
  serve(() => json({ detail: "That password is not right." }, 401));
  await assert.rejects(createSession(API, "nope", { subject: "Robin" }), /That password is not right\./);
});

test("a refusal with no readable reason still says sign-in failed", async () => {
  serve(() => new Response("<html>bad gateway</html>", { status: 502 }));
  await assert.rejects(createSession(API, "pw", { subject: "Robin" }), /Could not sign in\./);
});

test("a validation error names each field instead of printing [object Object]", async () => {
  serve(() => json({ detail: [{ loc: ["body", "subject"], msg: "field required" }, "plain", { other: 1 }] }, 422));
  await assert.rejects(createSession(API, "pw", { subject: "" }), (error: Error) => {
    assert.equal(error.message, "body.subject: field required; plain");
    return true;
  });
});

test("a validation error with nothing readable in it gets a generic message", async () => {
  serve(() => json({ detail: [{ nothing: true }] }, 422));
  await assert.rejects(createSession(API, "pw", { subject: "" }), /Request failed validation\./);
});

// ---------------------------------------------------------------- catalogue

test("the catalogue is fetched with the session token and returned by category", async () => {
  const categories = [{ status: "Y", label: "In scope", count: 1, items: [{ id: "a", name: "Emails", section: "Copywriting", summary: "" }] }];
  const calls = serve(() => json({ categories }));
  assert.deepEqual(await fetchCatalog(API, "tok"), categories);
  assert.equal(calls[0].url, `${API}/api/catalog`);
  assert.deepEqual(calls[0].init.headers, { Authorization: "Bearer tok" });
});

test("without a token no Authorization header is sent", async () => {
  const calls = serve(() => json({ categories: [] }));
  await fetchCatalog(API, null);
  assert.deepEqual(calls[0].init.headers, {});
});

test("a reply with no categories is an empty catalogue", async () => {
  serve(() => json({}));
  assert.deepEqual(await fetchCatalog(API, null), []);
});

test("a refused catalogue request rejects with the server's reason", async () => {
  serve(() => json({ detail: "Session expired." }, 401));
  await assert.rejects(fetchCatalog(API, "old"), /Session expired\./);
});

// ---------------------------------------------------------------- chat stream

test("a turn posts the message, state, history and note with the token", async () => {
  const calls = serve(() => stream([]));
  const { handlers } = recorder();
  const state = { turn: 1 } as never;
  await streamChat(API, "Can we get a radio ad?", state, [{ role: "user", content: "hi" }] as never, "tok", handlers, undefined, "for March");

  assert.equal(calls[0].url, `${API}/api/chat/stream`);
  assert.deepEqual(calls[0].init.headers, { "Content-Type": "application/json", Authorization: "Bearer tok" });
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
    message: "Can we get a radio ad?", state: { turn: 1 }, history: [{ role: "user", content: "hi" }], note: "for March",
  });
});

test("an empty note is sent as null and no token means no Authorization header", async () => {
  const calls = serve(() => stream([]));
  await streamChat(API, "hi", null, [], null, recorder().handlers, undefined, "");
  assert.equal(JSON.parse(String(calls[0].init.body)).note, null);
  assert.deepEqual(calls[0].init.headers, { "Content-Type": "application/json" });
});

test("verdict, text and done events reach their handlers in order", async () => {
  const verdict = { verdict: { status: "Y", meaning: "In scope", service: "Emails" }, citations: ["copywriting--emails"], notes: [], needsAHuman: false, awaitingAnswer: false, candidates: [], actions: [] };
  serve(() => stream([sse("verdict", verdict), sse("text", { text: "Yes, " }), sse("text", { text: "that is included." }), sse("done", { text: "Yes, that is included.", source: "llm", degraded: false, truncated: false, state: { turn: 2 } })]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);

  assert.deepEqual(seen.verdicts, [verdict]);
  assert.deepEqual(seen.text, ["Yes, ", "that is included."]);
  assert.deepEqual(seen.done, [{ text: "Yes, that is included.", source: "llm", degraded: false, truncated: false, state: { turn: 2 } }]);
});

test("an event split across network chunks is put back together", async () => {
  const whole = sse("text", { text: "one piece" });
  serve(() => stream([whole.slice(0, 9), whole.slice(9, 25), whole.slice(25)]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);
  assert.deepEqual(seen.text, ["one piece"]);
});

test("a final event with no trailing blank line is still delivered", async () => {
  serve(() => stream([`event: text\ndata: ${JSON.stringify({ text: "last" })}`]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);
  assert.deepEqual(seen.text, ["last"]);
});

test("a multi-byte character split between chunks is decoded correctly", async () => {
  const bytes = new TextEncoder().encode(sse("text", { text: "£250 café" }));
  const cut = bytes.indexOf(0xc2) + 1; // inside the two-byte "£"
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes.slice(0, cut));
      controller.enqueue(bytes.slice(cut));
      controller.close();
    },
  });
  serve(() => new Response(body));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);
  assert.deepEqual(seen.text, ["£250 café"]);
});

test("malformed, empty and unknown events are skipped without stopping the stream", async () => {
  serve(() => stream(["event: text\ndata: {not json\n\n", "event: text\n\n", sse("ping", { at: 1 }), ": comment\n\n", sse("text", { text: "still here" })]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);
  assert.deepEqual(seen.text, ["still here"]);
  assert.deepEqual(seen.verdicts, []);
});

test("values that are not strings never reach the page as [object Object]", async () => {
  serve(() => stream([
    sse("text", { text: { nested: true } }),
    sse("text", { text: "[object Object]" }),
    sse("verdict", { verdict: { status: { x: 1 }, meaning: "In scope", service: null }, citations: ["ok", 5, "[object Object]"], notes: "not a list", candidates: "nope" }),
    sse("done", { text: 42, source: null, state: {} }),
  ]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);

  assert.deepEqual(seen.text, [], "non-string text chunks are dropped");
  assert.deepEqual(seen.verdicts, [{
    verdict: { status: "", meaning: "In scope", service: "" },
    citations: ["ok"], notes: [], needsAHuman: false, awaitingAnswer: false, candidates: [], actions: [],
  }]);
  assert.deepEqual(seen.done, [{ text: "", source: "deterministic", degraded: false, truncated: false, state: {} }]);
});

test("a verdict event with no verdict is passed on as null", async () => {
  serve(() => stream([sse("verdict", { verdict: null, needsAHuman: true })]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);
  assert.equal((seen.verdicts[0] as { verdict: unknown }).verdict, null);
  assert.equal((seen.verdicts[0] as { needsAHuman: boolean }).needsAHuman, true);
});

test("a data line spanning several lines is joined before parsing", async () => {
  serve(() => stream([`event: text\ndata: {"text":\ndata: "two lines"}\n\n`]));
  const { seen, handlers } = recorder();
  await streamChat(API, "q", null, [], null, handlers);
  assert.deepEqual(seen.text, ["two lines"]);
});

test("a refused turn rejects with the server's reason, or the status when there is none", async () => {
  serve(() => json({ detail: "You are sending messages too quickly." }, 429));
  await assert.rejects(streamChat(API, "q", null, [], "tok", recorder().handlers), /too quickly/);

  serve(() => new Response("oops", { status: 500 }));
  await assert.rejects(streamChat(API, "q", null, [], "tok", recorder().handlers), /Request failed \(500\)/);
});

test("a reply with no body is treated as a failure", async () => {
  serve(() => new Response(null, { status: 200 }));
  await assert.rejects(streamChat(API, "q", null, [], null, recorder().handlers), /Request failed \(200\)/);
});

test("the abort signal is handed to fetch so a turn can be cancelled", async () => {
  const calls = serve(() => stream([]));
  const controller = new AbortController();
  await streamChat(API, "q", null, [], null, recorder().handlers, controller.signal);
  assert.equal(calls[0].init.signal, controller.signal);
});
