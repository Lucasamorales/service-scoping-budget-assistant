# RAG + Tooling Architecture Template

A portable write-up of how the Editorial Bot is built, aimed at starting a **different**
domain from scratch. Every mechanic below is in production in this repo, so each section
names the real file and the real decision behind it.

Read this alongside, not instead of, the code. Where a rule exists because something broke,
the breakage is written down — those are the parts worth copying most.

> Not to be confused with `RAG-ARCHITECTURE-GUIDE.md` in this repo, which documents an
> earlier, simpler project (vanilla-JS widget, Firestore vector search, no routing, no
> tools). Use that one for infrastructure and deployment patterns. Use this one for
> retrieval behaviour, grounding and tool design.

---

## 0. The one idea that matters most

**Retrieval is a workflow decision before it is a similarity problem.**

Naive RAG embeds the question, takes the top-k nearest chunks and hopes. That works for
"look something up" and fails for "do a job", because the chunks the model *needs* are
often not the chunks nearest the question. A user asking "check chapter 5 against the
standard" needs the *rule* (a policy document) and the *subject* (chapter 5) — two
different document types, one of which the question barely mentions.

So this architecture routes first: it decides **what kind of job this is**, and from that
**which document types are allowed to answer**. Similarity ranks *within* that decision.

Everything else follows from taking that seriously.

If you copy one thing, copy this:

```
message ──▶ router ──▶ { intent, doc types, ids, entity hint, needsState }
                          │
                          ▼
                     retrieval (filter → force → score → cap)
                          │
                          ▼
        context pack: always-on + state + measurements + slices
                          │
                          ▼
                       model (+ tools that only propose)
                          │
                          ▼
            deterministic post-processing ──▶ UI ──▶ user confirms ──▶ write
```

---

## 1. Layer 0 — The corpus

### Typed documents, declared in a manifest

Files are never discovered by globbing. They are declared, with a type, in one config
object per tenant (`src/lib/tenants.ts`):

```ts
knowledgeManifest: [
  { file: "01-SOP-beta-feedback-analysis.md", docType: "sop",          sopId: "01" },
  { file: "05-SOP-esl-copyedit-voice.md",     docType: "sop_flagship", sopId: "05" },
  { file: "TEMPLATE-intro-outline.md",        docType: "template",     sopId: "intro" },
  { file: "DRAFT-blurbs.md",                  docType: "blurbs" },
  { file: "00-PROJECT-INSTRUCTIONS.md",       docType: "meta", excludeFromRetrieval: true },
]
```

Why a manifest and not a folder scan:

- `docType` is the primary retrieval lever (see §5). It has to be author-declared, because
  no heuristic reliably tells a *policy* from a *worked example* from *raw subject matter*.
- A stable `sopId` (or any short document id) lets the router say "for this job, SOP 02 and
  03 are relevant" without embedding anything.
- `excludeFromRetrieval` matters: some documents belong in the **always-on prompt** and must
  never come back as a retrieved slice, or the model cites its own instructions as evidence.

### Domain policy lives in the corpus, never in code

The strongest rule in this project: **the editor's rules are parsed out of her markdown at
runtime; they are never transcribed into TypeScript.** `chapter-standard.ts` reads the five
structural elements out of `03-SOP-developmental-editing.md` with a regex over its numbered
list. If she edits the SOP, the app changes.

```ts
const ELEMENT_RE = /^\d+\.\s+\*\*(.+?)\*\*\s*[—–-]\s*(.+)$/;
// → { id: "opening-quote", label: "Opening quote", rule: "under 12 words, attributed…" }
```

This is worth the parsing awkwardness. The moment domain rules are duplicated in code you
have two sources of truth and the code silently wins.

**Port it as:** whatever your domain expert owns — refund policy, clinical guideline, style
guide, contract playbook — stays in their file. Parse it. Cite it back by section.

### Three document classes to plan for

| Class | Example here | Retrieval behaviour |
|---|---|---|
| **Policy / rules** | the 8 SOPs | routed by job; one type is *flagship* and gets a guaranteed slot |
| **Subject matter** | the manuscript | must be force-included for any job that edits it (§5.3) |
| **Worked examples** | templates, blurbs | retrieved only for the specific job that uses them |

---

## 2. Layer 1 — Preprocessing

`src/lib/preprocess.ts`. Small, boring, and it prevents a whole class of retrieval bug.

