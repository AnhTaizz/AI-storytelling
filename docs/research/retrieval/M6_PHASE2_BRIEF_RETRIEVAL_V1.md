# M6 Phase 2 — Brief retrieval v1

Status: **IMPLEMENTED**. The decisions are in `docs/DECISIONS.md` (DEC-021); the proposal they answer is `M6_PHASE2_BRIEF_RETRIEVAL_PROPOSAL_V0.md`. This document records the design, the DEV results and the limits.

## What it does

`tools/story_retrieval/brief_retrieval_v1.py` searches Story Brief items rather than raw source passages. Every hit carries all of the source passages its item cites.

| Piece | Behaviour |
|---|---|
| Items | Every event (`c3.E2`), character fact (`c3.CH1.F2`) and relationship (`c3.R1`) of the chapter briefs up to an inclusive cutoff. Rendered in the brief's own words with the item's chapter-local names, location, motivation (with its status), consequence and epistemic label (`brief_render_v1`). |
| Identity | Refs are bound to one brief snapshot. `BriefCorpus.stamps` holds chapter → sha256 of the brief's canonical JSON, and `snapshot` hashes story, cutoff, language, renderer and stamps. Regeneration may renumber refs. |
| Validation | A missing chapter, an item without evidence, or evidence that is not a passage of the item's own chapter (≤ cutoff) rejects the whole corpus. Nothing is trimmed. |
| Spoiler safety | Briefs after the cutoff are dropped before rendering. The retriever only sees allowed refs, and every returned item and expanded passage is checked against the request cutoff again. A retriever that ignores its allowed set still cannot leak (tested). |
| Ranking | BM25 tokenized for the brief language: words plus word pairs for Vietnamese (`latin_words_bigrams_v1`), the frozen Japanese tokenizer, and the CJK bigram baseline for ko/zh. Any v0 `Retriever` (e5 dense, hybrid) can be passed instead. |
| `delivery(hits, budget)` | Evidence in rank order, deduplicated, up to a passage budget. Support that does not fit is returned as `overflow`. |
| `entity_evidence(corpus, names)` | Every item naming the entity, in chapter order, with its passages. Always `status: partial`: briefs keep selected facts only (DEC-021, item 9). |
| `callback_candidates(...)` | Earlier events (any importance) recalled by an episode's events, for the episode recap. |

## DEV results (no model calls)

The evaluation used `python -m tools.story_retrieval.evaluate_brief_v1` on DEV v1: 30 probes, 15 in Japanese and 15 in Vietnamese, chapters 1–5. The probe gold was locked before retrieval by the Phase 1 work. The briefs are the stored model briefs for public chapters 1–5, pinned in `tests/story_retrieval/fixtures/briefs_sample_v1/` so CI can rerun the evaluation.

Recall / Success at each delivery depth. Gold is passage ids; Success means every passage of one gold set was delivered.

| Route | Language | @10 | @20 | @30 |
|---|---|---|---|---|
| passage BM25 (Phase 1) | ja | 73.3 / 73.3 | 73.3 / 73.3 | 93.3 / 93.3 |
| passage BM25 (Phase 1) | vi | 0 / 0 | 0 / 0 | 0 / 0 |
| **brief BM25** | vi | **83.3 / 80.0** | **90.0 / 86.7** | 90.0 / 86.7 |
| **brief, then passage** | all | 78.3 / 76.7 | 81.7 / 80.0 | **91.7 / 90.0** |

- **Comparison with Phase 1 dense retrievers.** These numbers come from `M6_RETRIEVAL_BASELINE_V0.md`, run on a machine with the models. On the same probes, e5-large reached Vietnamese Success@10 53.3%. The best overall Success@30 was 86.7%, by hybrid-large. Brief retrieval needs no model and beats both on these probes, because a Vietnamese question meets Vietnamese brief text instead of crossing languages.
- **Japanese questions** find nothing in Vietnamese briefs, so the combined route falls through to passage retrieval for them. A Japanese-brief profile would reverse this.
- **Spoiler violations: 0** on every route. The evaluation raises an error if any delivered passage is after the probe cutoff.
- **Brief coverage ceiling:** 80% of probes have a gold set whose passages are all cited by some brief item. The other 20% need the passage route: briefs keep selected facts only.

## Pipeline use

An episode with earlier chapters (recap mode) gets up to 8 callback candidates: earlier events that its own events recall, with evidence ids, quote and epistemic label. They are added to the recap, and the plan may cite them as callbacks. See "Callbacks from brief retrieval" in `docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md`.

## Limits

- DEV probes are authored by the implementers and are not a sealed benchmark. Five Vietnamese and five Japanese probes per category is small: one probe moves a language figure by 6.7 points.
- The briefs are one model's output for one story. Their coverage (80%) bounds the brief route. A different brief could change the numbers.
- Exhaustive entity evidence (every mention, pronouns, indirect references) needs M4 extraction persisted by M5. It is deferred to M10 (DEC-021, item 9).
- Dense retrieval over brief items is supported but not measured here: the models cannot be downloaded in this environment.
