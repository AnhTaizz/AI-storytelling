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

## Story isolation

Following the "One index per story" amendment owned by PR #6 (the spec on this
branch is unchanged), `build_corpus` now returns a list-compatible `StoryCorpus`
carrying `load_scope`'s `story_id` and `source_language`. `RetrievalRequest` adds an
optional final `story_id` field; `retrieve --story-id ID` exposes it. When supplied,
it must match the corpus before indexing/search. Existing positional calls still
work. Keep the corpus object when passing it between components: converting it to
a bare list discards its identity. Legacy bare passage sequences use the explicit
`unscoped` namespace and Japanese tokenizer; multi-story applications must use
`StoryCorpus`. The frozen v0 JSON schema/request echo is unchanged; story matching
is enforced at the request boundary rather than adding fields to that schema.

Index snapshots include story ID, language and passages. Reusing one BM25, dense
or hybrid instance for another story replaces its index, even if passage IDs and
text coincide. A hybrid passes the original corpus metadata to every component.
The model/encoder can be reused across stories; passage vectors and indexes cannot.
Cache files now live under `<cache_root>/<story_id>/<model_revision_hash>.json`.
Old root-level cache files are ignored, with no automatic migration. Story IDs
must be safe portable single path components (no separators, traversal or Windows
device names); removing one story's directory leaves other stories intact.
The legacy private-pack adapter has no manifest identity and assigns its own
`private-<pack_directory_name>` namespace, separately from manifest-backed stories.

Tokenizer selection follows **source** language, independently of query language:
`ja` uses the unchanged `BM25LexicalV1` / `jp_simple_lexical_v1`, preserving all
recorded Japanese-source scores. `ko` and `zh` use the new versioned
`cjk_lexical_v1.py:cjk_words_bigrams_v1`: NFKC/casefold, alphanumeric words retained
(including Korean whitespace words), plus adjacent bigrams within CJK/Hangul runs
and singleton script tokens. Punctuation/whitespace stop bigrams. Lossless ASCII
token serialization lets it reuse frozen BM25 scoring without changing that
module. This is a small **untuned baseline**, not a morphological or tuned ko/zh
tokenizer. Other/unknown source languages raise a clear BM25 error, including in
hybrids. Dense retrieval remains language-agnostic.

Synthetic tests use two tiny manifests with the same name and passage IDs, test
API and CLI switching with fake encoders, warm-cache isolation/deletion, identical
text across stories, unsafe IDs and language selection. No new real-model test
gate or protected-path change is needed.

## Retrievers and tokenizer

- `bm25` / `bm25_v0`, version `0`: wraps the unchanged `BM25LexicalV1`, k1=1.2,
  b=0.75, tokenizer `jp_simple_lexical_v1`.
- `dense_e5` / `dense_e5_small_v0`, version `0+614241f`: defaults to
  `intfloat/multilingual-e5-small` on CPU with normalized embeddings. It applies
  `query: ` and `passage: ` prefixes and computes cosine similarity in Python.
  An optional encoder callable enables offline tests. Sentence-transformers is
  imported inside the lazy loader on first encoding, never at module import or
  retriever construction. Invalid embedding counts/dimensions/values fail clearly.
- `dense_e5_large` / `dense_e5_large_v0`, version `0+3d7cfbd`: uses
  `intfloat/multilingual-e5-large` with the same encoding and ranking contract.
  The factory uses batch size 4 for large and 32 for small. The constructor accepts
  `model_name`, `revision` and `batch_size`; a known model selects its pinned
  revision by default. An unknown model requires an explicit revision and uses
  the stable name `dense_e5_custom_v0`. Versions contain the first seven revision
  characters; the full default revisions are listed below.
- `hybrid` / `hybrid_rrf_v0`: combines BM25 and e5-small rankings with
  `sum(1 / (60 + rank))`, searching each component to depth `max(k, 100)` and
  applying the same deterministic tie-break. `hybrid_large` /
  `hybrid_rrf_large_v0` substitutes e5-large. Hybrid versions include the component
  names and versions. Components can also be supplied directly.

`RETRIEVER_NAMES` supplies the choices for both CLIs and the factory. Dense loaders
set `max_seq_length = 512`, call `eval()`, seed torch with 42 and enable deterministic
algorithms (`warn_only=True`). Encoding requests normalized embeddings, the configured
batch size and no progress bar. Python normalizes the vectors again and computes
cosine scores; no GPU, translation, reranker or LLM is used.

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

### Embedding cache

Passage caching is opt-in: `DenseE5RetrieverV0(..., cache_dir=None)` and
`make_retriever(name, cache_dir=None)` preserve the previous behavior and write no
cache files. Both CLIs accept `--cache-dir PATH`, including for either hybrid's
dense component. Recommended ignored location: `.local/story_retrieval/embedding_cache/`.

Within each story directory, each model/revision pair has one JSON file named by the SHA-256 of its serialized
identity; entries hash the exact UTF-8 `passage: ` plus text, independent of IDs.
Vectors are stored **after `_unit`**, as round-tripped Python floats (double
precision), without normalizing again on load. Missing unique texts use one ordered
batch. Saves use a same-directory temporary file and `os.replace`; concurrent
writers may lose additions and cause extra encoding, but cannot expose partial
files. Invalid/unreadable files or inconsistent dimensions rebuild; a changed
dimension detected in a new batch or warm query also rebuilds all current vectors.
Queries are never cached. Only supplied passage IDs enter the index, so cached
later-chapter text cannot bypass allowed IDs or the inclusive cutoff.

Offline CPU e5-small CLI timing on 2026-11-15, all 353 public passages, cutoff 5,
`--json`, with the pinned model/environment below:

| Cache state / query | Wall time |
|---|---:|
| Cold / Japanese `お粥 梅` | 21.566 s |
| Warm / Vietnamese `Cháo có mơ muối khi bị ốm` | 18.595 s |
| No cache / Japanese | 23.524 s |
| No cache / Vietnamese | 22.343 s |

Both cached JSON outputs equal fresh uncached runs exactly, including hits/scores;
Unicode query echoes were checked. Timings include process start, torch import, model
loading and query encoding, which dominate for e5-small on 353 passages: a warm cache
saves only about 4 s (roughly 17%) per CLI call here. The cache matters more for larger
corpora and for e5-large (not timed); for many queries, the bigger saving is to keep one
process and one retriever alive, which this CLI does not do.
Outputs/logs: `.local/m6_embedding_cache_check/utf8/` only.

Verification: compile, policy and suites pass (889 tests, 19 retrieval tests, seven
declared gates). The unchanged Windows diff-coverage guard reports 0% and exits 1.
Direct coverage: 348/359 lines (96.9%; 97% including branches); normalized coverage
of this change: 61/61 executable `tools/` lines (100%). Gate/coverage logs:
`.local/m6_embedding_cache_check/`.

