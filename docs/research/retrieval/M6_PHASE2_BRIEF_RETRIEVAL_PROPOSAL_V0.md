# M6 Phase 2 — Story Brief retrieval interface proposal v0

Status: **PROPOSAL — not agreed, no implementation; needs owner + pipeline agreement.**

This document proposes the interface requested by `M6_RETRIEVAL_BASELINE_SPEC_V0.md:Phase 2`. All interfaces below are
proposed unless explicitly described as current. Agreement is required before implementation.

## 1. What exists today

- Passage retrieval uses frozen `RetrievalRequest(query, cutoff_chapter, k=10, chapters=None)` and `Hit(passage_id,
  chapter, score, rank, text, retriever)`; `Retriever` has `name`, `version`, `index`, and `search`. Cutoffs are
  inclusive; windows satisfy `1 <= start <= end <= cutoff`; only positive scores survive, with natural-ID tie ordering
  (`tools/story_retrieval/retrieval_v0.py:RetrievalRequest, Hit, Retriever, retrieve, natural_key`).
- `build_corpus` returns source `Passage`s for chapters 1 through cutoff using `load_scope`; it explicitly rejects later
  passage IDs. `Passage` contains only `passage_id` and `text`; IDs are chapter order plus paragraph ordinal, not brief
  IDs (`tools/story_retrieval/retrieval_v0.py:build_corpus`; `tools/story_pipeline/source.py:Passage, load_scope`).
- Exact brief shapes (`schemas/story_pipeline/story_brief_v0.schema.json:properties`):

  | Collection | ID field | Content and provenance |
  |---|---|---|
  | `characters[]` | `id`, pattern `^CH\d+$` | `name`, `romanized_name`, `aliases`, `facts[]` |
  | `characters[].facts[]` | **none** | `text`, `evidence`, `quote`, `epistemic` |
  | `relationships[]` | **none** | `between` (two `CH` IDs), `state`, `evidence`, `quote`, `epistemic` |
  | `events[]` | `id`, pattern `^E\d+$` | `summary`, `participants`, `location`, `importance`, `motivation`, `consequence`, `evidence`, `quote`, `epistemic` |

`importance` is CORE/SUPPORTING/MINOR; `motivation` has `text` and `status`. Each fact/relationship/event has nonempty
`evidence`: passage-ID strings matching `^\d+\.\d+$`. `quote` is a short source excerpt; `epistemic` is EXPLICIT,
REPORTED, APPEARANCE, SPECULATION, or FIGURATIVE. Summary, unknowns, forbidden inferences, ending state, and closing
hook also exist; closing hook has evidence but no item ID (same schema:properties).

- Briefs are produced per chapter by `stages.run_brief`; schema validation precedes semantic checks
  (`tools/story_pipeline/stages.py:run_brief`; `tools/story_pipeline/llm.py:run_json_stage`). Currently **every cited
  passage must belong to that same chapter**, stronger than merely `<= chapter_order`; quotes, character/event
  uniqueness, and participant references are checked (`tools/story_pipeline/stages.py:brief_semantic_errors`).
- `StoryMemory` stores `<root>/<story_id>/chapters/chapter_NNN.json`, one current record per chapter order. The envelope
  contains format, chapter_order, source_version, brief_fingerprint, producer, and brief. `get_brief` requires matching
  format/order/source_version/fingerprint; `put_brief` replaces the file atomically
  (`tools/story_memory/memory_v0.py:StoryMemory._path, get_brief, put_brief`). Source version is the source-byte SHA-256
  (`tools/story_pipeline/source.py:Chapter`). The fingerprint hashes brief system/user prompts, schema bytes, and brief
  language; it excludes model and is **not a hash of generated brief content**
  (`tools/story_pipeline/stages.py:brief_fingerprint`).
- `as_of(briefs, order)` filters inclusively and sorts; it does not validate evidence or cache freshness. `build_roster`
  merges characters by shared normalized names or aliases, reports ambiguous matches, and assigns derived `P` keys;
  `ref_index` maps **character** refs such as `c2.CH1` to those keys, not arbitrary brief items
  (`tools/story_memory/memory_v0.py:as_of, build_roster, ref_index`).
- `relationship_timeline` groups each resolved character pair's chapter/state/evidence observations in chapter order; it
  carries no relationship item ref or epistemic label. `recap_context(briefs, before=N)` uses chapters `< N`: summaries,
  ending states, CORE event refs/summaries, unknowns, roster, latest stated relationships, and roster warnings.
  `recap_event_refs` extracts those CORE refs (`tools/story_memory/memory_v0.py:relationship_timeline, recap_context,
  recap_event_refs`).
