# Remediation: the 26 Aug 2026 golden-question round

**Status board for the fixes.** Root-cause analysis behind it: the failures are six mechanisms,
not twenty-five bugs. Keep this honest — a task moves to Done only when its `knownFailure` marker
has been removed from the eval file and the suite is green without it.

## The shape of the problem

The retrieval layer was never connected to the decision layer. `InMemoryRetriever` is a hybrid
engine with IDF weighting, bigrams, name coverage and cosine blending; `ScopeResolver` owns the
verdict and consumes only the lexical half of it, with no query vector, in any environment. Most
of what follows is that one gap showing up in different places.

| ID | Root cause | Where it shows |
|---|---|---|
| RC-1 | The stemmer strips `-ing` but never restores the silent `-e`, so a verb never matches its own gerund | #25 |
| RC-2 | A model-authored `month` slot becomes a spreadsheet column key with no validation | #18, #16, #17 |
| RC-3 | The disagreement guard only considers rivals whose names contain a rare word | #25, #3 |
| RC-4 | Candidate admission constants admit near-ties, and discard a correct rank-1 answer when the field is crowded | #1, #6, #19, #22, #24 |
| RC-5 | A single common token can carry a verdict via name coverage alone | #21 |
| RC-6 | The guard is a regex phrasebook and the model paraphrases | #21, systemic |

## Phase 0 — a harness that can fail · **done**

| ID | Task | Status |
|---|---|---|
| T1 | `expectItem` / `expectVerdict` / `expectOutcome` on the turn eval; backfill the assertion-free cases | Done |
| T2 | Add the 25 golden questions as cases | Done |
| T3 | `--mode {rules,planner,deployed}`; run the deployed configuration | Done |
| T4 | Triage the three red harnesses | Done |
| T5 | CI on push, plus a nightly deployed run | Done |
| T6 | Clear the standing mypy errors so type checking can gate | Done |

Before: 51 cases, 39% asserting only which capability ran, three of four harnesses red, no CI.
After: 74 cases, every scope case asserting an item or a verdict, all four harnesses gating, CI
green with the ten real defects recorded and visible.

Two decisions taken here are worth knowing about:

- **`knownFailure` markers.** A defect that is understood and scheduled is recorded in the eval
  file with the task that will fix it. Marked cases run, print and count, but do not gate. The
  alternative was a suite that stayed red for a fortnight, which is how a signal stops being
  read. A marked case that starts passing is reported so the marker is removed.
- **`Intent.OUT_OF_REMIT`.** Employment matters are refused outright rather than handed to a
  named HR contact. The router, the unit tests and the routing eval each described different
  behaviour here; this settles it. See the README's handover section.

## Phase 1 — the two confidently-wrong answers · **done**

| ID | Task | Root cause | Status |
|---|---|---|---|
| T7 | `canonical_month` returns `""` for anything that is not one of the twelve months | RC-2 | Done |
| T8 | Resolve relative months ("this month", "last month") through the fiscal calendar | RC-2 | Done |
| T9 | Never persist an invalid slot into sticky state | RC-2 | Done |
| T10 | A lone matched term must be distinctive as well as high-coverage | RC-5 | Done |

**#18 and #21 both answer correctly now, in the deployed configuration.** "What's the total UK
marketing budget for this month?" returns £2,500 — the planner still emits `month="this month"`,
and that phrase now resolves through the fiscal calendar instead of becoming the column key
`"Thi"`. "Can you build us a new website from scratch?" says it cannot find a matching service
instead of promising it free of charge.

T7 also closed a latent bug of its own: `canonical_month` matched on the first three characters,
so "marketing" would have read as March and "maybe" as May. It is now an exact table.

T10 was safe by measurement rather than by hope: document frequency separates the one-word
requests that must keep working (merch 1, leaflet 1, qr 1, billboard 2) from the noise word that
caused #21 (website 13, video 11, email 12). It also fixed #19 as a side effect — removing weak
single-token candidates left nothing confident enough to name, which is the correct answer for a
sponsorship request the catalogue does not cover.