### Real-model environment

The 2026-11-15 runs used a separate Python 3.13 environment with CPU inference:
torch `2.15.0+cpu`, sentence-transformers `6.3.0`, transformers `5.23.0`. Both
snapshots were already in the local HuggingFace cache; no downloads were made.

| Model | Pinned revision |
|---|---|
| `intfloat/multilingual-e5-small` | `614241f622f53c4eeff9890bdc4f31cfecc418b3` |
| `intfloat/multilingual-e5-large` | `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3` |

With torch and sentence-transformers installed (they are not CI requirements) and the
models cached, run offline from the repository root:

```
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m tools.story_retrieval.evaluate_v0 --retriever bm25 dense_e5 dense_e5_large hybrid hybrid_large --json
```

Tests and the quality gate run in an environment without torch, as in CI, so the dense
code is exercised there only through injected encoders. Raw JSON and logs of these runs
stay in the git-ignored `.local/` directory.

## Public DEV evaluation (2026-11-15)

The fixture contains 10 implementer-authored probes: five Japanese and five
Vietnamese, with cutoffs varying across chapters 1-5. Gold was selected by reading
the actual `load_scope` passages. Each probe has one gold passage, so Hit, Recall
and Full Evidence Success coincide at every reported depth. This is a tiny, paired
DEV set, not a sealed benchmark. One probe changes a language score by 20 percentage
points (10 points overall); the results do not establish general multilingual quality.

All five retrievers below ran on the actual public passages. MRR in this DEV table
is through rank 10 (`mrr@10` in the public JSON). The JSON now also reports
full positive eligible-ranking `mrr`, independent of the requested metric depths;
per-probe ranking rows remain limited to the largest requested depth. Full MRR
for the dense retrievers has not been recomputed. Spoiler violation is zero at
every reported depth for every retriever and language.

| Retriever | Group (probes) | Hit/Recall/Success@1 | @5 | @10 | MRR@10 |
|---|---|---:|---:|---:|---:|
| `bm25_v0` | Overall (10) | 30.00% | 50.00% | 50.00% | 0.4000 |
| `bm25_v0` | ja (5) | 60.00% | 100.00% | 100.00% | 0.8000 |
| `bm25_v0` | vi (5) | 0.00% | 0.00% | 0.00% | 0.0000 |
| `dense_e5_small_v0` | Overall (10) | 60.00% | 80.00% | 80.00% | 0.6750 |
| `dense_e5_small_v0` | ja (5) | 100.00% | 100.00% | 100.00% | 1.0000 |
| `dense_e5_small_v0` | vi (5) | 20.00% | 60.00% | 60.00% | 0.3500 |
| `dense_e5_large_v0` | Overall (10) | 60.00% | 90.00% | 100.00% | 0.7200 |
| `dense_e5_large_v0` | ja (5) | 80.00% | 100.00% | 100.00% | 0.8667 |
| `dense_e5_large_v0` | vi (5) | 40.00% | 80.00% | 100.00% | 0.5733 |
| `hybrid_rrf_v0` | Overall (10) | 50.00% | 80.00% | 80.00% | 0.6250 |
| `hybrid_rrf_v0` | ja (5) | 80.00% | 100.00% | 100.00% | 0.9000 |
| `hybrid_rrf_v0` | vi (5) | 20.00% | 60.00% | 60.00% | 0.3500 |
| `hybrid_rrf_large_v0` | Overall (10) | 60.00% | 90.00% | 100.00% | 0.7367 |
| `hybrid_rrf_large_v0` | ja (5) | 80.00% | 100.00% | 100.00% | 0.9000 |
| `hybrid_rrf_large_v0` | vi (5) | 40.00% | 80.00% | 100.00% | 0.5733 |

Evaluation indexes all 353 public passages once per retriever and filters eligible
IDs at each probe cutoff. BM25 statistics use the full public pack. The API returns
overall/language means and public per-probe IDs/ranks without source text; the CLI
outputs aggregates and retriever versions only.

## Private CUTOFF_FILTERED comparison

The local comparison uses 15 probes and 97 original parent chunks under
`.local/story_integration/otonari_30ch/`: `LONG_RANGE_PROBE_V1/probes.yaml` and
`PARAGRAPH_PACK_V1/chunks.jsonl`. Both files match the input SHA-256 values in
both recorded M1 dense result artifacts. Chunk text is used unchanged; internal
pipeline passage IDs map back to the original chunk IDs for canonical multi-gold
metrics. The full pack is indexed and candidates are filtered by inclusive cutoff.
Only aggregates and retriever versions leave `evaluate_private`; no private text,
queries, IDs or per-probe results are written to tracked files. Missing input files
return `None`, and an empty chunk pack yields zero metrics.

Private `mrr` now uses the full positive eligible ranking, matching the M1 depth
convention. `mrr@10` explicitly preserves the former truncated measurement. Hit,
Recall, Success and spoiler violation are reported at 1, 3, 5, 10 and 20. All
spoiler violations are zero.

| Retriever / recorded M1 baseline | Hit@10 | Recall@10 | Full Evidence Success@10 | MRR (full) | MRR@10 |
|---|---:|---:|---:|---:|---:|
| `bm25_v0` (this run) | 20.00% | 8.89% | 0.00% | 0.1333333333 | 0.1333333333 |
| `BM25_LEXICAL_V1` (recorded) | 20.00% | 8.89% | 0.00% | 0.1333333333 | - |
| `dense_e5_small_v0` (this run) | 93.33% | 56.67% | 20.00% | 0.3446296296 | 0.3429629630 |
| `DENSE_E5_SMALL_V1` (recorded) | 93.33% | 56.67% | 20.00% | 0.3446296296 | - |
| `dense_e5_large_v0` (this run) | 80.00% | 57.78% | 26.67% | 0.4208559277 | 0.4077777778 |
| `DENSE_E5_LARGE_V1` (recorded) | 80.00% | 57.78% | 26.67% | 0.4208559277 | - |
| `hybrid_rrf_v0` (this run) | 93.33% | 56.67% | 20.00% | 0.3646296296 | 0.3629629630 |
| `hybrid_rrf_large_v0` (this run) | 80.00% | 57.78% | 26.67% | 0.4373471558 | 0.4244444444 |

| Retriever | Hit@20 | Recall@20 | Full Evidence Success@20 |
|---|---:|---:|---:|
| `bm25_v0` | 20.00% | 8.89% | 0.00% |
| `dense_e5_small_v0` | 93.33% | 73.33% | 53.33% |
| `dense_e5_large_v0` | 100.00% | 82.22% | 60.00% |
| `hybrid_rrf_v0` | 93.33% | 73.33% | 53.33% |
| `hybrid_rrf_large_v0` | 100.00% | 82.22% | 60.00% |