- `run` writes run-local `briefs/chapter_NNN.json`, reuses memory after semantic checks, constructs `memory_recap.json`,
  and passes recap to plan/script/critic/revision. Run-local `cached(..., resume=True)` bypasses `produce`, hence
  bypasses its memory freshness checks (`tools/story_pipeline/run_pipeline.py:run, cached`).
- Prompt refs are added only to characters/events. Plans accept episode events plus recap CORE events; callbacks have
  setup_ref/payoff_ref. Critic brief_refs are strings, but strength/hedge audits resolve character/event refs, including
  recap CORE events; recap labels become EXPLICIT in `labelled_statements`
  (`tools/story_pipeline/stages.py:briefs_for_prompt, event_index, plan_semantic_errors, brief_item_texts,
  labelled_statements`; `schemas/story_pipeline/narrative_plan_v0.schema.json:properties`;
  `schemas/story_pipeline/critic_v0.schema.json:properties`).

## 2. Proposed additive contract

Leave v0 API, CLI defaults, and `retrieval_result_v0.schema.json` unchanged. Proposed home: a new
`tools/story_retrieval/brief_retrieval_v1.py`; names below reuse imported v0 `RetrievalRequest`, `Retriever`, `Hit`, and
pipeline `Passage`.

```python
Kind = Literal["fact", "relationship", "event"]

@dataclass(frozen=True)
class BriefStamp:
    chapter: int
    source_version: str
    brief_fingerprint: str
    brief_sha256: str                 # new canonical JSON content hash

@dataclass(frozen=True)
class BriefItem:
    item_ref: str                     # c<chapter>.<adapter-local id>
    kind: Kind
    chapter: int                      # observation chapter, not story time
    text: str                         # deterministic indexing rendering
    evidence_passage_ids: tuple[str, ...]
    epistemic: str
    importance: str | None            # event only
    locator: str                      # JSON Pointer into brief snapshot
    pipeline_ref: str | None          # event ref / fact's parent CH ref / None for rel
    stamp: BriefStamp

@dataclass(frozen=True)
class BriefCorpus:
    story_id: str
    cutoff_chapter: int
    brief_language: str
    renderer_version: str
    stamps: tuple[BriefStamp, ...]
    items: tuple[BriefItem, ...]
    passages: tuple[Passage, ...]      # source units used by v0

@dataclass(frozen=True)
class BriefRetrievalRequest:
    request: RetrievalRequest         # preserve v0 validation semantics
    kinds: tuple[Kind, ...] = ("fact", "relationship", "event")

@dataclass(frozen=True)
class BriefHit:
    item: BriefItem
    score: float
    rank: int
    retriever: str
    evidence_hits: tuple[Hit, ...]     # complete expansion, not top-k search

def build_brief_corpus(memory: StoryMemory, scope: StoryScope, cutoff_chapter: int,
                       *, brief_fingerprint: str, brief_language: str) -> BriefCorpus: ...
def retrieve_briefs(request: BriefRetrievalRequest, retriever: Retriever,
                    corpus: BriefCorpus) -> list[BriefHit]: ...
def expand_evidence(item: BriefItem, corpus: BriefCorpus) -> tuple[Hit, ...]: ...
```

**Identity recommendation, needing agreement:** events keep `cN.E1`. Facts receive adapter IDs `cN.F_CH1_1` (first fact
under CH1); relationships receive `cN.R1` (first relationship). These are synthetic IDs, not fields currently in the
schema. Keep JSON Pointers (`/characters/0/facts/0`, `/relationships/0`, `/events/0`). The durable lookup key is
`(story_id, stamp, item_ref)`, never item_ref alone. No stability across regeneration is promised, even for E
IDs. Content hashing uses UTF-8 canonical JSON with sorted object keys and preserved array order; fingerprint identifies
setup, content hash identifies the actual generated snapshot.

**Rendering:** use only the item's own chapter brief: local names/aliases, kind, fact text / relationship state / event
summary, epistemic label; events also include location, importance, motivation text **with status**, and consequence
when present. Preserve hedges; do not translate or add later aliases, roster facts, or inferred causality. Store brief
language and `brief_render_v1` in corpus identity. Quote stays in the source brief; expanded passages provide source
text. Index all three kinds and all event importance levels initially; exclude unreferenced summary/hook prose.

**Construction and safety:** require integer cutoff C >= 1 and scope for this same story containing every chapter 1..C.
Ignore scope chapters > C before deriving any views or index text. Flatten eligible source passages as v0 `build_corpus`
does; check unique passage IDs and source versions. Read memory only for eligible orders using `get_brief(order,
Chapter.version, expected_fingerprint)`; missing/stale records fail the build with chapter/reason, without generating
briefs. Validate schema and current semantic rules again; use `as_of` before roster/timeline work. Never trust run-local
resumed briefs as a substitute for this validation.

