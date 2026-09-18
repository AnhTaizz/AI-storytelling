# DENSE_E5_MULTIQUERY_V1 Methodology

## Purpose
This experiment (TASK M1-30CH-I) tests one retrieval hypothesis:

> A single dense query under-specifies the multiple evidence needs of long-range /
> multi-evidence questions. Deterministic, question-only query decomposition plus
> multi-query rank fusion should improve Required Evidence Recall and Full Evidence
> Success over single-query dense retrieval (`DENSE_E5_SMALL_V1`).

It is a controlled experiment. The only variable changed relative to `DENSE_E5_SMALL_V1`
is: one query → several question-derived queries fused with Reciprocal Rank Fusion.
The purpose is to test (and possibly falsify) the hypothesis, not to show that multi-query
retrieval works. A negative result is a valid result.

This document was frozen **before** the first scored execution. The rules below were not
tuned on benchmark results, and there is exactly one decomposition version.

## Frozen Controls (identical to DENSE_E5_SMALL_V1)
- **Corpus**: Otonari 30-chapter frozen corpus, fingerprint `7f9bb8106d6d50acd2b3760738c0b8040f36ab547c2d2f7eade1ca0b9a827ff8`.
- **Passage contract**: `OTONARI_LOCAL_PASSAGE_V1 / PARAGRAPH_PACK_V1` (chunks SHA-256 `10ef5681…40fb`).
- **Benchmark**: `LONG_RANGE_PROBE_V1`, 15 frozen probes (probe file SHA-256 `24ca1f9c…36e2`).
  The runner verifies both hashes against `LONG_RANGE_PROBE_V1_FREEZE.yaml` and stops if they differ.
- **Model**: `intfloat/multilingual-e5-small`, HuggingFace revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, CPU only.
- **Representation**: F parent-chunk representation (one embedding per parent chunk, 512-token
  truncation). The encoder is the unchanged `DenseE5SmallV1` class. There is no Window-Max (G) and no MMR (H).
- **Prefixes**: `query: ` for every query and subquery, `passage: ` for passages.
- **Similarity**: cosine (dot product of unit-normalized embeddings).
- **Cutoff semantics, metrics, gold evidence**: identical to F.

## Anti-Leakage Contract
Query decomposition reads **only** the `question` field. The runner builds a question-only
view of each probe (`{"question": ...}`) before decomposing it. `cutoff_chapter` is used
only to filter candidate passages at the spoiler boundary.

Decomposition never reads `category`, `required_evidence_chunk_ids`,
`supporting_evidence_chunk_ids`, `expected_answer`, `expected_facts`,
`earliest_required_chapter`, `latest_required_chapter`, `chapter_span`,
`requires_multi_chunk`, `requires_multi_chapter`, `forbidden_future_chapters` or `difficulty_notes`.
Gold fields are read only after retrieval, to compute metrics. `category` is used only to
aggregate per-category metrics. Unit tests enforce this with a guarded mapping that
raises if decomposition touches any key other than `question`. No rule special-cases a `probe_id`.

## Query Decomposition Contract — `QUESTION_FACET_DECOMP_V1`
The method is deterministic and rule-based. It uses no LLM, no external API, no synonym
expansion and no story knowledge. The same rules apply to every probe.

1. **Normalization** (`normalize_text`): Unicode NFKC, then every run of Unicode whitespace
   is collapsed to one ASCII space, then leading and trailing whitespace is stripped. Case is preserved.
2. **Q0** is the normalized original question. It is always the first query.
3. **Facet generation**. Each stage consumes the outputs of the previous stage:
   - **A. Sentence split**: split Q0 after `.`, `?` or `!` when followed by whitespace.
   - **B. Directive strip**: for each A segment containing `:`, keep only the text after the
     first `:` (the enumerated body). Segments without `:` pass through unchanged.
   - **C. Enumeration split**: split each B segment on `,` and `;`.
   - **D. Range split**: for each C item, apply the first matching pattern, case-insensitive
     and word-bounded, in this order:
     1. `<stem> from <X> to <Y>`
     2. `<stem> between <X> and <Y>`

     The rule emits `<stem> <X>` and `<stem> <Y>`, so each endpoint keeps the question's
     topical stem. When the stem is empty it emits `X` and `Y`. Items with no match pass through unchanged.
   - Candidate order: A segments (only if A produced more than one sentence), then B, then C, then D.
4. **Facet cleaning**: normalize, then strip leading and trailing whitespace and `. ? ! , ; :`.
5. **Validity filter**: a facet needs at least `MIN_CONTENT_TOKENS = 2` content tokens. A
   content token is a word token that is not in the frozen closed-class English stopword list
   (`FUNCTION_WORDS_V1` in code) and is not purely numeric. This removes scoping fragments that
   carry no evidence need, such as a bare "as of <N>" phrase.
6. **Deduplication**: the dedup key is the cleaned facet, casefolded. Q0 and any facet whose
   key matches Q0 or an earlier facet are dropped.