**Reproduction: PASS for both dense variants.** Hit@10, Recall@10, Success@10 and
full MRR are exactly equal as parsed floats to the recorded M1 results, not merely
equal after rounding. BM25 also reproduces its recorded comparison metrics. No
private-probe tuning was performed.

The V1 modules were checked: both use the same pinned revisions, `query: ` /
`passage: ` prefixes, max length 512, original parent-chunk text, normalized cosine
and cutoff eligibility. V1 uses NumPy float32 dot products and chunk-ID ties; v0
renormalizes in Python and uses natural passage-ID ties. These implementation
differences do not change the reported comparison aggregates here; exact ranking
or score identity with V1 was not claimed or tested. The older large run used
sentence-transformers 6.0.1, transformers 5.17.0 and torch 2.14.0+cpu; the current
versions still reproduce its aggregates. Using depth-10 MRR instead of full MRR
would incorrectly suggest a mismatch, especially for large (0.4077777778 versus
0.4208559277).

### Determinism and runtime

The full five-retriever DEV + private command completed successfully in
**1373.231 seconds (22m 53.2s)**. A separate fresh-process e5-small-only command
(`--retriever dense_e5 --json`) completed successfully in **207.732 seconds
(3m 27.7s)**. All e5-small DEV overall/per-language aggregates, private aggregates
and versions are identical across those two runs (exact JSON value equality).
E5-large and both hybrids were evaluated once; no repeat-determinism claim is
made for them. The automatically queued second full run was cancelled and is
not used as evidence.

These are end-to-end wall times including model loading, both corpora and query
encoding. Validation and the small repeat overlapped the full CPU evaluation, so
they are reproducibility timings, not controlled throughput measurements. No
per-model timing was instrumented. Raw aggregate JSON: `run1.json` and
`small_repeat.json`; versions/timings, aggregate comparison checks and logs remain
under `.local/m6_dense_followup/` only.

BM25 cannot bridge the five Vietnamese queries to Japanese source evidence.
E5-small retrieves three of five Vietnamese gold passages by rank 10 (MRR@10
0.3500), and e5-large retrieves all five (MRR@10 0.5733). On Vietnamese probes the
hybrids match their respective dense components; on the private probes, hybrid
fusion changes MRR but leaves Hit/Recall/Success@10 and @20 unchanged. Larger
capacity therefore does not dominate every metric: private small has higher
Hit@10, while private large has higher full-evidence completion and MRR.

## Verification and limits