Check explicitly that `1 <= evidence_chapter <= item.chapter <= C`, each evidence ID resolves in the same versioned
source corpus, and every item has evidence. Today also require `evidence_chapter == item.chapter` to honor the pipeline
validator. An item failing any check rejects the build; do not trim evidence to make it eligible. Multi-chapter evidence
is therefore **rejected today**. If a later agreed brief contract permits it, all cited chapters must be <= the
observation chapter and C; include the whole item only when every citation passes. An item observed in chapter 5 remains
unavailable at cutoff 4 even if all its evidence is from chapters 1–4.

Search requires request cutoff <= corpus cutoff, a nonblank query, positive k, and the v0 window rule. Filter items
**before indexing**, then independently check every returned item and expanded passage against request cutoff. Window
[S,E] restricts item observation chapters; evidence may precede S in the future multi-chapter case, but never exceed its
item's chapter or the cutoff. Renderings never incorporate later observations. Use positive scores, natural item-ref
ties, contiguous 1-based ranks, and k counting brief items. Empty eligible results return an empty list.

Expansion resolves all distinct evidence IDs against `corpus.passages`, in natural passage-ID order; require the item's
ref and stamp to match the corpus snapshot. Missing evidence is an error. Nested v0 `Hit`s use original text, chapter
from ID, local 1-based rank, `retriever="brief_evidence_v1"`, and `score=1.0` as an explicit lookup marker, **not a
relevance score**. Keep the parent's real score on BriefHit. Expansion is untruncated; shared evidence may appear under
several items. Do not pass synthetic brief IDs to v0 passage_chapter/retrieve/result_to_dict; an internal adapter may
index `Passage(item_ref, text)` through `Retriever.index/search`.

**Relationships:** retrieve historical observations, never silently overwrite older states. Build roster and
`relationship_timeline` from eligible validated briefs only. For a latest-state question at T, choose the last
observation <= T for each resolved pair from the full eligible timeline, not from top-k hits; absence of a new
observation means "last stated at chapter X", not proof it persists. Use original relationship items to recover snapshot
ref and epistemic label, which the timeline projection drops. Multiple observations for one pair in one chapter remain
distinct; conflicting states need review, not an array-order truth decision. Surface roster warnings.

**No mixed ranking initially:** retrieve briefs with full evidence expansion; callers may separately use v0 passage
retrieval as a fallback, recording which route supplied context. Do not compare BM25/dense scores across corpora.
Proposed wrapper names: `brief_bm25_v1`, `brief_dense_e5_small_v1`, `brief_dense_e5_large_v1`, `brief_hybrid_rrf_v1`
(and large variant if evaluated). Version records wrapper, renderer and underlying retriever version/full model revision.
Corpus hash binds story/cutoff, ordered stamps, renderer and language. Existing passage identities stay unchanged.

Add **new** `schemas/story_retrieval/retrieval_result_v1.schema.json` after agreement:
schema_version=`retrieval_result_v1`, request echo (including kinds), retriever identity, story/language/renderer,
corpus snapshot hash/stamps, separate passage/item chapter bounds (null bounds if empty), and `brief_hits` matching
BriefHit above. Nested evidence retains v0 Hit fields; require the lookup marker semantics. Reject extra properties,
validate kind/ref patterns and positive ranks/scores. Cross-field cutoff, provenance, hash and reference consistency
require runtime checks in addition to JSON Schema.

## 3. Pipeline call sites and example requests

These are proposed calls, not current pipeline behavior; query text is illustrative. `br = BriefRetrievalRequest`, `rr =
RetrievalRequest`; construct validated corpus first.

1. **Recap before chapter N=5:** in `tools/story_pipeline/run_pipeline.py:run`, after earlier briefs are available and
   before `stages.run_plan`, send `br(rr("Những sự kiện chính cần nhắc lại trước chương 5?", 4, k=6), ("event",))`.
   Select CORE results for recap; retain the deterministic roster/latest-state view. Retrieval supplements recap
   selection; it does not replace episode CORE coverage.
2. **Callback setup for an episode starting at 5:** before `stages.run_plan` or `stages.run_script`, send `br(rr("Sự
   kiện trước đây khi cô hàng xóm chăm người ốm", 4, k=3, chapters=(1, 3)), ("event",))`. Use the returned E ref plus
   evidence as candidate setup; payoff stays an episode event. Under today's `plan_semantic_errors`, earlier refs must
   already be in `recap_event_refs`; admitting non-CORE setups needs separate pipeline agreement.