```ts
repairEncoding()               // mojibake table: â€™ → ' , Â£ → £
normalizeGoogleDocsMarkdown()  // strip empty "### " headings, unescape 2020\. → 2020.
                               // collapse 4+ blank lines
detectSensitivity()            // tag chunks: none | family | legal | photo
splitAtSentenceBoundary()      // never cut mid-sentence
```

Lessons behind each:

- **Mojibake is retrieval-visible.** A chunk containing `â€™` fails a keyword match on
  `don't`. Fix at ingest, not at query time.
- **Exported documents lie about structure.** Google Docs markdown exports leave empty
  `###` lines and backslash-escape punctuation. Both break heading-based chunking. Look at
  your real export before writing the chunker.
- **Sensitivity tags at ingest** let the app route topics to a human instead of answering
  them. Cheap to add early, invasive to add later.

Ship a `preview-chunks` script before ingesting anything (`scripts/preview-chunks.ts`). Look
at twenty chunks with your own eyes. Most chunking bugs are obvious on sight and invisible
in metrics.

---

## 3. Layer 2 — Chunking

`src/lib/chunking.ts`. Two ideas do the heavy lifting.

### 3.1 Chunk by structure, then split by size

Split on headings first so a chunk is a *semantic unit*, then only split oversized sections
at sentence boundaries with overlap:

```ts
const BOOK_MAX = 1400;      // chars, not tokens — deliberately coarse
const BOOK_OVERLAP = 160;
const MIN_CHARS = 80;       // below this, it is a fragment, not a chunk
```

Overlap exists so a sentence spanning a boundary is retrievable from either side. It has a
cost you must plan for: **chunks now contain duplicated text**, so anything that
reconstructs a longer passage has to merge them (§7.2).

### 3.2 Chunks are self-describing

Every chunk carries its own provenance *inside the text*, not only in metadata:

```
[SOP 05 — Interference taxonomy — Prepositions]
Use when: awkward phrasing, ESL-check, hedging strip, fix errors keep accent
<the actual content>
```

Two reasons this beats metadata-only:

1. The model sees the label in-context, so it can cite accurately without a separate
   instruction telling it what it is reading.
2. `Use when:` is a **retrieval hint written by a human**, and it participates in keyword
   scoring. It is the cheapest possible relevance boost and needs no embedding.

The cost: consumers must strip the header when they want raw text. That is a two-line
function (`stripChunkHeader` in `chapter-scan.ts`) — worth it.

### 3.3 One chunker per document type

`chunkDocument()` dispatches on `docType`:

| Type | Strategy | Why |
|---|---|---|
| flagship policy | one chunk per `##`, `maxChars: 2000` | retrieval must return *one precise category*, not a blob |
| standard policy | heading chunks + `Use when` | ordinary routing is enough |
| template | **whole document** under 3500 chars | a partial template is worse than none — it must stay coherent |
| subject matter | chapter/section aware, tight max | never let one chunk dominate a pack |
| meta | `return []` | belongs in the always-on prompt |

**The template case is the instructive one.** Uniform chunking would have shredded a
nine-beat outline into three chunks and the model would have confidently produced a
six-beat outline. Ask of each document type: *what is the smallest piece of this that is
still true?* Chunk to that.

### 3.4 Repair known source quirks in the chunker

```ts
// Docs export uses **Chapter N: title** for Ch2+ instead of real # headings
text = text.replace(/^\*\*Chapter\s+(\d+)\s*:\s*([^*]+)\*\*\s*$/gim, "# Chapter $1: $2");
```

Real documents are inconsistent with themselves. This one manuscript uses `##` subheads for
three chapters and bold-only lines for the other eight. Normalise at ingest where you can,
and handle both forms where you cannot (§7.3).

---

## 4. Layer 3 — The index

### Chunk schema

```ts
{
  content, source, docType, sopId,        // identity + routing
  chapter, sectionTitle, useWhen,          // human-meaningful locators
  chunkIndex,                              // ORDER — load-bearing, see below
  sensitivity, embedding?
}
```

`chunkIndex` earns its place three separate times: neighbour-window expansion in retrieval
(§5.3), reconstructing a whole section for deterministic analysis (§7.2), and stable
deduplication keys (`${source}:${chunkIndex}`).

### Build-time index, runtime read

