// markdown.ts turns model text into the HTML the chat bubble shows. Its one job that matters is
// that nothing the model (or a document it quoted) wrote can become markup.
import assert from "node:assert/strict";
import { test } from "node:test";

import { escapeHtml, renderMarkdown } from "../src/markdown.ts";

test("the five HTML-significant characters are escaped", () => {
  assert.equal(escapeHtml(`<a href="x" title='y'>Tom & Co</a>`), "&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;Tom &amp; Co&lt;/a&gt;");
});

test("text with nothing to escape is returned unchanged", () => {
  assert.equal(escapeHtml("Plain text, 100% safe."), "Plain text, 100% safe.");
});

test("markup in a reply is shown as text, never rendered", () => {
  const html = renderMarkdown(`<img src=x onerror="alert(1)">`);
  assert.equal(html, "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
  assert.ok(!html.includes("<img"));
});

test("double asterisks become strong and single ones emphasis", () => {
  assert.equal(renderMarkdown("**In scope** and *free of charge*"), "<strong>In scope</strong> and <em>free of charge</em>");
});

test("emphasis inside strong text survives", () => {
  assert.equal(renderMarkdown("**bold with *italic* inside**"), "<strong>bold with <em>italic</em> inside</strong>");
});

test("underscores also mark emphasis", () => {
  assert.equal(renderMarkdown("this is _important_"), "this is <em>important</em>");
});

test("line breaks become <br>", () => {
  assert.equal(renderMarkdown("line one\nline two"), "line one<br>line two");
});

test("markdown markers around escaped text still apply, and the text stays escaped", () => {
  assert.equal(renderMarkdown("**<b>**"), "<strong>&lt;b&gt;</strong>");
});

test("an unmatched asterisk is left as it is", () => {
  assert.equal(renderMarkdown("5 * 3 = 15"), "5 * 3 = 15");
});

test("a value that is not a string renders as nothing rather than as [object Object]", () => {
  assert.equal(renderMarkdown({ text: "x" } as unknown as string), "");
  assert.equal(renderMarkdown(undefined as unknown as string), "");
});