Two eval cases were wrong rather than the code, and were corrected: a turn that identifies no
service runs `clarify`, not `scope`; and asserting the literal string "United Kingdom" tested the
composer's choice of wording rather than the figure, when the country is already guaranteed by
the tool and by `guard._wrong_country`.

## Phase 2 — recall · **done**

| ID | Task | Root cause | Status |
|---|---|---|---|
| T11 | Baseline the retrieval and resolver evals before touching `stem()` | — | Done |
| T12 | Adopt Snowball in place of the hand-written suffix rules | RC-1 | Done |
| T13 | Assert every gerund in an item name shares a stem with the verb people type | RC-1 | Done |

**Option B, as decided.** Snowball is pure Python with no data files, so the image is unchanged.
The synonym table stayed, as expected: photo/photography is an abbreviation rather than an
inflection and no stemmer unifies it.

Measured against the baseline taken before the change:

| | Before | After |
|---|---|---|
| Retrieval, rank 1 | 18/23 (78%) | 18/23 (78%) |
| Retrieval, in top 5 | 25/25 | 25/25 |
| Resolver, **wrong verdicts** | 1/25 | **1/25** |
| Resolver, answered well | 18/25 (72%) | **20/25 (80%)** |
| Resolver, asked when it could have answered | 6/25 | **4/25** |
| Turn eval | 66/74, 8 recorded | 66/74, 8 recorded |

**The safety number did not move, which was the condition for making this change at all.**

Two things worth knowing before Phase 4:

- **Better recall shifts pressure onto admission.** Items that used to score below the confidence
  floor are now real candidates, and the current constants turn some of those into clarifying
  questions. #25 moved from "in scope, free of charge" — a wrong verdict on a Local item — to
  asking, because Content scheduling climbed from rank 9 to rank 2. Site visits became the rank-1
  hit for the golden phrasing and is now questioned rather than answered, for the same reason.
  Both are safe, both are one admission constant from correct, and both are recorded against T20.
  This is the trade the plan predicted: fix these separately and they pass failures back and forth.
- **"up" joined the stopwords.** As a phrasal particle it attaches to whatever verb precedes it,
  so "can we **set up** a regular call about occupancy" matched *Monthly marketing catch ups* and
  outscored the item the sentence actually names. It costs that item some hint weight; it is still
  reached by "catch", "monthly" and "group", and a test asserts so.

T13 is the test that would have caught the original defect at authoring time: it fails on six of
the eleven gerund/verb pairs under the old stemmer, `scheduling`/`schedule` among them. A guard
keeps its table in sync with the corpus, so a new gerund-named service fails the build until
somebody writes down the verb people would use for it.

## Phase 3 — connect the RAG to the decision · **done**

| ID | Task | Status |
|---|---|---|
| T14 | Calibrated 0–1 confidence on `ScoredChunk`; the resolver's absolute threshold read off it | Done |
| T15 | Ship vectors to production | Done — needs one deploy to take effect |
| T16 | Pass the query vector into the resolver's retrieval | Done |
| T17 | Resolve the GCS index-at-boot path | Done — deleted |

**The dense half of the RAG now has a vote on the verdict.** It never did before, in any
environment: `ScopeResolver` called `retrieve()` without a query vector, so embeddings only ever
shaped the evidence pack the composer saw.

Measured with the rules planner and deterministic wording, so the numbers isolate retrieval:

| | Keyword only | Keyword + dense |
|---|---|---|
| Resolver — **wrong verdicts** | 1/25 | **1/25** |
| Resolver — answered well | 20/25 (80%) | **21/25 (84%)** |
| Resolver — asked when it could have answered | 4/25 | **3/25** |
| Turn eval | 66/74 | **68/74** |

The two turn cases it fixes are `clarify-no-invented-price` — a vague pricing question that was
being answered "included, free of charge" — and `golden-15-site-visit`, the case the stemmer had
knocked from answering into asking. No case regressed.

### T14 before T16, and why it was not optional

Blended scoring is `0.75 × cosine + 0.25 × keyword`, and cosine cannot exceed 1. The resolver's
old floor was a raw score of 1.6, which with vectors on would have required the keyword half
alone to reach 3.4. Measured over the 25 retrieval prompts with vectors enabled, **3 of 25 would
have had no hit clear that floor at all** — answered "I couldn't tell which service you mean" —
and rival admission would have been distorted for the rest. Under the calibrated floor: 0 of 25.