The index is a JSON file built during deployment (`npm run build` runs `build-index` before
`next build`) and is **gitignored**. Practical consequences worth copying:

- Serverless filesystems are read-only and cold-start empty. Anything read at request time
  must be built into the bundle, and anything *written* must go to an external store.
- Never read a loose source file at request time. Read the built index. In this repo the
  chapter scanner deliberately reconstructs chapters from chunks rather than reading the
  manuscript, because there is no guarantee the bundler traces a root-level `.md`.
- Keep an offline path. `loadLocalIndex()` returns `[]` rather than throwing, and retrieval
  reports `mode: "empty"` instead of failing the turn.

### Embeddings are optional, not assumed

`retrieveForIntent()` checks `candidates.some(c => c.embedding?.length)` and falls back to
pure keyword scoring with heavier doc-type boosts. It also catches embedding-call failures
mid-turn and degrades to keyword within the same request:

```ts
mode = `${mode}+dense`;             // or +keyword, or +keyword-fallback
```

That `mode` string is returned and surfaced. **Always be able to answer "how did we
retrieve this?"** at runtime.

---

## 5. Layer 4 — The router

`src/lib/intent.ts`. Regex over the message, in priority order, returning:

```ts
{
  intent,           // the job: "esl" | "backlog" | "dev_edit" | …
  sopIds,           // which policy docs are relevant
  preferDocTypes,   // which classes may answer
  needsBoard,       // does this turn need live state?
  entityHint,       // chapterHint — which subject slice
  parkForZoom,      // sensitivity flag → refuse to settle, offer options
  orderReminder,    // workflow invariant injected every turn
  queryText,        // what retrieval should actually search on
}
```

### Why regex and not a classifier

- Zero latency, zero cost, no extra failure mode on the hot path.
- Deterministic and unit-testable — an eval can assert routing without calling a model.
- Order encodes precedence explicitly. "Should I ESL-check before structure?" contains
  "esl" but is a *workflow* question, so that rule sits above the ESL rule and wins.

Reach for a model-based classifier only when regexes start fighting each other. Then keep
the regexes as a fast path.

### Sensitivity as a routing outcome

```ts
const ZOOM_TRIGGERS =
  /\b(final title|subtitle|cover sign-?off|trim size|pricing|foreword author|
     cut(ting)? (a )?chapter|daughter|ex-?partner|legal risk)\b/i;   // one flat regex
```

Certain topics must not be settled by the assistant. Detecting them in the router and
injecting a "offer options, do not decide" instruction is far more reliable than hoping a
general system prompt holds. **Every domain has these.** Enumerate them on day one.

### Conversational carry-over — a bug worth pre-empting

The router originally read one message. When the assistant asked "which chapter?" and the
user replied `"chapter 1"`, that routed to the generic fallback, which preferred policy
docs and retrieved **zero** subject matter — so the assistant asked the user to paste a
chapter that was fully indexed.

Fix: a short, unclassifiable reply inherits the task it answers.

```ts
export function routeIntent(message: string, previousUserMessage?: string | null) {
  const standalone = routeOne(message);
  if (!prev || !isBareFollowUp(message, standalone)) return standalone;   // ≤6 words AND
  const carried = routeOne(`${prev} ${message}`);                        // unclassifiable
  if (carried.intent === "general") return standalone;
  return { ...carried,
    entityHint: standalone.entityHint ?? carried.entityHint,  // newest entity wins
    parkForZoom: standalone.parkForZoom || carried.parkForZoom };
}
```

Two properties that keep it safe: a message the router *can* classify is never overridden,
and the newest named entity beats the one in the question. `queryText` carries the combined
text so retrieval has keywords to score on.

**If you build a router, build carry-over with it.** Any assistant that asks questions will
hit this.

---

## 6. Layer 5 — Retrieval

`retrieveForIntent()` in `src/lib/rag.ts`. Five stages, in order.

### 6.1 Filter by intent

```ts
let candidates = filterByIntent(pool, routed);      // docType or doc-id match
if (candidates.length < 3) candidates = pool;       // never starve the model
```

That fallback is important: an over-narrow filter that returns one chunk is worse than a
loose one. Widen rather than starve.

### 6.2 Narrow by entity, keeping the rules

