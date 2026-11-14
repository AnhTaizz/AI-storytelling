# M6 Retrieval Baseline v0

Status: IMPLEMENTED, PR pending owner review. This is an M6 spike and does not
complete M6. Phase 2 (Story Brief retrieval and evidence expansion) has not started.

## Interface and safety

`tools/story_retrieval/retrieval_v0.py` defines frozen `RetrievalRequest` and `Hit`
records, the `Retriever` protocol (`name`, `version`, `index`, `search`),
`build_corpus`, `retrieve`, `result_to_dict`, and `make_retriever`.

`build_corpus(manifest_path, cutoff_chapter, source_root=None)` calls the unchanged
pipeline `load_scope` for chapters 1 through the inclusive cutoff and flattens
passages in chapter order. This bounds the corpus by construction. An explicit
`RuntimeError` check rejects a loader result containing a later passage, including
under optimized Python. Cutoffs below 1 are rejected.

`retrieve` rejects blank queries, nonpositive k/cutoff, and any chapter window
outside `1 <= start <= end <= cutoff`. It indexes the supplied passages, passes
only eligible IDs to search, then independently filters returned IDs and scores.
Thus callers may supply an index containing later chapters without returning
later passages. A final explicit spoiler check guards the constructed hits.
Each retriever snapshots the passage sequence: equal sequences reuse the index;
a different sequence replaces it. This includes changed text under an existing ID.

Only scores above zero survive. Ordering is descending score, then a total
natural order over digit/non-digit runs (`1.2` before `1.10`, also supporting
`ch002_c0010`); original spelling breaks numerically equivalent ties. Ranks are
1-based. BM25 reorders all positive candidates before truncating, avoiding the
frozen scorer's lexical tie-break at the top-k boundary.

The draft 2020-12 schema is
`schemas/story_retrieval/retrieval_result_v0.schema.json`. It rejects extra object
properties and requires the version, request echo, retriever identity/version,
corpus chapter bounds, and hits with text, chapter, positive score, rank and
retriever name. Chapter bounds describe supplied passages at or below the cutoff,
independently of a narrower search window; both bounds are null for an empty corpus.

## Retrievers and tokenizer

- `bm25` / `bm25_v0`, version `0`: wraps the unchanged `BM25LexicalV1`, k1=1.2,
  b=0.75, tokenizer `jp_simple_lexical_v1`.
- `dense_e5` / `dense_e5_small_v0`, version `0`: defaults to
  `intfloat/multilingual-e5-small` on CPU with normalized embeddings. It applies
  `query: ` and `passage: ` prefixes and computes cosine similarity in Python.
  An optional encoder callable enables offline tests. Sentence-transformers is
  imported inside the lazy loader on first encoding, never at module import or
  retriever construction. Invalid embedding counts/dimensions/values fail clearly.
- `hybrid` / `hybrid_rrf_v0`, version `0`: combines BM25 and dense rankings with
  `sum(1 / (60 + rank))`, searching each component to depth `max(k, 100)` and
  applying the same deterministic tie-break. Components can also be supplied directly.

The frozen tokenizer applies Unicode NFKC and casefold. Hiragana, Katakana and CJK
emit unigrams and adjacent bigrams. Every other alphanumeric run, including Latin
with Vietnamese diacritics, digits and Hangul, is a single word token; whitespace
and punctuation delimit these runs and punctuation is dropped. Hangul has no
morpheme splitting. This is lexical matching with no translation.

## CLI and reproduction

From the repository root (on Windows, set `PYTHONUTF8=1` so the quality gate's git
subprocesses decode non-ASCII diffs):

```
python -m tools.story_retrieval.retrieve --cutoff 5 --query "お粥 梅" --k 10 --retriever bm25 --chapters 2-4 --json
python -m tools.story_retrieval.evaluate_v0 --retriever bm25 --json
```

Retrieval also accepts `--manifest` and `--source-root`. The default manifest is
`data/sample/otonari_no_tenshi/wn_jp/LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml`.
JSON preserves Unicode and stdout is explicitly UTF-8 on Windows. Text output
contains one rank, passage ID, score and short single-line snippet per hit.
Invalid arguments/windows and missing optional dependencies report stderr and
return exit code 2. Both modules expose `main(argv=None)`.

## Public DEV evaluation (2026-11-15)