*(An earlier estimate in the audit put this at "nearly everything". That came from four
hand-picked probes; the measured figure across the eval set is 12% of prompts going dead. Still a
regression that would have been read as "embeddings made it worse", which is the opposite of what
the ranking shows.)*

Two properties make the calibration safe rather than merely plausible:

- **Keyword confidence is `score / (score + 1.6)`**, so `confidence >= 0.5` accepts exactly the
  hits `score >= 1.6` accepted. Introducing the scale changed no behaviour in keyword-only mode,
  and a test asserts the two constants have not drifted apart.
- **Dense confidence is calibrated on measurement, not on intuition.** Raw cosine is not a
  confidence: over the eval prompts the *expected* item scores 0.650–0.794 while every other item
  scores 0.479–0.740. An unrelated service sits at 0.57, which used directly would read as 57%
  sure. The classes separate at about 0.657, and the anchors put that at 0.5.

`RIVAL_FLOOR` deliberately still compares raw scores. It is a *relative* judgement between two
hits scored the same way in one query, so it needs no absolute scale — only that both sides are
measured alike. Its distribution does change when cosines compress the spread, which is a retune
and belongs to T20.

### A determinism bug this exposed

Wiring the embedder into the resolver meant `eval_turns` embedded whenever a Gemini key happened
to be configured — so a laptop and CI scored the same commit differently and neither knew. Dense
retrieval is now a settings flag (`use_dense_retrieval`) tied to the eval mode rather than to
whether a key is lying around. `rules` is offline for real; CI gates on it.

### T15: the index is built where the key is

`gcloud run deploy --source .` builds in Cloud Build, which has no Gemini key — the mechanical
reason production shipped keyword-only while every local check ran against vectors. Rather than
add a Cloud Build secret to a deploy that works, `deploy_cloud_run.ps1` now builds the index
before uploading and ships it in the image, so what production runs is byte-identical to what the
deployer tested. Without a key it falls back to keyword-only, and a hand-run `docker build` still
builds its own.

**Not yet in production.** It takes effect on the next deploy; `/api/health` should then report
`embeddings: true`.

### T17: deleted rather than built

`KNOWLEDGE_BUCKET`, `KNOWLEDGE_INDEX_OBJECT` and `google-cloud-storage` described a
load-the-index-from-a-bucket path that no code ever read. With T15 shipping vectors in the image,
what the bucket would add is refreshing the corpus without a redeploy — and this corpus is a
service catalogue that changes rarely. The dependency is gone; **delete the two `KNOWLEDGE_*`
lines from your local `.env`**, which is the only place they still exist.

## Phase 4 — judgement

| ID | Task | Root cause | Status |
|---|---|---|---|
| T18 | One notion of "close enough to be a real alternative", used by retrieval and the guard | RC-3 | Done |
| T19 | The disagreement guard requires corroboration, not just a shared word | RC-3 | Done |
| T20 | Retune admission; stop discarding a correct rank-1 | RC-4 | Done |
| T21 | Composer returns a structured verdict claim; code compares it to the fact pack | RC-6 | To do |

**In the deployed configuration the turn eval goes 68/74 → 72/74.** #03, #22, #24 and **#25**
are fixed. #25 — the worst defect of the golden round — now resolves outright to Content
scheduling, Local, instead of promising that central marketing does it free of charge.

Three changes, each measured:

- **Ranking moved onto confidence.** Score and confidence had diverged into two orderings inside
  one decision, and the resolver took its leader from one while filtering on the other. For "who
  looks after our instagram posts" the top-scoring item was Campaign wrap-ups — an analytics
  report — at 0.23 confidence. In keyword-only mode the two orderings are identical, so this
  changed nothing there.
- **A crowded field is trimmed, not discarded.** Returning UNKNOWN past four candidates was
  throwing the leader away with the noise; #24 put Graphics for screens first, with a name the
  request covers entirely, and answered "I couldn't tell which service you mean". Whether a
  request was too vague is a question about confidence, which is now measured directly.