```ts
if (routed.chapterHint) {
  const subject = narrowed.filter(c => c.docType === "manuscript");
  const rules   = candidates.filter(c => c.docType === "sop" || c.docType === "sop_flagship");
  if (subject.length) candidates = [...rules, ...subject];
}
```

Note what is preserved: naming an entity narrows the *subject*, never the *rules*. You
almost always still need the policy.

### 6.3 Force-include, don't hope

The highest-leverage mechanism here. For jobs that edit the subject matter, similarity
alone is not trusted:

```ts
const needsSubject = ["esl", "dev_edit", "lenses", "subheadings"].includes(routed.intent);
const forced = needsSubject ? forceSubjectSlices(pool, query, routed, 2) : [];
```

`forceSubjectSlices` is a small purpose-built ranker:

- strips process words from the query (`check`, `fix`, `scene`, `chapter`) so only
  distinctive nouns remain;
- **scores bigrams above unigrams** (`+0.7` for `"panic attack"` vs `+0.4` for `panic`), so a
  named scene beats a passing mention of the same word elsewhere;
- expands each seed into a **neighbour window** `[-2,-1,+1,+2]` by `chunkIndex`, refusing to
  cross a chapter boundary — because an edit needs the surrounding paragraphs, not one hit;
- fills **best-scoring seed windows first**, not lowest `chunkIndex`.

That last bullet was a real bug: sorting by index then slicing kept an early weak mention
and dropped the actual scene later in the chapter.

There is also a **hard guarantee** — on an ESL turn, if no flagship policy slice survived
scoring, one is spliced in, evicting the last subject slice if the pack is full:

```ts
if (routed.intent === "esl" && sopCount() === 0) { /* drop last manuscript, unshift SOP 05 */ }
```

**Guarantee the slices a job cannot be done without.** Do not leave them to a score.

### 6.4 Hybrid score

```ts
score = dense * 0.75 + keyword * 0.25 + docIdBoost + flagshipBoost + subjectBoost
//        0.08 when the doc id is one the router asked for
//        0.10 flagship policy on its own intent
//        0.12 subject matter when the job needs grounding
```

Keyword still carries 25% with embeddings present, because exact tokens matter in editorial
work (a proper noun, a typo like `batton`). Boosts are small and additive — they nudge
ranking, they do not override it. Force-include (§6.3) is what overrides.

### 6.5 Cap, dedupe, and cap by type

```ts
const maxSubject = routed.intent === "esl" ? 6 : 4;   // per-type cap
const cap = routed.intent === "esl" ? Math.max(limit, 8) : limit;
```

Per-type caps stop one long document from crowding out the rules. Dedupe on
`${source}:${chunkIndex}`.

---

## 7. Layer 6 — The context pack

Assembled in `buildTurnContext()` (`src/lib/chat.ts`). Four distinct kinds of context, kept
separate on purpose:

```ts
{
  alwaysOn,       // compiled constitution — stable across turns
  boardBlocks,    // live external state
  standardBlock,  // domain rules + deterministic measurements (§8)
  ragBlocks,      // retrieved slices
  orderReminder,  // one-line workflow invariant
  citations,
}
```

### 7.1 Always-on is compiled, not retrieved

A single markdown file is compiled to `tenants/<slug>/always-on/compiled.md` at build time
and prepended every turn: identity, goals, audience, decisions already made, forbidden
moves. It is excluded from retrieval so it never returns as "evidence".

Keeping it stable and first is also what makes prompt caching possible.

### 7.2 Budget in buckets, and say so out loud

`src/lib/token-budget.ts`:

```ts
TOKEN_BUDGET = { target: 18_000, warn: 22_000, hard: 28_000,
                 maxHistoryMessages: 8, maxHistoryMessageChars: 2_500 }
estimateTokens = text.length / 4        // deliberately crude, not billing-accurate
```

Trimming has an explicit priority — **drop subject slices before rules**:

```ts
const dropScore = (b) => /SOP\s*05|sop_flagship/i.test(head) ? 2   // keep
                       : /manuscript|chapter/i.test(head)     ? 0   // drop first
                       : 1;
```

Two implementation notes that came from bugs:

- Drop **in place**. Re-sorting the block array desynchronised the citation list from the
  slices, so the UI cited documents that were no longer in the pack.
- Some providers require history to start with a user turn; trimming can leave a leading
  assistant message. Handle it in the trimmer, with a note.