3. **Fact cross-check in a chapter-5 script:** before `stages.run_critic` (or a proposed follow-up check for an
   UNDETERMINED claim), send `br(rr("Thói quen ăn uống và tình trạng căn phòng của Amane", 5, k=4), ("fact",))`. Pass
   item, epistemic label, and evidence to the critic; a miss proves nothing. Synthetic fact/relationship refs need
   explicit consumption support: today's `brief_item_texts`/`labelled_statements` cannot resolve them. Do not silently
   replace a precise fact ref with its broader parent CH ref for audit purposes.

## 4. Evaluation plan (after agreement)

Reuse questions/languages/cutoffs from `tests/story_retrieval/fixtures/dev_probes_v0.yaml` as candidate DEV probes;
current gold is passage IDs, not brief refs (`tools/story_retrieval/evaluate_v0.py:evaluate_dev`). Manually map answer
support to snapshot-bound gold item refs; mark questions absent from briefs as coverage gaps, not invented gold.
Preserve a source-only comparison and report brief coverage rate. Pin public chapter-1–5 brief snapshots and their
source/setup/content hashes; use reviewed stored briefs or hand-authored fixtures, without new model calls here.

Maintain separate `gold_item_sets` and `gold_passage_sets`; adapt each separately to `gold_evidence_sets` for
`tools/story_benchmark/multi_gold_metrics.py:calculate_probe_metrics`. Report item Hit/Recall/Full Evidence
Success@1/5/10 and MRR@10; for evidence, deduplicate in parent-rank then nested-rank order. Report evidence metrics at
fixed passage budgets and completeness from the full expansion of top-k items, clearly distinguishing units. The
calculator supports alternative complete gold paths and treats IDs as strings; it does not calculate spoiler violations
(same file:normalize_gold_evidence_sets, calculate_probe_metrics; `tools/story_retrieval/evaluate_v0.py:_metrics`).

Require **Spoiler_Violation = 0** for items, renderings, and every expanded passage; expansion completeness 100%,
dangling refs 0, and deterministic snapshot/rank results. Add boundary probes for later exact matches, missing/stale
briefs, reordered/regenerated items, changing/conflicting relationship states, and invalid multi-chapter evidence. Use
synthetic future-contract cases for atomic multi-chapter cutoff behavior if approved. This remains DEV evaluation, not a
sealed benchmark or milestone completion; agree quality thresholds after baseline measurement. No evaluation is
performed by this document.

## 5. Decisions needed from the owner and pipeline owner

1. Accept snapshot-bound synthetic fact/relationship IDs, or require a new brief schema with producer-assigned IDs? What
   stability is promised for E/CH IDs on regeneration?
2. Accept the separate content hash alongside brief_fingerprint and source_version? Who pins snapshots and invalidates
   retrieval context on pipeline resume?
3. Index all facts/relationships/events and all importance levels? Keep recap/callback admission CORE-only, or extend
   the plan's allowed earlier-event refs?
4. Accept original brief-language rendering without translation, and who versions it?
5. Exclude missing/stale/invalid briefs by failing the build as proposed, or allow an explicitly reported partial corpus
   with source-only fallback? Who refreshes memory?
6. Keep same-chapter evidence now; does future cross-chapter evidence require a new brief contract? Accept atomic
   evidence inclusion and the item-window semantics?
7. Accept historical relationship hits plus deterministic latest-stated views, with warnings/conflicts exposed? How will
   critic preserve epistemic labels from recap?
8. Does retrieval own the new result schema, with pipeline review of consumers? Agree context payload/budget,
   precise-ref audit support, probe ownership, and rollout.

## 6. Out of scope and risks

No implementation, schema/test changes, memory migration, pipeline wiring, LLM calls, mixed-result fusion, graph
traversal, or automatic truth verdict. Correct citations cannot prove faithful paraphrase; partial brief coverage and
name-based roster merges remain risks. Long evidence expansions need a caller budget that does not silently drop
support. Cache setup identity cannot guarantee generated-item stability. This is a spike under
`docs/ROADMAP.md:Execution Semantics, M6`; provenance and temporal state follow `docs/DECISIONS.md:DEC-010, DEC-011`,
without claiming M5/M6 completion (`docs/PROJECT_STATE.md:Implementation Status, M6 Retrieval Baseline v0`).

**Review summary:** add a separate, cutoff-bounded brief search API with complete source-passage expansion and
snapshot-qualified refs. Agreement is chiefly needed on IDs/regeneration, freshness/resume, kind/language policy,
evidence/time semantics, and the pipeline's schema, prompt, and audit consumers before any code starts.