In CI (Linux, PR #5) `python -m tools.ci.check --coverage` passes on every commit; at
commit `ecf9e9d` it reported diff coverage of 97.0% of 366 changed executable `tools/`
lines (97.5% of 281 for the first version). On the Windows development machine the same
gate passes compile, test policy and all suites (889 tests at `ecf9e9d`, zero
failures/skips, seven declared environment gates), but the
protected diff-coverage guard reports 0%: coverage JSON keys there are relative paths
with backslashes, which the guard does not normalise. The guard was not changed or
bypassed; the figures below were computed with its own functions on normalised keys.
The final gate run took 255.3 seconds while CPU model evaluation was also active.

Suite counts: canonical_story 99, ci 26, script_quality 64, story_benchmark 193
(six gates), story_extraction 362, story_ingestion 79 (one gate), story_memory 7,
story_pipeline 40, story_retrieval 16. The dense V1 tests remain gated exactly as
in CI because the gate environment has no ML stack.

Direct coverage from `.local/ci/coverage/.coverage`:

| Module | Statements covered | Coverage report (including branches) |
|---|---:|---:|
| `retrieval_v0.py` | 161/170 | 95% |
| `evaluate_v0.py` | 89/90 | 98% |
| `retrieve.py` | 42/43 | 96% |
| `__init__.py` | 0/0 | 100% |
| Total | 292/303 (96.4%) | 96% |

An independent read-only calculation normalizing coverage paths and including
working-tree changes gives **33/38 = 86.8%** executable-line coverage for this
follow-up (`git diff HEAD`) and **292/303 = 96.4%** for the branch plus working
tree (`git diff origin/main`). Only the real loader body is uncovered among this
follow-up's changed executable lines. Raw gate and direct-coverage logs are under
`.local/m6_dense_followup/`.

The retrieval tests cover real public loading/Japanese retrieval, cutoff/window
validation, defensive filtering, natural ties, positive-score policy, Unicode
JSON/schema and CLI output/errors, dense cosine/prefixes, RRF arithmetic, index
reuse/replacement and import isolation. They check each model's name, revision,
batch size, lazy loader arguments and both CLIs' shared choices without torch.
Evaluation tests validate public gold and exercise the private adapter using a
tiny synthetic temporary pack only, including first-gold ranks 11, 20 and 21 to
separate full MRR, mrr@10 and the depth-20 boundary.

Dense and hybrid tests use deterministic injected encoders without torch. No
real-model gated test was added: `tests/environment_gates.yaml` is protected and
adding such a gate requires an owner decision. The actual dense model and its
multilingual retrieval quality are evaluated separately in the ML environment.
No new dependencies, network access, Gemini or other LLM calls are involved in
this implementation.

BM25 cannot bridge Vietnamese queries to Japanese evidence: all five Vietnamese
DEV probes score zero on Hit/Recall/Success and MRR. Hangul remains word-level.
The dev set is small, paired and authored by the implementer, not sealed. There
are only five probes per language: a difference of one probe is 20 percentage
points in that language (10 points overall). Dense models truncate at 512 tokens;
the historical private pack has 77/97 passages above that limit. There is no
reranker or Story Brief integration; phase 2 is not started.

## Dev probe set v1

The 2026-11-15 follow-up uses
`tests/story_retrieval/fixtures/dev_probes_v1.yaml`. The implementer read all 353
passages returned by `build_corpus(DEFAULT_MANIFEST, 5)`, authored the questions
and gold without running a retriever on v1, then printed and reread every gold
passage and checked its chapter against the cutoff. The fixture was locked before
evaluation with SHA-256:

`e7af4a47b0ef02b9847ce812cff28298c4356407dcecad344e0b48827caa1a36`

This is still a small implementer-authored DEV set, not a sealed benchmark or an
independent assessment of general multilingual retrieval. The Vietnamese questions
ask different facts from the Japanese questions; there are zero deliberate
cross-language pairs. Vietnamese wording follows recap/brief requests, using
Amane, Mahiru and Itsuki or descriptive references. Language scores consequently
compare different questions, rather than isolating a translation effect.

| Category | ja | vi | Total |
|---|---:|---:|---:|
| character_fact | 3 | 3 | 6 |
| event | 3 | 3 | 6 |
| relationship | 3 | 3 | 6 |
| recap | 3 | 3 | 6 |
| boundary | 3 | 3 | 6 |
| Total | 15 | 15 | 30 |

Cutoff counts for chapters 1/2/3/4/5 are 7/7/6/5/5. Twelve probes specify a
multi-passage answer (eight ja, four vi): eleven require two passages and one
requires three. Two probes accept alternative singleton evidence sets: the
temperature reading versus its spoken report, and initial caution expressed in
eyes versus voice. The six boundary probes have tempting text in a later chapter
but gold only at or before cutoff:

| Probe | Cutoff | Tempting chapter | Earlier answer |
|---|---:|---:|---|
| v1_ja_13 | 1 | 4 | Her nearly tearful look and his troubled conscience motivate intervention. |
| v1_ja_14 | 2 | 4 | She already says her presence caused his cold. |
| v1_ja_15 | 4 | 5 | He already expects them to be mere acquaintances the next day. |
| v1_vi_13 | 1 | 5 | He already separates attraction from romantic feelings. |
| v1_vi_14 | 2 | 3 | His poor housekeeping and messy room are already described. |
| v1_vi_15 | 2 | 5 | His reply already identifies Itsuki as having a girlfriend. |

Gold corrections after lock: **none**. The locked fixture remains unchanged.
The v0 fixture and recorded v0 results above are unchanged. The CLI now accepts
`--probes PATH`, defaulting to v0, and reports `per_category` means only when
categories are present. Untagged probes still contribute to overall/language
means but not category means. Per-probe output and metric definitions are unchanged.

Reproduction in an environment with torch and sentence-transformers, with both
model snapshots already cached:

```
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 python -m tools.story_retrieval.evaluate_v0 --probes tests/story_retrieval/fixtures/dev_probes_v1.yaml --retriever bm25 dense_e5 dense_e5_large hybrid hybrid_large --cache-dir .local/story_retrieval/embedding_cache --private-root .local/none --json
```

The run indexes all 353 passages and filters eligible IDs at each cutoff; the
nonexistent private root skips private evaluation. Hit and full MRR use the union
of acceptable gold passages. Recall uses the best-matching gold set; Success
requires every passage of any one gold set. MRR below covers the full positive
eligible ranking, not just ten hits. Spoiler violation is measured at 1, 5 and 10.
Raw JSON, per-probe ranks and local profiling logs stay under
`.local/m6_dev_v1/`; passage embeddings stay under the requested ignored cache.

### V1 results

Labels below correspond to the existing v0 retriever names and pinned revisions
above. SV is the maximum spoiler violation across depths 1/5/10; each individual
depth is also zero. The first table groups by language, the second by category,
and the third isolates the twelve multi-passage probes. Percentages are probe
means, including best-set Recall; MRR is untruncated.

| Group | Retriever | Hit@1 | Hit@5 | Hit@10 | Recall@10 | Success@10 | MRR (full) | SV |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Overall (30) | BM25 | 33.33% | 36.67% | 36.67% | 36.67% | 36.67% | 0.3461 | 0 |
| Overall (30) | E5-small | 23.33% | 50.00% | 66.67% | 57.22% | 46.67% | 0.3841 | 0 |
| Overall (30) | E5-large | 43.33% | 70.00% | 76.67% | 68.33% | 60.00% | 0.5522 | 0 |
| Overall (30) | Hybrid-small | 36.67% | 53.33% | 60.00% | 52.22% | 43.33% | 0.4616 | 0 |
| Overall (30) | Hybrid-large | 43.33% | 66.67% | 73.33% | 65.00% | 56.67% | 0.5524 | 0 |
| ja (15) | BM25 | 66.67% | 73.33% | 73.33% | 73.33% | 73.33% | 0.6923 | 0 |
| ja (15) | E5-small | 20.00% | 60.00% | 86.67% | 76.67% | 66.67% | 0.4139 | 0 |
| ja (15) | E5-large | 46.67% | 73.33% | 80.00% | 73.33% | 66.67% | 0.5857 | 0 |
| ja (15) | Hybrid-small | 46.67% | 66.67% | 73.33% | 66.67% | 60.00% | 0.5689 | 0 |
| ja (15) | Hybrid-large | 46.67% | 66.67% | 73.33% | 66.67% | 60.00% | 0.5861 | 0 |
| vi (15) | BM25 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.0000 | 0 |
| vi (15) | E5-small | 26.67% | 40.00% | 46.67% | 37.78% | 26.67% | 0.3544 | 0 |
| vi (15) | E5-large | 40.00% | 66.67% | 73.33% | 63.33% | 53.33% | 0.5186 | 0 |
| vi (15) | Hybrid-small | 26.67% | 40.00% | 46.67% | 37.78% | 26.67% | 0.3544 | 0 |
| vi (15) | Hybrid-large | 40.00% | 66.67% | 73.33% | 63.33% | 53.33% | 0.5186 | 0 |

| Group | Retriever | Hit@1 | Hit@5 | Hit@10 | Recall@10 | Success@10 | MRR (full) | SV |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| character_fact (6) | BM25 | 33.33% | 33.33% | 33.33% | 33.33% | 33.33% | 0.3349 | 0 |
| character_fact (6) | E5-small | 16.67% | 66.67% | 66.67% | 66.67% | 66.67% | 0.4015 | 0 |
| character_fact (6) | E5-large | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 1.0000 | 0 |
| character_fact (6) | Hybrid-small | 16.67% | 50.00% | 50.00% | 50.00% | 50.00% | 0.3547 | 0 |
| character_fact (6) | Hybrid-large | 83.33% | 83.33% | 83.33% | 83.33% | 83.33% | 0.8444 | 0 |
| event (6) | BM25 | 16.67% | 16.67% | 16.67% | 16.67% | 16.67% | 0.1798 | 0 |
| event (6) | E5-small | 16.67% | 16.67% | 50.00% | 50.00% | 50.00% | 0.2223 | 0 |
| event (6) | E5-large | 33.33% | 33.33% | 66.67% | 58.33% | 50.00% | 0.3876 | 0 |
| event (6) | Hybrid-small | 16.67% | 16.67% | 33.33% | 33.33% | 33.33% | 0.2018 | 0 |
| event (6) | Hybrid-large | 16.67% | 16.67% | 50.00% | 50.00% | 50.00% | 0.2398 | 0 |
| relationship (6) | BM25 | 50.00% | 50.00% | 50.00% | 50.00% | 50.00% | 0.5000 | 0 |
| relationship (6) | E5-small | 16.67% | 50.00% | 83.33% | 66.67% | 50.00% | 0.3382 | 0 |
| relationship (6) | E5-large | 33.33% | 83.33% | 83.33% | 75.00% | 66.67% | 0.5250 | 0 |
| relationship (6) | Hybrid-small | 66.67% | 66.67% | 83.33% | 75.00% | 66.67% | 0.6854 | 0 |
| relationship (6) | Hybrid-large | 66.67% | 100.00% | 100.00% | 83.33% | 66.67% | 0.8056 | 0 |
| recap (6) | BM25 | 33.33% | 50.00% | 50.00% | 50.00% | 50.00% | 0.3750 | 0 |
| recap (6) | E5-small | 50.00% | 83.33% | 100.00% | 69.44% | 33.33% | 0.6905 | 0 |
| recap (6) | E5-large | 16.67% | 83.33% | 83.33% | 58.33% | 33.33% | 0.4040 | 0 |
| recap (6) | Hybrid-small | 66.67% | 100.00% | 100.00% | 69.44% | 33.33% | 0.7917 | 0 |
| recap (6) | Hybrid-large | 16.67% | 83.33% | 83.33% | 58.33% | 33.33% | 0.4179 | 0 |
| boundary (6) | BM25 | 33.33% | 33.33% | 33.33% | 33.33% | 33.33% | 0.3409 | 0 |
| boundary (6) | E5-small | 16.67% | 33.33% | 33.33% | 33.33% | 33.33% | 0.2680 | 0 |
| boundary (6) | E5-large | 33.33% | 50.00% | 50.00% | 50.00% | 50.00% | 0.4443 | 0 |
| boundary (6) | Hybrid-small | 16.67% | 33.33% | 33.33% | 33.33% | 33.33% | 0.2745 | 0 |
| boundary (6) | Hybrid-large | 33.33% | 50.00% | 50.00% | 50.00% | 50.00% | 0.4541 | 0 |

| Group | Retriever | Hit@1 | Hit@5 | Hit@10 | Recall@10 | Success@10 | MRR (full) | SV |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Multi all (12) | BM25 | 58.33% | 66.67% | 66.67% | 66.67% | 66.67% | 0.6042 | 0 |
| Multi all (12) | E5-small | 41.67% | 75.00% | 91.67% | 68.06% | 41.67% | 0.5963 | 0 |
| Multi all (12) | E5-large | 33.33% | 83.33% | 83.33% | 62.50% | 41.67% | 0.5062 | 0 |
| Multi all (12) | Hybrid-small | 66.67% | 91.67% | 91.67% | 72.22% | 50.00% | 0.7719 | 0 |
| Multi all (12) | Hybrid-large | 41.67% | 91.67% | 91.67% | 70.83% | 50.00% | 0.6117 | 0 |
| Multi ja (8) | BM25 | 87.50% | 100.00% | 100.00% | 100.00% | 100.00% | 0.9062 | 0 |
| Multi ja (8) | E5-small | 25.00% | 75.00% | 100.00% | 81.25% | 62.50% | 0.5179 | 0 |
| Multi ja (8) | E5-large | 50.00% | 87.50% | 87.50% | 75.00% | 62.50% | 0.6333 | 0 |
| Multi ja (8) | Hybrid-small | 62.50% | 100.00% | 100.00% | 87.50% | 75.00% | 0.7812 | 0 |
| Multi ja (8) | Hybrid-large | 62.50% | 100.00% | 100.00% | 87.50% | 75.00% | 0.7917 | 0 |
| Multi vi (4) | BM25 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.0000 | 0 |
| Multi vi (4) | E5-small | 75.00% | 75.00% | 75.00% | 41.67% | 0.00% | 0.7532 | 0 |
| Multi vi (4) | E5-large | 0.00% | 75.00% | 75.00% | 37.50% | 0.00% | 0.2519 | 0 |
| Multi vi (4) | Hybrid-small | 75.00% | 75.00% | 75.00% | 41.67% | 0.00% | 0.7532 | 0 |
| Multi vi (4) | Hybrid-large | 0.00% | 75.00% | 75.00% | 37.50% | 0.00% | 0.2519 | 0 |

### V1 CPU cost and pipeline recommendation

A local-only profiling wrapper called the same evaluation CLI entry point and
factory, timing the existing lazy loader and encoder without changing their
outputs. It evaluated each retriever sequentially with the same corpus and
queries. The primary timing run finished before the quality gate started.
Torch used eight CPU threads, with the pinned models and ML versions recorded
above. Initial torch/sentence-transformers imports cost **25.062 s**, separately
from the model-load times below. The profiled CLI body took **257.746 s**,
excluding those imports. BM25's corpus loading/indexing and 30 searches took
**0.343 s**. These are single local wall-time measurements, not controlled
hardware benchmarks or production latency guarantees.

| Retriever | Model load | Missing unique passage texts / encode | 30 query encodes | Mean / median query encode | Evaluation wall |
|---|---:|---:|---:|---:|---:|
| E5-small | 6.486 s | 107 / 5.657 s | 4.120 s | 0.137 / 0.134 s | 17.408 s |
| E5-large | 15.117 s | 353 / 153.226 s | 21.874 s | 0.729 / 0.681 s | 192.805 s |
| Hybrid-small | 6.243 s | 0 / 0 s (warm) | 4.603 s | 0.153 / 0.131 s | 11.790 s |
| Hybrid-large | 14.956 s | 0 / 0 s (warm) | 18.623 s | 0.621 / 0.577 s | 35.256 s |

Model-load timing excludes dependency imports and includes model construction,
configuration and deterministic setup. Encode timing is inside the existing
encoder, excluding Python vector normalization and cosine scoring. Passage cache
coverage differs, so the two cold/partial-cache evaluation wall times are not a
fair model-speed ratio. The same thirty uncached queries give the useful comparison:
large query encoding averages about **5.3 times** small in the dense runs, and
about **4.0 times** small in the warm hybrid runs. Large model loading is about
2.3 times small. Keeping a retriever alive avoids repeated model loading; the
passage cache does not cache query embeddings.

**Recommend `dense_e5_large` provisionally for completeness-sensitive passage retrieval,
at a writer delivery depth chosen from the completeness curve below**,
whose briefs commonly use Vietnamese, with `dense_e5` as the explicitly selected
lower-latency CPU option. Large retrieves some gold for 11/15 Vietnamese probes
at rank ten versus 7/15 for small, and completes 8/15 versus 4/15; Vietnamese
Recall@10 rises from 37.78% to 63.33%. Overall Recall/Success@10 rises from
57.22%/46.67% to 68.33%/60.00%, and full MRR from 0.3841 to 0.5522. This quality
gain supports paying the measured load and query-encoding cost for that use case.
The primary comparison is Recall and Full_Evidence_Success at the actual delivery
depth; these historical @10 facts do not recommend a ten-passage writer budget.
Character-life completeness instead depends on exhaustive M4 extraction persisted
by M5, with retrieval supplying a safety net and quotes/callbacks.

Large does **not** dominate multi-passage retrieval: small's multi-passage
Recall@10 is 68.06% versus large's 62.50%, with both completing only 5/12.
Hybrid-small is strongest there on recall (72.22%, 6/12 complete), while
hybrid-large reaches 70.83% and also 6/12. Both dense variants and both hybrids
complete **zero of the four Vietnamese multi-passage probes**; small has higher
partial recall there (41.67% versus 37.50%). This is evidence against treating a
top-ten hit as sufficient context for a recap, and it leaves multi-evidence
completion unresolved for the later pipeline integration. Category results also
favor small on recap recall, while large's advantage is strongest on character
facts. Only 3/6 boundary probes have a gold hit at ten with large, despite all
six remaining spoiler-safe.

The current equal-weight RRF variants are not the default recommendation:
hybrid-large has lower overall Hit/Recall/Success@10 than dense-large
(73.33%/65.00%/56.67% versus 76.67%/68.33%/60.00%), with nearly identical MRR.
Neither hybrid improves Vietnamese metrics over its dense component because BM25
returns no Vietnamese matches. BM25 remains cheap and strong on these Japanese
multi-passage questions, but its 0/15 Vietnamese hits rule it out as a common
multilingual default. No retriever or pipeline behavior was tuned or changed in
response to these results.

One probe still changes an overall score by 3.33 percentage points and a language
score by 6.67 points; the multi-passage Vietnamese subset has only four probes.
The Japanese and Vietnamese multi-passage mixes are also unequal (8 versus 4).
The default recommendation is therefore provisional, based on this small public
DEV set, the measured CPU cost, and the pipeline's Vietnamese query use case.

### V1 verification

The direct `-m tools.story_retrieval.evaluate_v0` command above exited **0**.
Its aggregate JSON, including all five retriever versions and the skipped private
section, exactly equals the profiling run's JSON. This warm-cache check overlapped
the gate and is used for output verification only, not the timing comparison.
Raw outputs are `.local/m6_dev_v1/evaluation_cli.json`, `evaluation.json` and
`per_probe.json`; timings are `timings.json`. The local timing wrapper's initial
PowerShell invocation reported status 1 after formatting stderr progress as native
errors, although it produced complete JSON; the subsequent direct CLI check removes
that shell-status ambiguity. No model download, Gemini or other LLM call occurred.

On the Windows development machine, the gate in an environment without torch
(`python -m tools.ci.check --coverage`) passes compile,
test policy and all nine suites: **890 tests, zero failures/skips, seven declared
environment gates**. Exact suite lines:

```text
  OK   canonical_story    ran   99  failed   0  skipped   0  gated   0  9.18s
  OK   ci                 ran   26  failed   0  skipped   0  gated   0  43.23s
  OK   script_quality     ran   64  failed   0  skipped   0  gated   0  7.37s
  OK   story_benchmark    ran  193  failed   0  skipped   0  gated   6  32.81s
  OK   story_extraction   ran  362  failed   0  skipped   0  gated   0  50.93s
  OK   story_ingestion    ran   79  failed   0  skipped   0  gated   1  4.46s
  OK   story_memory       ran    7  failed   0  skipped   0  gated   0  0.04s
  OK   story_pipeline     ran   40  failed   0  skipped   0  gated   0  2.41s
  OK   story_retrieval    ran   20  failed   0  skipped   0  gated   0  14.37s
```

The unchanged Windows guard still misreads relative backslash coverage keys:

```text
diff coverage: 0.0% of 523 changed executable lines under tools/
QUALITY GATE: FAIL (guards)
```

The gate therefore exits **1**, solely for this known false diff-coverage failure;
it is not an overall gate pass. The guard was neither changed nor bypassed.
Direct coverage from this gate's `.local/ci/coverage/.coverage` is:

| Module | Covered statements | Coverage including branches |
|---|---:|---:|
| `evaluate_v0.py` | 99/100 | 98% |
| `retrieval_v0.py` | 219/228 | 96% |
| `retrieve.py` | 43/44 | 96% |
| `__init__.py` | 0/0 | 100% |
| Total | 361/372 (97.0%) | 97% |

A read-only calculation using the guard's `diff_coverage_findings`, normalizing
coverage keys to forward slashes and parsing `git diff HEAD -U0 -- tools/`, gives
**7/7 changed executable lines covered (100.0%)**, exceeding the required 80%.
Logs remain in `.local/m6_dev_v1/gate.log` and `direct_coverage.txt`. Tests extend
the existing evaluation file with versioned fixture checks, optional category
aggregation on synthetic probes, and default/explicit CLI probe selection; cases
share bodies through `subTest`. The catalog was regenerated with the prescribed
test-policy command and converted to LF. All changed files use LF. No commit,
push, branch switch, private evaluation or pipeline integration was performed.

## Completeness curve (owner criterion)

The owner's primary criterion is **Full_Evidence_Success (FES) and Recall at the
actual depth handed to the brief writer**, because a missing event or character
fact matters even when an early hit is relevant. Hit@10 and MRR remain useful
secondary diagnostics. Existing results above are retained unchanged.

`evaluate_v0 --k-values INT [INT ...]` now selects reported depths. DEV defaults
remain 1/5/10; private defaults remain 1/3/5/10/20 and private always retains 10
when explicit depths are supplied. Invalid zero/negative depths return CLI exit
2 or raise `ValueError` through the evaluator API. Full-ranking MRR and mrr@10
are unchanged. JSON adds `passages_in_scope` (indexed count and eligible counts
by cutoff), separate from metrics, and DEV adds a `multi_passage` aggregate
(overall and per language); text mode omits scope counts. Multi-passage means
all acceptable gold paths require more than one passage, the same 12-probe
subset used in the earlier tables.

### DEV v1: measured depth curve

Every cell is **Recall % / FES %**; these are macro probe means, not micro unit
recall. Overall n=30, ja/vi n=15 each; multi n=12 (ja 8, vi 4). Spoiler violations
are zero at all six evaluated depths. The set is **implementer-authored**, covers
only **five chapters**, and is neither independent gold nor a sealed benchmark.
One probe moves overall FES by 3.33 points; one Vietnamese multi-passage probe
moves that subgroup by 25 points. These are question-evidence completeness
measurements, not character-dossier completeness measurements.

| Group | Retriever | @10 R / FES | @20 R / FES | @30 R / FES | @50 R / FES |
|---|---|---:|---:|---:|---:|
| Overall (30) | BM25 | 36.67 / 36.67 | 36.67 / 36.67 | 46.67 / 46.67 | 46.67 / 46.67 |
| Overall (30) | E5-small | 57.22 / 46.67 | 63.89 / 56.67 | 67.22 / 60.00 | 83.33 / 80.00 |
| Overall (30) | E5-large | 68.33 / 60.00 | 82.22 / 73.33 | 82.22 / 73.33 | 91.67 / 90.00 |
| Overall (30) | Hybrid-small | 52.22 / 43.33 | 67.22 / 63.33 | 73.89 / 70.00 | 88.33 / 86.67 |
| Overall (30) | Hybrid-large | 65.00 / 56.67 | 88.89 / 83.33 | 90.56 / 86.67 | 95.00 / 93.33 |
| ja (15) | BM25 | 73.33 / 73.33 | 73.33 / 73.33 | 93.33 / 93.33 | 93.33 / 93.33 |
| ja (15) | E5-small | 76.67 / 66.67 | 80.00 / 73.33 | 80.00 / 73.33 | 90.00 / 86.67 |
| ja (15) | E5-large | 73.33 / 66.67 | 83.33 / 73.33 | 83.33 / 73.33 | 93.33 / 93.33 |
| ja (15) | Hybrid-small | 66.67 / 60.00 | 86.67 / 86.67 | 93.33 / 93.33 | 100.00 / 100.00 |
| ja (15) | Hybrid-large | 66.67 / 60.00 | 96.67 / 93.33 | 100.00 / 100.00 | 100.00 / 100.00 |
| vi (15) | BM25 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| vi (15) | E5-small | 37.78 / 26.67 | 47.78 / 40.00 | 54.44 / 46.67 | 76.67 / 73.33 |
| vi (15) | E5-large | 63.33 / 53.33 | 81.11 / 73.33 | 81.11 / 73.33 | 90.00 / 86.67 |
| vi (15) | Hybrid-small | 37.78 / 26.67 | 47.78 / 40.00 | 54.44 / 46.67 | 76.67 / 73.33 |
| vi (15) | Hybrid-large | 63.33 / 53.33 | 81.11 / 73.33 | 81.11 / 73.33 | 90.00 / 86.67 |
| Multi all (12) | BM25 | 66.67 / 66.67 | 66.67 / 66.67 | 66.67 / 66.67 | 66.67 / 66.67 |
| Multi all (12) | E5-small | 68.06 / 41.67 | 76.39 / 58.33 | 76.39 / 58.33 | 83.33 / 75.00 |
| Multi all (12) | E5-large | 62.50 / 41.67 | 80.56 / 58.33 | 80.56 / 58.33 | 95.83 / 91.67 |
| Multi all (12) | Hybrid-small | 72.22 / 50.00 | 84.72 / 75.00 | 84.72 / 75.00 | 87.50 / 83.33 |
| Multi all (12) | Hybrid-large | 70.83 / 50.00 | 88.89 / 75.00 | 93.06 / 83.33 | 95.83 / 91.67 |
| Multi ja (8) | BM25 | 100.00 / 100.00 | 100.00 / 100.00 | 100.00 / 100.00 | 100.00 / 100.00 |
| Multi ja (8) | E5-small | 81.25 / 62.50 | 87.50 / 75.00 | 87.50 / 75.00 | 93.75 / 87.50 |
| Multi ja (8) | E5-large | 75.00 / 62.50 | 81.25 / 62.50 | 81.25 / 62.50 | 100.00 / 100.00 |
| Multi ja (8) | Hybrid-small | 87.50 / 75.00 | 100.00 / 100.00 | 100.00 / 100.00 | 100.00 / 100.00 |
| Multi ja (8) | Hybrid-large | 87.50 / 75.00 | 93.75 / 87.50 | 100.00 / 100.00 | 100.00 / 100.00 |
| Multi vi (4) | BM25 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 |
| Multi vi (4) | E5-small | 41.67 / 0.00 | 54.17 / 25.00 | 54.17 / 25.00 | 62.50 / 50.00 |
| Multi vi (4) | E5-large | 37.50 / 0.00 | 79.17 / 50.00 | 79.17 / 50.00 | 87.50 / 75.00 |
| Multi vi (4) | Hybrid-small | 41.67 / 0.00 | 54.17 / 25.00 | 54.17 / 25.00 | 62.50 / 50.00 |
| Multi vi (4) | Hybrid-large | 37.50 / 0.00 | 79.17 / 50.00 | 79.17 / 50.00 | 87.50 / 75.00 |

### Private: aggregates only

| Retriever (15 probes) | @10 R / FES | @20 R / FES | @30 R / FES | @50 R / FES |
|---|---:|---:|---:|---:|
| E5-small | 56.67 / 20.00 | 73.33 / 53.33 | 82.22 / 66.67 | 91.11 / 80.00 |
| E5-large | 57.78 / 26.67 | 82.22 / 60.00 | 91.11 / 80.00 | 93.33 / 86.67 |

**Private reproduction: PASS.** Both dense models reproduce the Recall and FES
values at @10/@20/@30/@50 from the recorded M1-30CH-K completeness curve (its F
and K columns). The sole parsed-float difference is large Recall@20:
0.8222222222222223 versus recorded 0.8222222222222222 (1.11e-16). Recomputing
all depths from both frozen per-probe rankings with this evaluator's Python
mean exactly matches every current Recall/FES value, confirming aggregation
roundoff rather than a changed completeness result. Hit@10, Recall@10,
Success@10 and full MRR also exactly match their recorded M1 result artifacts;
the frozen probe/chunk input hashes match. This is reproduction, with no private
probe tuning. No private queries, character names, text or IDs are published.
None of these tested private depths reaches 100% Recall or FES: small reaches
91.11% / 80.00% at 50; large reaches 93.33% / 86.67%. Private hybrids and BM25
were not rerun beyond their previously recorded depths; no new private depth
claim is made for them.

### Passages in scope

DEV indexes 353 passages for unchanged corpus statistics and filters eligible
IDs by inclusive cutoff. Private indexes the original 97 parent chunks; their
sizes are different from public paragraph passages. Depth is therefore not a
comparable token budget between these corpora.

| DEV cutoff | Eligible passages | 50 / eligible |
|---|---:|---:|
| 1 | 61 | 81.97% |
| 2 | 143 | 34.97% |
| 3 | 246 | 20.33% |
| 4 | 313 | 15.97% |
| 5 | 353 | 14.16% |

| Private cutoff | Eligible parent chunks | min(50, eligible) / eligible |
|---|---:|---:|
| 10 | 30 | 100.00% |
| 15 | 47 | 100.00% |
| 18 | 57 | 87.72% |
| 21 | 68 | 73.53% |
| 24 | 79 | 63.29% |
| 28 | 90 | 55.56% |
| 30 | 97 | 51.55% |

Counts are aggregates, not positive-score candidate counts. A retriever can
return fewer than k, and lexical zero-score evidence remains unreachable by
increasing k. At the full private cutoff 50 is 51.55% of the 97-chunk corpus.
For hybrids this curve truncates the evaluator's **full-pool RRF ranking**
(component depth `max(indexed passage count, 100)`). Reproduce that policy before
truncating context for the writer: a standalone `retrieve --k 50` uses component
depth 100 and its hybrid context has not been validated by this table. Dense and
BM25 rankings do not have that RRF depth distinction. A future pipeline must
measure its actual selection and any later prompt trimming, not assume an
internal candidate-depth score survives the final handoff.

### Interpretation and provisional delivery choice

For an illustrative **80% overall FES** target on DEV, BM25 never reaches it in
the tested range; E5-small needs 50, E5-large needs 50, hybrid-small needs 50,
and hybrid-large first reaches it at 20 (83.33%). At 50 the respective overall
Recall/FES values are 46.67/46.67, 83.33/80.00, 91.67/90.00, 88.33/86.67 and
95.00/93.33 percent. For at least 90% overall Recall, large needs 50 and
hybrid-large needs 30; the other three do not reach it by 50. Hybrid-large
reaches 100% on the Japanese group at 30, and hybrid-small at 50; these small
subgroups do not establish a general guarantee. BM25 has no Vietnamese matches
at any measured depth.

For private **80% FES**, small needs 50 while large needs 30 (both have Recall 91.11%
at those depths). Large improves further to 86.67% FES at 50 but still misses
required evidence. No tested depth provides complete private evidence for every
probe. Earlier M1-30CH-L/M/N/O diagnostics already show why better early ranking
or reranking can leave one required item outside a small delivery budget; their
recorded results and conclusions are unchanged.

**Small-corpus caveat.** Deep values are partly a property of corpus size, not
of ranking quality. At private cutoffs 10 and 15, depth 50 returns every eligible
chunk, and at DEV cutoff 1 it returns 82% of the eligible passages. The @50
figures are therefore optimistic for a multi-volume story, where the same depth
is a far smaller share of the corpus. Read the curve as "how deep the evidence
sits in a 5-chapter / 30-chapter corpus", not as a depth that transfers.

Keep **dense_e5_large at delivery depth 50** as the provisional Vietnamese
pipeline safety-net choice: Vietnamese Recall/FES rises from 63.33/53.33 at ten
to 90.00/86.67 at fifty. Depth 30 is an explicitly lower-completeness/cost option
(private 91.11/80.00; Vietnamese DEV 81.11/73.33). The measured CPU load/query
cost facts above still apply; larger writer context adds unmeasured generation
cost. For mixed Japanese/Vietnamese review content, **hybrid-large at 50 under
the evaluated full-pool fusion policy** is the stronger public completeness
candidate (95.00/93.33 overall), rather than rejecting it from its @10 result.
It ties dense-large on Vietnamese results, and its private @50 behavior remains
unevaluated. Small remains an explicit lower-latency option with lower measured
completeness. These are provisional choices to agree, not a pipeline change or
an accepted quality threshold.

Even at 50, dense-large/hybrid-large complete only 3/4 Vietnamese multi-passage
probes (75%); small/hybrid-small complete 2/4 (50%). Similarity top-k cannot
guarantee exhaustive evidence: a fixed budget can exclude low-similarity facts,
pronouns, aliases, indirect reports and evidence spread across volumes. Increasing
the budget changes this empirical curve, not that guarantee. Character-life
coverage must come from exhaustive M4 mention/identity, event/participant,
information and state-change extraction, persisted by M5 and checked for missing
chapters/records. Today's roster preserves selected chapter-brief facts and is
not exhaustive. Retrieval supplies separately verified safety-net candidates,
quotes and callbacks; review briefs also need an extracted key-event checklist.
See the updated Phase 2 proposal and
`M6_CHARACTER_DOSSIER_EVAL_PROPOSAL_V0.md` (both **PROPOSAL**, no dossier gold or
implementation authored).

### Reproduction and verification for this change

With the already cached pinned models and the offline environment above:

```text
python -m tools.story_retrieval.evaluate_v0 --probes tests/story_retrieval/fixtures/dev_probes_v1.yaml --k-values 1 5 10 20 30 50 --retriever bm25 dense_e5 dense_e5_large hybrid hybrid_large --private-root .local/none --cache-dir .local/story_retrieval/embedding_cache --json
python -m tools.story_retrieval.evaluate_v0 --k-values 10 20 30 50 --retriever dense_e5 dense_e5_large --cache-dir .local/story_retrieval/embedding_cache --json
```

Both commands use `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`, `PYTHONUTF8=1` and
`PYTHONDONTWRITEBYTECODE=1`, with eight CPU threads. DEV historical overall,
language and category metrics are exactly equal to the previous v1 aggregate
JSON. Raw aggregate outputs stay in ignored local storage; passage caches use
per-story directories under the cache root. No network, model download, Gemini or LLM
call, fixture edit, branch switch, commit or push occurred.

Final no-torch gate: compile and test policy pass; all **894 tests** pass, zero
failures/skips, seven unchanged declared environment gates. Exact suite lines:

```text
  OK   canonical_story    ran   99  failed   0  skipped   0  gated   0  5.97s
  OK   ci                 ran   26  failed   0  skipped   0  gated   0  27.71s
  OK   script_quality     ran   64  failed   0  skipped   0  gated   0  6.09s
  OK   story_benchmark    ran  193  failed   0  skipped   0  gated   6  21.11s
  OK   story_extraction   ran  362  failed   0  skipped   0  gated   0  41.3s
  OK   story_ingestion    ran   79  failed   0  skipped   0  gated   1  2.26s
  OK   story_memory       ran    7  failed   0  skipped   0  gated   0  0.02s
  OK   story_pipeline     ran   40  failed   0  skipped   0  gated   0  2.32s
  OK   story_retrieval    ran   24  failed   0  skipped   0  gated   0  7.7s
```

On Windows the diff-coverage guard reports 0% because of a path-separator issue
in the guard (unchanged, not bypassed); CI on Linux runs the full gate. Direct
retrieval coverage is:

| Module | Covered statements | Coverage including branches |
|---|---:|---:|
| `cjk_lexical_v1.py` | 20/20 | 100% |
| `evaluate_v0.py` | 115/116 | 99% |
| `retrieval_v0.py` | 250/259 | 97% |
| `retrieve.py` | 44/45 | 96% |
| Total (including empty `__init__.py`) | 429/440 (97.5%) | 97% |

A read-only calculation with the guard's own `diff_coverage_findings`, normalized
coverage keys and working-tree/new-file changes gives **89/89 changed executable
lines covered (100%)** against HEAD, and **429/440 (97.5%)** against origin/main.
DEV evaluation took 336.282 s; the dense-only command
including historical v0 DEV and private took 307.415 s. These are local runtime
observations, not controlled latency benchmarks.