Every trim is recorded in `trimNotes` and surfaced to the user as a status line —
*"Context light · ~7k · 6 slices, nothing trimmed"*. Users tolerate limits they can see.

### 7.3 Provenance is a feature

Each turn returns citations derived from the slices that actually survived trimming, shown
as *"Read from SOP 05 · Chapter 1. 8 slices, nothing trimmed."*

This is not decoration. It is the fastest debugging tool you will have: when an answer is
wrong, the citation line usually tells you it retrieved the wrong thing, before you open a
log.

---

## 8. Layer 7 — Deterministic analysers

**The single biggest quality lever in this project, and the least standard part of it.**

### 8.1 Never ask a model what a function can measure

Two analysers run *before* the model and put their findings in the prompt as ground truth:

- `esl-scan.ts` — regex scanner over retrieved subject text, producing "MUST FIX" hits with
  spans and severities.
- `chapter-scan.ts` — reads a whole chapter and measures it against the parsed policy:
  word counts, subhead spacing, presence of an epigraph and its attribution, list lengths.

The prompt then constrains the model against them:

```
Use these as your verdicts unless the text contradicts them, and say so by quoting the
passage — never overrule a count.
```

Why this matters more than better prompting: retrieval hands the model 6 of ~25 slices of a
chapter, so a confident "missing" from the model has always really meant "not retrieved".
The analyser reads all 25. **Measurement beats persuasion.**

### 8.2 Reconstruct whole units when the job needs them

Retrieval's job is to find; analysis often needs the whole thing. Because chunks overlap,
reconstruction needs a merge, not a concatenation:

```ts
chunks.filter(sameUnit).sort(byChunkIndex) → mergeOverlappingManuscriptParts(...)
```

