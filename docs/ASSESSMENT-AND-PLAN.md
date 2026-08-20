# Acme Scoping Assistant — functional audit and architecture plan

**Date:** 2026-08-20
**Method:** code read of the whole turn path + 28 realistic utterances run through the live pipeline
(Sheets, Firestore and the real index all connected) via `scripts/probe_intents.py`, plus the full
test suite.
**Companion docs:** `docs/ASSESSMENT-HANDOFF.md` (what the system is), `docs/ARCHITECTURE-AUDIT.md`
(status board), `README.md`.

---

## 0. Headline

The integrations are healthy and the deterministic tools are correct. **The failure is the layer
that decides which tool to use.** One regex classifier picks exactly one capability per turn,
*before* anything has been looked up, and its choice is final. When it picks wrong the user does not
get a degraded answer — they get a confident, fluent, wrong one.

Two numbers made the point at audit time:

- **354 tests pass.** Every one of them asserted the regexes we wrote.
- **11 of 28 realistic utterances landed on the wrong capability**, including phrases used as
  canonical examples in our own documentation.

The tests were green because they tested the implementation, not the product.

**Status after plan/execute/compose (2026-08-20):** golden harness `evals/turns.json` is
**51/51 (100%)**, **0/9 critical failures**, on the rules planner with live catalog/Sheet.
The previous criticals — translation answered as free-of-charge (F1), “what's left for london”
denied as a missing capability (F2), roster unused (F3), inventory phrasing unreachable (F4/F5) —
now reach the right lookup. README and `docs/ARCHITECTURE-AUDIT.md` describe the current path.

---

## 1. Functional audit

Legend: **works** = correct and reachable by normal phrasing. **reachable** = correct but only if
the user phrases it our way. **broken** = wrong answer or dead end.

| Capability | Where | State | Evidence |
|---|---|---|---|
| Handover (safety, legal, press, GDPR, refunds, discounts) | `router.HANDOVER_TOPICS` | **works** | injury and journalist probes both pre-empted correctly |
| Scope verdict lookup (Y / N / Local / On demand) | `resolver.py` + corpus | **works, with one wrong-verdict class** | see F1 |
| Full catalog list | `tools/catalog.py` | **reachable** | needs the literal word "services" — see F5 |
| Filtered list (by status / section) | `tools/catalog.py` | **broken in practice** | the code supports it; no phrasing users try reaches it — F4, F5 |
| Budget: single branch, country rollup, all branches, month, sticky follow-ups | `tools/budget.py` + Sheets | **works once you're in the tool**; **entry is broken** | F2 |
| Quote (tier → price, over-budget flag, Variable abort) | `tools/quote.py` + `Pricing_tiers` | **works** | 350 GBP returned live for billboards / photoshoots |
| Yes → email AM/CM via Resend | `tools/flows.py`, `store/mail.py` | **works, but hard to reach** | F7, F8 |
| Country prompt before send | `flows._ask_country` | **works** | |
| Clarifying question on disagreeing candidates | `resolver` AMBIGUOUS | **works when it fires** | does not fire on F1 |
| Hybrid retrieval (keyword + dense 768d) | `retriever`, `embeddings` | **works** | `embed.connected dimensions=768` in every scoping turn |
| Firestore + JSONL audit dual-write | `store/audit.py` | **works**, but not diagnostic | F11 |
| Roster from the `Roster` tab | `store/roster.py` | **loaded and never used** | F3, F13 |
| Semantic inventory detector | `intent_semantics.py` | **disabled dead code** | F13 |
| Gemini wording | `llm.py` + `context.py` | **works, on the wrong turns** | F9 |

### Findings