7. **Cap**: at most `MAX_QUERIES_PER_PROBE = 8` queries including Q0, in generation order.

If no valid facet survives, the probe uses only Q0. That is a valid outcome, and no query is
invented to force decomposition.

## Retrieval / Fusion Contract
- Each query is embedded independently (batch of one) with the frozen E5 model, using the same
  call path as F. For Q0 this gives exactly the F query embedding.
- Each query produces a cosine ranking over the eligible parent chunks. Ties are broken by `chunk_id` ascending, as in F.
- **Reciprocal Rank Fusion**: `RRF(d) = Σ_q 1 / (K_RRF + rank_q(d))` with ranks starting at 1.
  `K_RRF = 60` is frozen and was not swept. Scores are summed in exact rational arithmetic, so
  ties are exact and do not depend on summation order.
- Final ordering: RRF score descending, then `chunk_id` ascending.
- Top-10 of the fused ranking is evaluated. Top-1/3/5/10 all come from the same fused ranking.
- No MMR, reranker, BM25 hybrid, graph, or LLM rewriting is used.

## Cutoff Semantics
1. **CUTOFF_FILTERED** (primary): only chunks with `chapter_number <= cutoff_chapter` are
   candidates for every query ranking, before fusion.
2. **GLOBAL_DIAGNOSTIC**: all 97 chunks are candidates. This mode measures natural spoiler leakage, as in F and H.

## Relevance Control Gate (fail-fast)
Before any multi-query scoring, Q0 alone is scored with ordinary cosine relevance under CUTOFF_FILTERED:
- The ordered chunk-id list for each of the 15 probes must equal the ranking in the local F
  artifact `DENSE_E5_SMALL_V1/cutoff_filtered_per_probe.jsonl`. That artifact's SHA-256 must
  match the value recorded in `DENSE_E5_SMALL_V1_RESULT.yaml`.
- Aggregate CUTOFF_FILTERED overall metrics must equal the committed F result, with tolerance 1e-9.
- If the F artifact is missing, or anything mismatches, execution stops. No approximate baseline is reconstructed.

## Metrics
Same metrics as F and H, for K = 1, 3, 5, 10: Hit@K, Required Evidence Recall@K,
Full Evidence Success@K, MRR and Spoiler Violation@K. Values are macro-averaged overall and
per category; categories are used only for this reporting. The F reference values are read
from `DENSE_E5_SMALL_V1_RESULT.yaml` and are not hard-coded.

## Diagnostics
- **Decomposition**: probe_count, probes_with_multiple_queries, probes_with_single_query_only,
  mean, min and max queries per probe, and the histogram of queries per probe.
- **Retrieval vs Q0-only control** (CUTOFF_FILTERED Top-10):
  - mean number of chunks newly introduced into Top-10;
  - mean Top-10 Jaccard overlap;
  - number of probes whose Top-10 set changed;
  - number of probes where Recall@10 improved, decreased or stayed unchanged;
  - number of Full Evidence Success@10 transitions 0→1 and 1→0.

## Frozen Interpretation Rule
Deltas are I minus F on CUTOFF_FILTERED overall metrics. "Major collapse" of Hit@10 means
ΔHit@10 < −0.10, which is more than one probe out of 15.
- **NOT_EVALUABLE**: any gate fails (benchmark freeze, relevance control, determinism,
  privacy), or fewer than 3 of 15 probes (under 20%) produce more than one query.
- **SUPPORTED**: ΔRecall@10 > 0 **and** ΔFullEvidenceSuccess@10 > 0 **and** no major Hit@10 collapse.
- **PARTIALLY_SUPPORTED**: not SUPPORTED, but ΔRecall@10 > 0 **or** ΔFullEvidenceSuccess@10 > 0.
- **NOT_SUPPORTED**: ΔRecall@10 ≤ 0 **and** ΔFullEvidenceSuccess@10 ≤ 0.

The verdict is computed mechanically by `interpret_verdict()` in code. The algorithm is not
changed after the first valid scored execution.

## Reproducibility Contract
The runner executes the full pipeline twice in a row. After runtime-only fields are removed,
the following must be identical across both runs: the aggregate result, the decomposition
manifest hash, the control ranking hash, the fused ranking hashes (cutoff and global), and the
per-query ranking hash. Any difference sets `deterministic_reproduction_status: FAIL` and
invalidates the result.

## Privacy
Raw questions, generated subqueries, chunk text, chunk IDs, embeddings and per-probe rankings
stay in `.local/story_integration/otonari_30ch/DENSE_E5_MULTIQUERY_V1/`. The public result YAML
holds only aggregate metrics, aggregate diagnostics and hashes. Before the public YAML is
written, the runner scans it and stops if it contains any question, subquery or chunk ID string.
This document uses no probe text.

## Non-Goals
This experiment does not introduce a new embedding model, windowing, MMR, rerankers,
cross-encoders, BM25 hybrid retrieval, graph or entity memory, LLM query rewriting, answer
generation, prompt tuning or parameter sweeps.