`mergeOverlappingManuscriptParts` consumes the longest overlapping prefix between
consecutive parts. Without it, output contains mid-sentence fragments and duplicated
paragraphs — a real, user-reported bug in this project ("it's repeating, not being faithful
to the book").

Also cut a unit at the *next* unit's boundary: overlapping chunks mean a chapter's tail can
carry the next chapter's head, which showed up as chapter 4's "segue" being chapter 5's
opening line.

### 8.3 Three states, used strictly

```
met      — found, and every part of the rule that can be measured passes
missing  — genuinely absent. absence is the only thing asserted outright
unknown  — present but a measurement is off, or the rule turns on judgement
```

`unknown` is a **first-class answer**, not an error. It is what stops fabrication, and the
bias is deliberately towards it: a wrong `missing` sends the user redoing work that was
already fine.

Invariants, enforced by tests: **a `met` always carries evidence; an `unknown` always
carries a reason.** If your analyser cannot say what it saw, it does not get to have an
opinion.

### 8.4 Handle real-document inconsistency, and pin it

Every detection rule in `chapter-scan.ts` exists because a first pass got it wrong on real
input:

| Reality | Naive result | Rule |
|---|---|---|
| `##` subheads in ch 1–3, bold lines after | 8 chapters "have no subheads" | accept both markups |
| attribution same-line (ch 1) vs next-line (ch 2) | attribution counted as a subhead | claim it explicitly |
| takeaways as `* **X:**` vs bare `**X:**` | "3 lines" where there were 6 | count both forms |
| a quote *inside* a paragraph | fabricated `met` | epigraph must be ≥50% of its block |
| overlapping chunks across units | next unit read as this one's ending | cut at the boundary |

**Budget real time for this.** The analyser is not the hard part; the document's
inconsistency with itself is.

### 8.5 Judgement stays with the human

Each finding separates the measurable from the arguable:

```
TL;DR block — NEEDS HIS EYES: "Learnings from chapter 2:" with 6 lines.
  (6 lines, SOP asks for 3–5. Whether each line is concrete and quotable is your call.)
```

Presence and counts are mechanical. Quality is not, and the analyser says so in as many
words. That sentence is what makes users trust the ticks.

---

## 9. Layer 8 — Tools

`src/lib/board-actions.ts`.

### 9.1 Tools propose; they never write

> *"Tools never write — they only build PendingBoardAction for UI Confirm."*

Every mutating tool returns a pending action plus a response that tells the model, in
words, not to claim success:

```ts
return { action, response: { ok: true, pending: true,
  message: `Proposed ${action.label}. Waiting for author Confirm in the UI —
            do not claim it is saved yet.` } };
```

The write happens in a separate confirm endpoint, after the user clicks. Benefits, in order
of how much they matter:

1. A hallucinated tool call costs nothing — it becomes a proposal the user declines.
2. The user always knows what is about to change, in their own vocabulary.
3. The audit trail is real: nothing reached the external store without an explicit yes.

For anything irreversible, or anything a user is paying for, **make this the default.**

### 9.2 Tool descriptions carry the negative cases

The declarations spend more words on when *not* to call than on when to call:

```
"Propose a backlog status change ONLY when the author explicitly asks (mark done /
 in progress / parked / reopen). Do NOT call for 'what's next', burn-down, or other
 read-only questions. Does NOT write yet — Confirm required in the UI."
```

The failure mode you will actually fight is over-calling: the model marks something done
because it *discussed* marking it done. Negative examples in the description, plus a
matching rule in the system prompt, are what stop it.

### 9.3 Let the model omit what it does not know

```
elements: "One entry per element you actually assessed. Omit elements you did not check."
```

Then the handler counts what was skipped and puts it in the human-facing label —
*"Standard audit — 3 met, 1 missing, 1 not checked"*. **Make the honest answer the easy
answer**, and surface the omission rather than defaulting it.

### 9.4 The tool loop is bounded

```ts
for (let i = 0; i < 4; i++) {
  const calls = result.response.functionCalls();
  if (!calls?.length) break;
  // execute → send function responses back → continue
}
```

A fixed small bound, not `while (true)`.

### 9.5 Normalise the model's vocabulary at the edge

Tool payloads keep the model's own wording, and a normaliser maps it onto real ids on the
confirm path:

```ts
normalizeAuditStates(tenant, entries)   // "the body" | "body" | "The Body" → "the-body"
                                        // → { states, unmatched[] }
```

This keeps the tool schema from hardcoding names the domain file owns, and `unmatched` gives
you a place to notice drift instead of silently dropping data.

### 9.6 A deterministic fallback for when tools are skipped

```ts
heuristicPendingFromUserMessage("mark #3 done")   // → the same PendingBoardAction
```

Models sometimes answer in prose instead of calling the tool. When the user's intent is
unambiguous in plain text, a regex produces the identical proposal. Because it is still
only a *proposal*, a false positive is harmless.

---

## 10. Layer 9 — Post-processing the model's output

Prompts are advisory. Post-processing is not. When a behaviour matters, enforce it in code.

Real examples, all in `esl-format.ts` / `why-it-matters.ts`:

- **Praise stripping.** The model kept complimenting the passage even when told not to.
  Prompt tightening failed repeatedly; `stripPassagePraise()` removes it deterministically.
- **Screening tiers.** Model-proposed edits are re-classified: judgement categories are
  demoted from "mechanical fix" to "your call", and any patch that introduces new content
  words is dropped as a rewrite. The model proposes; a function decides what is safe to
  present as mechanical.
- **Structured extraction.** A required labelled line (`**Why it matters:** …`) is parsed
  out server-side into a typed field and removed from the prose, so the UI renders it as a
  block instead of the user hunting for it in a paragraph. The prompt is told the exact
  label to use *because* a parser depends on it.

The pattern: **prompt for a machine-readable marker, then parse it.** Free-form output that
the UI has to guess at is where reliability goes to die.

Rule of thumb: after two failed attempts to fix a behaviour by prompting, stop and write
the function.

---

## 11. Layer 10 — State, writes and idempotency

### External store is the source of truth; local JSON is a cache

Google Sheets here, with `chapter-standard.json` / `board.json` as a short-TTL cache and
offline fallback:

```ts
if (!sheetsConfigured()) return loadLocal(tenant);
try   { const record = rowsToRecord(await pullFromSheets()); saveLocal(record); return record; }
catch { return loadLocal(tenant); }          // never fail the turn on a sync error
```

Writes are **append-only rows**, reduced on read with newest-wins per key. That gives a free
audit log, tolerates concurrent writers, and makes a failed write harmless. Cache writes are
wrapped in try/catch because serverless filesystems are read-only:

```ts
catch (err) { console.warn("[standard] could not write cache:", err); }  // Sheets still worked
```

### A ledger, so the assistant stops repeating itself

Applied fixes are recorded and then **excluded from future scans**:

```ts
scanManuscriptBlocks(blocks, { excludeApplied: (m) => isEslSpanApplied(tenant, m, chapter) })
```

Without this, the assistant re-suggests the same correction forever and looks broken. Any
assistant that recommends actions needs a memory of what was already done.

### Identity matching across surfaces

The user records `"Chapter 2"`; the index knows `"Chapter 2: Walking up to the start line"`.
Naive name matching means the progress counter reads 0 forever, with nothing in the logs.

```ts
export function chapterKey(name: string): string {
  const m = name.match(/chapter\s*(\d+)/i);
  return m ? `ch${Number(m[1])}` : slug(name);
}
```

**Define one canonical key function early** and use it everywhere entities cross a
boundary. This class of bug is silent, which makes it expensive.

---

## 12. Layer 11 — Evaluation

Three tiers, cheapest first. None of them requires a model call to be useful.

### 12.1 Retrieval assertions — `scripts/eval.ts`

Per prompt, assert what the pack contains without generating anything:

```json
{ "id": "esl-panic",
  "prompt": "ESL-check the panic attack scene in Chapter 1.",
  "expectIntent": "esl",
  "mustRetrieve": ["manuscript", "sop_flagship"],
  "mustBoard": false,
  "answerChecks": ["…"] }
```

Fast, deterministic, and it catches the majority of regressions — because most bad answers
are bad retrieval.

### 12.2 Human checklists in the same file

For things only a person can score, the same entry carries an `answerChecks` array that the
harness prints beside each result:

```
□ Says plainly that there is nothing new to fix
□ Does NOT invent patches in order to look useful
□ No praise of the passage (be honest, not nice)
□ Does NOT ask the author to paste the scene
```

Writing the checklist is itself a design act: it forces you to state what a good answer is.

### 12.3 Smoke tests, with invariants and anchors kept apart

An explicit distinction worth adopting:

- **Invariants** hold for any corpus. *A `met` always carries evidence. An unknown entity is
  refused, not guessed. Findings follow the policy's order.*
- **Anchors** are facts about *this* corpus, verified by reading the source. *Chapter 2's
  epigraph is 14 words. Only chapter 3 has a segue.*

Anchors will break when the corpus changes, and the test file says what to do about it:

```
Swapping the manuscript will break them, and that is correct: re-verify against the new
source rather than deleting the assertions.
```

Two hard-won habits: tests that mutate a tracked cache must restore it **byte for byte**
(a save helper that stamps `updatedAt` will dirty your repo on every run), and a smoke that
can silently skip is worse than no smoke — one here quietly passed for weeks after its test
fixture left the corpus.

---

## 13. Failure modes, and what each one taught

Every row happened in this project.

| Symptom | Root cause | Lesson |
|---|---|---|
| "Paste the chapter" for indexed content | terse reply routed to fallback → zero subject slices | routers need conversational carry-over |
| Marks listed ≠ marks highlighted | excerpt capped at 5 paragraphs from first hit | never show a count you cannot show the items for |
| Repeated, fragmented quoted text | overlapping chunks concatenated, not merged | overlap is a debt; pay it at reconstruction |
| Confident "missing" for present content | verdict from 6 of 25 slices | measure whole units deterministically |
| Fabricated `met` on an epigraph | quote *inside* a paragraph matched | require the evidence to dominate its block |
| Praise despite explicit instructions | prompt-only enforcement | post-process what matters |
| Same fix suggested forever | no ledger of applied actions | remember completed work |
| Progress stuck at 0 | `"Chapter 2"` ≠ `"Chapter 2: …"` | one canonical key function |
| Citations naming absent documents | trimmer re-sorted the block array | trim in place |
| Tests passing while asserting nothing | fixture no longer in corpus | assert the fixture exists |
| Gate covering 2 of 23 items | gated the wrong *unit* (rows, not chapters) | model the axis the domain actually progresses along |

That last one is the most expensive kind: the code was correct and the *unit of work* was
wrong. Before building a mechanic, name the thing your domain actually progresses along.

---

## 14. Architectural template

### File layout

```
src/lib/
  tenants.ts          # config + manifest. no domain names anywhere else
  types.ts            # Chunk, ContextPack, PendingAction, DocType
  preprocess.ts       # encoding repair, normalisation, sentence splitting
  chunking.ts         # one strategy per docType
  discover.ts         # manifest → chunks
  <store>.ts          # index read/write, offline-safe
  embeddings.ts       # single contract, batched at ingest
  intent.ts           # router: job → doc types, ids, entity, flags
  rag.ts              # filter → narrow → force → score → cap
  token-budget.ts     # buckets, trim priority, user-facing status
  chat.ts             # pack assembly, contracts, provider call, tool loop
  <domain>-scan.ts    # deterministic analysers (the quality lever)
  <domain>-format.ts  # output screening, extraction, stripping
  <domain>-actions.ts # tool declarations + propose handlers
  <state>.ts          # external store, append-only, cached
  <ledger>.ts         # what is already done

scripts/
  preview-chunks.ts   # look at chunks before ingesting
  build-index.ts      # run in the build, gitignore the output
  compile-prompt.ts   # source → always-on prompt
  eval.ts             # retrieval assertions + human checklists
  smoke-*.ts          # invariants + corpus anchors
  report-*.ts         # print analyser output over the whole corpus
```

### Build order

1. **Corpus and manifest.** Types before content. Decide what is policy, what is subject
   matter, what is a worked example, and what is always-on.
2. **Preprocess + chunk + `preview-chunks`.** Read twenty chunks with your own eyes. Do not
   proceed until they look like semantic units.
3. **Index, with a keyword-only path.** Get retrieval working before embeddings exist. If it
   is useless without vectors, the corpus or the chunking is wrong.
4. **Router.** Enumerate jobs, the doc types each needs, and your sensitive topics. Add
   carry-over now.
5. **Retrieval, with force-include.** Name the slices each job cannot be done without and
   guarantee them.
6. **Pack + budget + citations.** Surface the status line from the start; you will use it to
   debug everything else.
7. **`eval.ts` with retrieval assertions.** Before touching prompts. Most bad answers are
   bad retrieval.
8. **Response contracts per intent**, then the always-on prompt.
9. **Deterministic analysers.** Measure whatever a function can measure. Expect the corpus
   to be inconsistent with itself.
10. **Tools, propose-only,** plus the confirm endpoint and a heuristic fallback.
11. **Post-processing** for behaviours that prompting failed to fix twice.
12. **Ledger and idempotency.**

### Porting map — worked example

Say the next project is a **support desk over product docs, policies and a ticket tracker**:

| Here | There |
|---|---|
| SOPs (policy) | refund/warranty/escalation policies — parse them, cite by section |
| SOP 05 (flagship) | the refund policy: guaranteed a slice on any refund-intent turn |
| Manuscript (subject) | product docs + the ticket thread; force-include on any ticket job |
| Templates | canned response templates — chunk whole, never split |
| `chapterHint` | `ticketId` / `productId` / `orderId` — one canonical key function |
| Backlog board | the ticket tracker; append-only writes, newest wins |
| ESL scanner | a policy lint: is the order in warranty? is the amount over the auto-approve limit? |
| Chapter standard | the resolution checklist a closed ticket must satisfy |
| `propose_backlog_update` | `propose_refund`, `propose_escalation` — proposals, never writes |
| ESL ledger | actions already taken on this ticket, so nothing is offered twice |
| Park-for-Zoom | legal threats, chargebacks, safety issues → hand to a human, never settle |
| Chapter progress | tickets meeting the checklist, per week |

The shapes transfer unchanged. What you re-derive per domain is: the job list, the sensitive
topics, the unit of progress, and which measurements a function can make instead of a model.

---

## 15. Anti-patterns

- **Top-k over everything.** Filter by job first, or the rules get crowded out by subject
  matter that merely sounds relevant.
- **One chunker for all documents.** A shredded template is worse than no template.
- **Domain rules transcribed into code.** Two sources of truth; the code wins silently.
- **Tools that write.** One hallucinated call and you are apologising to a user.
- **Prompting for something a function can guarantee.** After two failures, write the
  function.
- **`unknown` treated as failure.** Removing it is how a system starts fabricating.
- **Retrieval you cannot explain at runtime.** Keep the `mode` string and the citation line.
- **Hidden trimming.** Users forgive limits they can see and distrust answers that quietly
  lost their evidence.
- **Silent no-ops.** A mechanic that finds nothing and says nothing looks identical to one
  that is broken.
- **Building the mechanic before naming the unit.** Correct code on the wrong axis is the
  most expensive mistake in this list.