**F1 — Wrong verdict on the exact class we care most about (critical).**
`"do you handle translating our web pages"` resolves to **Web pages (Copywriting), status Y — free
of charge**. The real request is translation, and `Translation & localisation` is **Local**. So an
Account Manager is told central marketing will do it for free when the local team owns it. The
resolver's own docstring cites this sentence as the case that *should* come back AMBIGUOUS; with the
current corpus it scores Web pages at 6.22 and never considers the rival, because the alias match
needs the alias words contiguous while keyword scoring rewards the item whose *name* is in the
sentence. Free-vs-chargeable is the highest-cost error in this product, and there is no guard that
notices two named candidates disagreeing.

**F2 — The canonical budget phrase does not reach the budget tool (critical).**
`"what's left for london"` → intent SCOPING → no service matched → *"I don't have that capability."*
That sentence is the example in `ASSESSMENT-HANDOFF.md` §12 and in the README. `_BUDGET_RE` wants an
explicit money word, or `left` followed within 32 characters by `branch|month|budget`. Once you do
get into the tool, sticky sessions work well: `"and manchester?"` and bare country rollups chain
correctly. The tool is good; the door is locked.

**F3 — Confident wrong answer to a directory question (high).**
`"who is my account manager"` → keyword match on **Attendance (travel, accommodation, food)**
[3.54] → on-demand verdict, price path, and a *pending email action* recorded in Firestore as
`email_pending`. Meanwhile the `Roster` tab is loaded into the pipeline at startup and never read by
any code path. The answer to that question is sitting in memory, unused.

**F4 — The assistant denies capabilities it has (high).**
All three of these land in SCOPING → UNKNOWN → *"I don't have that capability — this assistant only
covers central marketing scope, budget checks, and quotes"*:

- `"what else can you do for me"` (matched `can you` as scoping framing)
- `"which things are free and which cost money"`
- `"what do I get for free"`

The last two are precisely the status-filtered list that `list_services()` already implements. This
is the behaviour you described as "it forgets what it can do" — it is literal: the copy says it has
no capability while holding the answer.

**F5 — Section listing is unreachable (high).**
`"show me everything under events"` → resolves to **Planning (Events)** and answers about that one
item. `_LIST_RE` requires the word `services`/`offerings`/`catalogue`, so naming a section is not
enough.

**F6 — One capability per turn, so compound questions lose half (medium-high).**
`"do we have money for a photoshoot in basingstoke"` answers *either* the price (fresh session) *or*
the budget (sticky session), never both — the two facts the question actually needs. Nothing in the
design can run two tools for one message.

**F7 — Explicit tool requests dead-end (medium-high).**
`"email my AM about the merch request"` matches `_ACTION_RE` before any scope resolution, so it
returns *"I can't send anything yet. Tell me which service this is about"* — about a message that
names the service. No pending action is set, so a following `"yes"` is meaningless.

**F8 — Bare confirmations outside a CTA are hostile (medium).**
`"yes"` / `"no thanks"` with no pending action → UNKNOWN → *"I don't have that capability."*

