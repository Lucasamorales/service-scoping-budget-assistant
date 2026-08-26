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

## Phase 2 — recall

| ID | Task | Root cause | Status |
|---|---|---|---|
| T11 | Baseline the retrieval and resolver evals before touching `stem()` | — | Done (2 known failures recorded) |
| T12 | Adopt a real stemmer (Snowball/Porter) in place of the hand-written suffix rules | RC-1 | To do |
| T13 | Assert every catalog item is reachable by the plain verb form of its own name | RC-1 | To do |

**Decided: option B, a real stemmer.** The failing pairs share no single rule — `scheduling`
needs an `-e` restored, `planning` a doubled consonant collapsed, `management` a `-ment` rule,
`localisation` something else again. Hand-written rules mean one new rule per production
discovery, and this bug class is found by users rather than by tests. The synonym table stays
either way: ad/advert are abbreviations, not inflections, and no stemmer handles them.

## Phase 3 — connect the RAG to the decision

| ID | Task | Root cause | Status |
|---|---|---|---|
| T14 | Calibrated 0–1 confidence on `ScoredChunk`; resolver thresholds re-expressed in it | — | To do |
| T15 | Ship vectors to production: Cloud Build secret + `--embed` in the image | — | To do |
| T16 | Pass the query vector into the resolver's retrieval | — | **Blocked on T14** |
| T17 | Implement the GCS index-at-boot path, or delete the config that promises it | — | To do |

**T16 must not land before T14.** Blended scoring is `0.75 × cosine + 0.25 × keyword` and cosine
caps at 1.0, so a threshold of 1.6 needs the keyword half alone to reach 3.4. Measured on four
probe questions, the number of hits clearing the resolver's floor goes 2→0, 4→0, 4→2 and 4→1 the
moment vectors are switched on. Shipped as one change it reads as a catastrophic regression, and
the conclusion drawn would be that embeddings made things worse — the opposite of what the
ranking shows. Dense retrieval moves the correct item for #25 from rank 9 to rank 3.

T17 is a live trap rather than a missing feature: `KNOWLEDGE_BUCKET` and `KNOWLEDGE_INDEX_OBJECT`
sit in `.env` and `google-cloud-storage` sits in `pyproject.toml`, and **no code reads any of
them**. Resolve it in one direction or the other.

## Phase 4 — judgement

| ID | Task | Root cause | Status |
|---|---|---|---|
| T18 | One function answering "did the request name this item", used by retrieval and the guard | RC-3 | To do |
| T19 | Rivals qualify on IDF-weighted name coverage instead of a hard `df ≤ 4` cutoff | RC-3 | To do |
| T20 | Retune `RIVAL_FLOOR`, `MIN_RIVAL_COVERAGE`, `MAX_CANDIDATES`; stop discarding a correct rank-1 | RC-4 | To do |
| T21 | Composer returns a structured verdict claim; code compares it to the fact pack | RC-6 | To do |

These interact. Fixed separately they trade failures back and forth between the
false-clarification rate and the confidently-wrong rate.

If T20 starts absorbing days, the calibration in T14 is not doing its job — go back to it rather
than hand-fitting constants.

## Phase 5 — data and honesty

| ID | Task | Status |
|---|---|---|
| T22 | Rename the Copywriting item "Paid ads" so it stops colliding with the Paid ads section | Needs the Scope sheet owner |
| T23 | Fix the citation line on the catalog-list path — "No supporting documents retrieved" misreports a catalog answer | To do |
| T24 | Keep build artefacts newer than their sources | Index done; `widget/dist` still stale |

## Waiting on a product ruling

| Question | Blocks | Why it matters |
|---|---|---|
| #9 — when a request names two disagreeing services, ask or resolve to the more specific one? | T19, T20 | Changes the behaviour those tasks tune toward. Answering late means tuning twice. The eval currently encodes the existing design (ask). |
| #16/#17 — should login require a branch rather than offering it optionally? | — | Removes a class of "which branch?" round-trips for one field at sign-in. The plumbing already exists. |
| #23 — track the 4–5/month ad-hoc email allowance, or quote every time? | — | Needs a per-branch running total the sheet does not expose, and the sheet is read-only by design. |
| #7 — wording implied a correct out-of-scope verdict might be quotable | — | Prose fix in the corpus or the composer brief, not code. |