- **`RIVAL_FLOOR` is 0.85 and compares confidence.** Swept against the whole suite with
  embeddings on: 0.50–0.60 give 66/74, 0.70–0.80 give 69/74, 0.85 upwards give 70/74. Confidence
  saturates where score does not, so 0.85 admits roughly what 0.5 admitted on the old scale.

### The guard now needs corroboration, and only semantics can give it

`_check_for_disagreement` promotes a rival the request named. Naming turned out to be necessary
but not sufficient: "Heart Radio" contains the word radio, which was enough to raise *Radio ads*
— a chargeable design item — against a plainly correct answer.

What separates that from the translation case is not the word but how convincing retrieval found
the rival. Measured across four cases where the answer is known:

| Request | Rival, as a fraction of the leader's confidence | | |
|---|---|---|---|
| | **keyword only** | **with embeddings** | should ask? |
| translating our web pages | 0.89 | 0.96 | yes |
| web page copy translated to French | 0.77 | 0.94 | yes |
| landlord wants signage, who pays | 0.99 | 0.88 | yes |
| Heart Radio campaign wrap-up | **0.79** | **0.69** | **no** |

With embeddings the two populations separate cleanly and `RIVAL_FLOOR` divides them. **Without
them they overlap** — 0.77 for a genuine second reading against 0.79 for a coincidence — and no
threshold exists that could separate them. Telling a real alternative from a shared word is a
question about meaning, and word counts cannot answer it.

So the corroboration check applies only when the hits are semantic. Offline it falls back to
naming alone, which asks more often than it needs to — the safe direction, and the reason this
degrades rather than guesses. Nine cases now pass in the deployed configuration and are recorded
as known failures in the offline one; each marker says so.

### Where the tuning stopped

The last two failures are **corpus gaps, not ranking defects**, and no threshold fixes either:

- **`golden-06`** — the item is named "Marketing + GMs calls - 121", and no phrasing a person uses
  reaches it. `1:1` tokenises to `('1','1')`; `one to one` tokenises to nothing at all, because
  "one" is a stopword.
- **`scope-local-owner`** — **"Instagram" appears in zero documents**, as do Twitter and YouTube.
  The organic social items never name the platforms they cover, so the request has no distinctive
  word to match and the resolver correctly declines rather than guessing.

Both are cheap to fix on the Scope sheet and impossible to fix in the ranking. Chasing them with
constants would have been overfitting to nine sentences.

### Settled: ask, when a request genuinely names two disagreeing services

Product ruling, 26 Aug: ask. Worst case the user reiterates. The eval encodes it, and the
corroboration check above exists to make sure it is a *genuine* second reading being put to them
rather than a word that happened to appear twice in the corpus.

## Phase 5 — data and honesty

| ID | Task | Status |
|---|---|---|
| T22 | Rename the Copywriting item "Paid ads" so it stops colliding with the Paid ads section | Needs the Scope sheet owner |
| T25 | Declare `1:1`, `one to one`, `one-to-one` as aliases on the two `- 121` call items | Needs the Scope sheet owner |
| T26 | Name the platforms — Instagram, Twitter/X, YouTube, Facebook, TikTok — as aliases on the Organic social items | Needs the Scope sheet owner |
| T23 | Fix the citation line on the catalog-list path — "No supporting documents retrieved" misreports a catalog answer | To do |
| T24 | Keep build artefacts newer than their sources | Index done; `widget/dist` still stale |

## Waiting on a product ruling

| Question | Blocks | Why it matters |
|---|---|---|
| ~~#9 — ask, or resolve to the more specific one?~~ | — | **Settled 26 Aug: ask.** Encoded in the eval; the guard's corroboration check makes sure it is a genuine second reading. |
| #16/#17 — should login require a branch rather than offering it optionally? | — | Removes a class of "which branch?" round-trips for one field at sign-in. The plumbing already exists. |
| #23 — track the 4–5/month ad-hoc email allowance, or quote every time? | — | Needs a per-branch running total the sheet does not expose, and the sheet is read-only by design. |
| #7 — wording implied a correct out-of-scope verdict might be quotable | — | Prose fix in the corpus or the composer brief, not code. |