**F9 — The model writes the turns that matter least (medium, and it explains the "same answer
every time" feeling).**
`_tool_or_flow` returns a template for every IN_SCOPE and QUOTE_REQUIRED resolution, and
`_model_for` blocks the model for those statuses anyway. Add the CAPABILITIES / BUDGET / ACTION /
GREETING skip set and Gemini only writes when the outcome is Local, Out of scope, ambiguous or
unknown. So: the two most common, most valuable outcomes are byte-identical strings every time, the
tone-of-voice document barely affects production output, and the facts we work hardest to fetch
(catalog list, budget numbers, quote) are never shown to the model at all.

**F10 — Budget numbers leak into scoping turns (medium).**
`_flow_in_scope` calls `answer_budget(question, ...)` on any in-scope turn, so any branch name in
the sentence attaches a cap/spent/remaining line to a question that was not about money.

**F11 — The audit cannot explain a bad answer (medium).**
The turn payload records `intent`, `status`, `source`, `outcome` — not which tools ran, which slots
were extracted, or which candidates were considered. When an AM reports a bad reply, Firestore
cannot tell you why, so every diagnosis is a local re-run.
Also `email_pending` is written whenever a CTA is offered, including on wrong-verdict turns like F3,
which inflates the funnel numbers you would use to judge the product.

**F12 — No closed loop (structural).**
There is no eval set. Every incident so far was fixed by widening a regex, which is why the same
class of bug keeps returning in a new phrasing.

**F13 — Dead capability surface.**
`USE_SEMANTIC_INVENTORY` is off and unreferenced in practice; the roster is loaded and unqueried.
Both cost maintenance and neither answers anything.

---

## 2. Why the semantic detector was in the router — and what that really tells us

Because the router is the only place in this design where behaviour is chosen. Intent selects the
branch, the branch selects the tool, and nothing downstream can revisit the decision. So to
recognise "the user wants the inventory" you had exactly one place to put it: the classifier.

Two things then made a near-miss catastrophic rather than merely wrong:

1. **`CAPABILITIES` is overloaded.** It means both "dump the whole catalog" and "recite the static
   *what I can do* blurb". A semantic hit without a regex hit took the second meaning, so every
   paraphrase returned the same canned paragraph.
2. **A classifier's confidence gates the tools.** Inventory exemplars scored ~0.54 against a budget
   threshold of 0.55. A near-tie between two capabilities silently skipped the real tools instead of
   looking anything up.

So the lesson is not "embeddings are dangerous". It is that **a single up-front classifier whose
choice is irreversible converts every borderline case into a confident wrong answer.** Regexes have
the identical failure mode — F1 through F8 are all that same shape, and they were shipped by
patterns, not by a model.

Your instinct is right, and this is the part worth stating plainly: the facts should reach the model
so it can reason about *the question in front of it*, while verdicts and numbers stay lookups. Today
we do the opposite — we decide everything up front and hand the model only the turns where we have
nothing to say.

---

## 3. Root causes

| # | Cause | Symptoms |
|---|---|---|
| RC1 | One classifier decides both *what to look up* and *what to say*, before any lookup | F1–F5, F7, F8 |
| RC2 | Exactly one capability per turn | F6 |
| RC3 | Tool facts never reach the model on the paths that carry facts | F9, F10 |
| RC4 | No evals; fixes are per-phrase regex patches | F12, and the recurrence you feel |

---

## 4. Options

### Option A — Harden the rules
Patch the regexes from §1, reorder ACTION after resolution, make bare yes/no benign.
**Cost:** ~half a day. **Keeps:** RC1–RC4. **Prediction:** buys a week, then the next unseen
phrasing reopens the same class of bug. Necessary as first aid, insufficient as an answer.

### Option B — Plan → execute → compose (recommended)
Two narrowly constrained Gemini calls around the **unchanged** deterministic tools.

```
message
  → safety gates (rules)            handover, pending Yes/No — never model-decided
  → PLAN call (structured JSON)     which capabilities + which slots. No prose, no verdicts.
  → execute tools (deterministic)   scope lookup, budget, quote, catalog list, roster, mail draft
                                    → may run several; produces a FactPack
  → COMPOSE call                    FactPack + history + tone → the reply
  → guard + fallback                numbers/verdicts not in the pack ⇒ use composer text
```

- The planner emits a validated schema: `capabilities: [scope|budget|quote|list|roster|mail_confirm]`
  plus slots (`service_phrase`, `branch`, `country`, `month`, `status_filter`, `section`). It cannot
  emit an answer, a price, or a verdict.
- Verdicts stay `resolver` lookups; prices stay rate card + Sheet; budget stays the Sheet. Injection
  can at worst aim the lookup at the wrong service, which the reply states out loud ("I read this as
  Merch — say the word if you meant something else").
- Compound questions work, because the planner may request two capabilities (F6).
- A misplan degrades into "I'm not sure which service you mean, here's what I can check" instead of
  a canned confident answer, because the compose call is *given the empty fact set* and told to ask.
- The two most common outcomes finally get real wording, and the tone doc starts mattering (F9).

**Cost:** ~1 to 1.5 weeks including evals. **Latency:** two `gemini-2.5-flash` calls, thinking off
≈ 1.5–3 s per turn against ~1 s today. **Risk:** planner drift — contained by schema validation,
the eval gate, and the composer fallback that already exists.

### Option C — Full function-calling agent
Give Gemini the tools and let it loop until it has what it needs.
**Upside:** most flexible; handles asks nobody anticipated. **Downside:** nondeterministic tool
sequences, 2–5 model calls per turn, harder to test, and no golden trace to assert in CI.
**Recommendation:** the natural evolution *after* B, because B produces exactly the artefacts C needs
— stable tool contracts and an eval set. Doing it first means debugging a loop with no ruler.

### Option D — Rules fast path, planner on low confidence
Keep regexes for unambiguous hits; call the planner only when nothing matches confidently.
**Upside:** cheapest, lowest latency, smallest diff. **Downside:** two intent systems to reason
about, and the confident-but-wrong cases (F1, F3, F5) never reach the planner because the rules
*were* confident. Best used as a **stage of B**, not a destination.

---

## 5. Recommended plan

Phases are ordered so that measurement comes before the rewrite. P0 and P1 are worth doing even if
you choose Option A and stop.

**P0 — First aid (half a day).** Fix F2, F4, F5, F7, F8: budget entry phrasings, capability
paraphrases routed to the real list, section-only listing, ACTION resolved before stubbing, benign
bare yes/no. Merge the static "what I can do" blurb into the catalog list so `CAPABILITIES` has one
meaning (removes the §2 failure mode structurally).

**P1 — A ruler (1–2 days).** `evals/turns.yaml`: ~80 utterances in the language AMs actually use →
expected capabilities, expected must / must-not strings. `python -m scripts.eval_turns` prints a
misroute rate; CI fails on regression. Seed it from `scripts/probe_intents.py` (already written and
already catching 11 of these). Add a `trace` block to the audit payload — tools run, slots
extracted, candidates considered — so Firestore can explain a bad turn (F11).

**P2 — Planner (2–4 days).** Structured-output plan call replaces the intent regexes for everything
except the safety gates and pending confirmations. Multi-capability turns. Sticky budget stays, as a
slot default rather than a route.

**P3 — FactPack + one compose call (2–3 days).** All statuses, budget, quote and list go through the
model with the facts pinned, and the deterministic composer stays as the fallback. Add the output
guard: any currency figure or verdict word not present in the pack ⇒ discard the generation and use
the composer text, logged as a violation.

**P4 — Correctness fixes the planner cannot solve (1–2 days).** F1: build candidates from the union
of name and alias matches, and force the clarifying question whenever two *named* candidates
disagree. F3: expose the roster as a tool so "who is my AM" is answered from the Sheet. F10: only
attach budget to a scoping turn when the planner asked for it.

**P5 — Optional (later).** Revisit Option C for open-ended asks, once P1 can prove it does no harm.

### Guardrails that must survive every phase
1. Verdicts come from the catalog lookup. The model is never asked to judge scope.
2. Prices come from the rate card / `Pricing_tiers`; budget from the Sheet. Never generated.
3. Handover topics pre-empt everything, by rule.
4. Mail sends only after an explicit Yes, against a pending action created by a tool.
5. Every model-written turn falls back to the deterministic composer on failure, empty output, or a
   guard violation.
6. No phase ships while `scripts.eval_turns` is red.

---

## 6. What I would not change

The parts under attack in this document are the routing layer and the template layer. The rest is
sound and should be left alone: the corpus-as-truth model, `Status` → verdict mapping, the resolver's
AGREED / AMBIGUOUS distinction, read-only Sheets, the Resend confirm-then-send flow, the dual-write
audit, and the composer as a real fallback rather than an error page. Option B keeps all of it —
it changes who decides *which* of them to use, and how the result is worded.