The fixture contains 10 implementer-authored probes: five Japanese and five
Vietnamese, with cutoffs varying across chapters 1–5. Gold was selected by reading
the actual `load_scope` passages. Each probe has one gold passage. This is a small
DEV set, not a sealed benchmark; the paired facts and authoring process limit
independence and generalization.

These are the real `evaluate_v0 --retriever bm25 --json` results. Because each
probe has a single gold passage, Hit, Recall and Full Evidence Success coincide
at every reported depth.

| bm25_v0 group | Probes | Hit/Recall/Success@1 | @5 | @10 | MRR through 10 | Spoiler violation@1/5/10 |
|---|---:|---:|---:|---:|---:|---:|
| Overall | 10 | 30% | 50% | 50% | 0.4000 | 0 |
| Japanese | 5 | 60% | 100% | 100% | 0.8000 | 0 |
| Vietnamese | 5 | 0% | 0% | 0% | 0.0000 | 0 |

Evaluation indexes all five public chapters once and filters IDs for each probe's
cutoff. BM25 corpus statistics therefore use the full public pack, while returned
evidence always respects the cutoff. The API returns overall and per-language
means plus per-probe IDs/ranks/metrics without source text. The CLI prints aggregates.

| Retriever | Real-model dev/private evaluation here |
|---|---|
| bm25_v0 | Run; numbers above and below |
| dense_e5_small_v0 | Not run: torch and sentence-transformers are not installed |
| hybrid_rrf_v0 | Not run: its dense component requires the same absent dependencies |

## Private CUTOFF_FILTERED comparison

The local comparison was run over 15 probes under
`.local/story_integration/otonari_30ch/`, using only
`LONG_RANGE_PROBE_V1/probes.yaml` and `PARAGRAPH_PACK_V1/chunks.jsonl`.
Chunks are converted to pipeline passage IDs internally, then ranked IDs are
mapped back to the original chunk IDs for the canonical multi-gold metrics.
All chunks are indexed for frozen BM25 statistics; eligibility is restricted per
probe cutoff. No private text, queries, IDs or per-probe output is written to
tracked artifacts. `evaluate_private` returns aggregates only and returns `None`
when either input file is absent.

| bm25_v0 depth | Hit | Recall | Full Evidence Success | Spoiler violation |
|---|---:|---:|---:|---:|
| 1 | 6.6667% | 3.3333% | 0% | 0 |
| 3 | 20% | 8.8889% | 0% | 0 |
| 5 | 20% | 8.8889% | 0% | 0 |
| 10 | 20% | 8.8889% | 0% | 0 |

MRR through depth 10: **0.1333333333**. These aggregates reproduce the recorded
`BM25_LEXICAL_V1` CUTOFF_FILTERED overall results, including all reported depths,
recall, completion, MRR and spoiler violation. The natural tie-break change does
not alter these aggregate results on this pack.

| M1-30CH comparison | Hit@10 | Full Evidence Success@10 |
|---|---:|---:|
| bm25_v0 (this run) | 20% | 0% |
| BM25_LEXICAL_V1 (recorded) | 20% | 0% |
| e5-small (spec's historical baseline) | 93.3% | 20% |
| e5-large (spec's historical baseline) | — | 26.7% |

The dense historical values are comparison figures from the task specification,
not reruns in this environment. MRR here is truncated to the requested maximum
depth, so comparisons on other packs must use the same depth convention.

## Verification and limits

The retrieval tests cover real public loading/Japanese retrieval, cutoff/window
validation, defensive filtering, natural ties, positive-score policy, Unicode
JSON/schema and CLI output/errors, dense cosine/prefixes, RRF arithmetic, index
reuse/replacement and import isolation. Evaluation tests validate public gold and
exercise the private adapter using a tiny synthetic temporary pack only.

Dense and hybrid tests use deterministic injected encoders without torch. No
real-model gated test was added: `tests/environment_gates.yaml` is protected and
adding such a gate requires an owner decision. The actual dense model and its
multilingual retrieval quality remain unexercised here. No new dependencies,
network access, Gemini or other LLM calls are involved in this implementation.

BM25 cannot bridge Vietnamese queries to Japanese evidence: all five Vietnamese
DEV probes score zero on Hit/Recall/Success and MRR. Hangul remains word-level.
The dev set is small, paired and authored by the implementer, not sealed. Dense
model truncation and model/revision reproducibility require a later real-model
evaluation. There is no reranker or Story Brief integration; phase 2 is not started.
