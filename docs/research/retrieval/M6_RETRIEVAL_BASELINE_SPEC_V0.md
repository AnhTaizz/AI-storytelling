# M6 Retrieval Baseline v0 — task specification

Status: SPEC (approved by the project owner for a parallel agent, 2026-11-14). This is an M6
spike: a prototype that does not complete M6 (see `docs/ROADMAP.md`, Execution Semantics).

Read `CLAUDE.md` first. Its rules (quality gate, one test file per module, no duplicated
tests, protected paths, never push to `main`) apply in full.

## Goal

Given a story, a chapter cutoff and a query, return the source passages most relevant to the
query, **never from a chapter after the cutoff**. The story pipeline
(`tools/story_pipeline`) will later use this to fetch context for chapters it is not
writing (recaps, callbacks, cross-checks), so the interface matters more than the score.

## Ownership (to avoid conflicts with the parallel pipeline work)

| You own | Read/import only, do not modify | Do not touch |
|---|---|---|
| `tools/story_retrieval/**` (new) | `tools/story_pipeline/source.py` (`load_scope`, `Chapter`, `Passage`) | `tools/story_pipeline/**` other than importing `source.py` |
| `tests/story_retrieval/**` (new) | `tools/story_benchmark/bm25_lexical_v1.py`, `dense_e5_*_v1.py`, `multi_gold_metrics.py` | `tools/story_memory/**`, `schemas/story_pipeline/**` |
| `schemas/story_retrieval/**` (new) | `data/sample/**` (protected) | protected paths in `tools/ci/policy/protected_paths.txt` |
| `docs/research/retrieval/**` | | |

Shared files: append only to `docs/PROJECT_STATE.md`, `docs/DECISIONS.md` and
`requirements-*.txt`. Never hand-edit `tests/TEST_CATALOG.md`; regenerate it with
`python -m tools.ci.test_policy --write-catalog`, including after every rebase.

Do not use Gemini or any other LLM: the free-tier keys are shared with live pipeline runs.

## Interface (v0)

```python
# tools/story_retrieval/retrieval_v0.py
@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    cutoff_chapter: int            # inclusive; nothing after it may be returned
    k: int = 10
    chapters: Optional[Tuple[int, int]] = None  # optional narrower window, must end <= cutoff

@dataclass(frozen=True)
class Hit:
    passage_id: str                # "<chapter>.<paragraph>", as in source.py
    chapter: int
    score: float
    rank: int                      # 1-based
    text: str
    retriever: str                 # e.g. "bm25_v0", "dense_e5_small_v0", "hybrid_rrf_v0"

class Retriever(Protocol):
    name: str
    def index(self, passages: Sequence[Passage]) -> None: ...
    def search(self, query: str, allowed_ids: AbstractSet[str], k: int) -> List[Tuple[str, float]]: ...

def build_corpus(manifest_path, cutoff_chapter, source_root=None) -> List[Passage]
def retrieve(request: RetrievalRequest, retriever: Retriever, passages: Sequence[Passage]) -> List[Hit]
```

- **Corpus.** Load passages with `load_scope(manifest, (1, cutoff_chapter))`. Because only chapters
  up to the cutoff are loaded, spoiler safety holds by construction. Keep an explicit
  assertion as well.
- **Retrievers:**
  - `bm25_v0` is required. It works with no extra dependencies; reuse or wrap
    `BM25LexicalV1`. Its tokenizer is Japanese-oriented, so state how other scripts
    (Latin, Hangul) are tokenized and test it.
  - `dense_e5_v0` is optional and uses `multilingual-e5`. It must import torch and
    sentence-transformers lazily. Its tests are gated through `tests/environment_gates.yaml`
    (`requires_modules`), the same way as `story_benchmark/test_dense_e5_*`.
  - `hybrid_rrf_v0` is optional: Reciprocal Rank Fusion of the two (K = 60).
- **Determinism.** The same input gives the same ranking. Break ties by passage id in natural
  order (`1.2` before `1.10`). Only results with a score above zero are returned.
- **Output schema.** `schemas/story_retrieval/retrieval_result_v0.schema.json` holds the
  request echo, the retriever name and version, the list of hits, and `corpus_chapters`
  (first and last chapter loaded).
- **CLI:**
  `python -m tools.story_retrieval.retrieve --cutoff 5 --query "..." [--k 10] [--retriever bm25] [--json]`.
  Default manifest:
  `data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml`
  (chapters 1–5 are tracked).

## Evaluation

- **Public.**
  - Write a small dev probe set over chapters 1–5 in `tests/story_retrieval/fixtures/`.
  - Use about 10 queries, in Japanese and in Vietnamese, the latter because pipeline queries
    will often come from Vietnamese briefs.
  - Each probe has gold passage ids, in the probe format that
    `multi_gold_metrics.calculate_probe_metrics` accepts.
  - This is a dev set, not a sealed benchmark. Say so in the doc.
- **Private (optional, gated).** If `.local/story_integration/otonari_30ch/LONG_RANGE_PROBE_V1/`
  exists, report CUTOFF_FILTERED metrics for comparison with the M1-30CH baselines in
  `docs/PROJECT_STATE.md`:
  - BM25: Hit@10 20%;
  - e5-small: Hit@10 93.3%, Full Evidence Success@10 20%;
  - e5-large: Full Evidence Success@10 26.7%.

  Do not commit private artifacts.
- **Metrics.** Hit@k, Recall@k, MRR, and Spoiler_Violation, which must be 0 by
  construction.

## Tests (in `tests/story_retrieval/test_retrieval_v0.py`, one file per module)

Cover behaviour, not implementation. Use `subTest` for variations.

- **Spoiler safety:** no hit has a chapter after `cutoff_chapter`, including when the query
  matches later text exactly. A `chapters` window that ends after the cutoff is rejected.
- **Determinism and order:** tie-break order, natural order of passage ids, and the
  zero-score policy.
- **Languages:** BM25 finds a known passage from a Japanese query, and the tokenizer
  handles Latin and Hangul text.
- **Output:** the result validates against the schema, and the CLI `--json` output
  round-trips.
- **Dense and hybrid:** gated tests only.

## Done when

1. `python -m tools.ci.check --coverage` → `QUALITY GATE: PASS`, with diff coverage of changed
   `tools/` lines at or above 80%.
2. `docs/research/retrieval/M6_RETRIEVAL_BASELINE_V0.md` records:
   - the design;
   - the dev-probe metrics for each retriever;
   - the private comparison, if it was run;
   - known limits.
3. One short entry is appended to `docs/PROJECT_STATE.md`.
4. The work is on its own branch, with a pull request to `main`. Nothing is merged without the
   owner.

## Phase 2 (after the story-memory pull request is on `main`)

Phase 2 indexes Story Brief items (facts, relationships, events) from `tools/story_memory`.
Each hit carries its brief reference (`c<chapter>.<id>`) and expands to its evidence passages.
The same cutoff rule applies. Agree the interface with the pipeline work before starting.

## Out of scope

- LLM calls, rerankers that need a GPU, and graph or temporal memory (M10/M11).
- Any change to the pipeline, the memory store, M3 ingestion or the benchmark modules.
